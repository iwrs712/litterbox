"""
Sandbox 创建指标收集器。

追踪：
  - 创建事件：耗时、成功/失败、来源（pool 命中 vs 直接创建）
  - 实时快照：当前 running/stopped/creating（由 snapshot 端点注入）

存储：
  - Prometheus Histogram/Counter → /metrics（Prometheus scrape）
  - 内存 deque（1h 滑动窗口）→ /api/v1/metrics/snapshot（前端轮询）
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque, Literal

from prometheus_client import Counter, Histogram

# ── Prometheus 指标 ──────────────────────────────────────────────

SANDBOX_CREATE_DURATION = Histogram(
    "litterbox_sandbox_create_duration_seconds",
    "End-to-end sandbox creation duration (request → pod ready)",
    ["template_id", "success", "source"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 45, 60, 90, 120],
)

SANDBOX_CREATE_TOTAL = Counter(
    "litterbox_sandbox_create_total",
    "Total sandbox create attempts",
    ["template_id", "success", "source"],
)


# ── 内存事件结构 ─────────────────────────────────────────────────

Source = Literal["pool", "direct"]


@dataclass
class _CreateEvent:
    ts: float
    duration: float
    success: bool
    template_id: str
    source: Source      # "pool" = 从预热池取出，"direct" = 现场创建


_WINDOW_SECONDS = 3600  # 1h 滑动窗口


class SandboxMetrics:
    """线程安全的沙盒创建指标收集器（进程内单例）。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._creates: Deque[_CreateEvent] = deque()
        # 实时状态由外部在 snapshot 端点注入
        self._live: dict = {}

    # ── 写入 ─────────────────────────────────────────────────────

    def record_create(
        self,
        *,
        template_id: str,
        duration: float,
        success: bool,
        source: Source = "direct",
    ) -> None:
        """记录一次 allocate/create 事件，在操作完成后调用。"""
        sl = "true" if success else "false"
        SANDBOX_CREATE_DURATION.labels(
            template_id=template_id, success=sl, source=source
        ).observe(duration)
        SANDBOX_CREATE_TOTAL.labels(
            template_id=template_id, success=sl, source=source
        ).inc()
        ev = _CreateEvent(
            ts=time.time(),
            duration=duration,
            success=success,
            template_id=template_id,
            source=source,
        )
        with self._lock:
            self._creates.append(ev)
            self._evict()

    # 向后兼容旧调用点
    def record(self, *, template_id: str, duration: float, success: bool) -> None:
        self.record_create(
            template_id=template_id,
            duration=duration,
            success=success,
            source="direct",
        )

    def set_live_stats(self, stats: dict) -> None:
        """注入当前实时状态（由 snapshot 端点在调用前填入）。"""
        with self._lock:
            self._live = stats

    # ── 读取 ─────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """
        返回供前端消费的完整 JSON 快照：

        {
          window_seconds,
          total, success, fail, success_rate,
          p50_seconds, p90_seconds,
          live: { total, running, stopped, creating },
          by_template: {
            <tid>: { total, success, fail, success_rate, p50, p90 }
          },
          timeline: [          # 60 个 bucket，从旧到新
            { minute_ago, count, success, fail,
              source_pool, source_direct, p50, p90 }
          ]
        }
        """
        now = time.time()
        with self._lock:
            self._evict()
            creates = list(self._creates)
            live = dict(self._live)

        total = len(creates)
        succeeded = [e for e in creates if e.success]
        durations = sorted(e.duration for e in succeeded)

        # ── 按 template 分组 ─────────────────────────────────
        tmpl_map: dict[str, list[_CreateEvent]] = {}
        for e in creates:
            tmpl_map.setdefault(e.template_id, []).append(e)

        by_template: dict[str, dict] = {}
        for tid, evs in tmpl_map.items():
            t_ok = [e for e in evs if e.success]
            t_dur = sorted(e.duration for e in t_ok)
            by_template[tid] = {
                "total": len(evs),
                "success": len(t_ok),
                "fail": len(evs) - len(t_ok),
                "success_rate": round(len(t_ok) / len(evs), 4) if evs else None,
                "p50": _percentile(t_dur, 50),
                "p90": _percentile(t_dur, 90),
            }

        # ── 按分钟 timeline ───────────────────────────────────
        buckets: dict[int, dict] = {}
        for e in creates:
            m = int((now - e.ts) // 60)
            if m >= 60:
                continue
            b = buckets.setdefault(m, {
                "count": 0, "success": 0, "fail": 0,
                "source_pool": 0, "source_direct": 0, "durations": [],
            })
            b["count"] += 1
            if e.source == "pool":
                b["source_pool"] += 1
            else:
                b["source_direct"] += 1
            if e.success:
                b["success"] += 1
                b["durations"].append(e.duration)
            else:
                b["fail"] += 1

        timeline = []
        for m in range(59, -1, -1):
            b = buckets.get(m, {})
            d = sorted(b.get("durations", []))
            timeline.append({
                "minute_ago": m,
                "count": b.get("count", 0),
                "success": b.get("success", 0),
                "fail": b.get("fail", 0),
                "source_pool": b.get("source_pool", 0),
                "source_direct": b.get("source_direct", 0),
                "p50": _percentile(d, 50),
                "p90": _percentile(d, 90),
            })

        return {
            "window_seconds": _WINDOW_SECONDS,
            "total": total,
            "success": len(succeeded),
            "fail": total - len(succeeded),
            "success_rate": round(len(succeeded) / total, 4) if total > 0 else None,
            "p50_seconds": _percentile(durations, 50),
            "p90_seconds": _percentile(durations, 90),
            "live": live,
            "by_template": by_template,
            "timeline": timeline,
        }

    # ── 内部工具 ─────────────────────────────────────────────────

    def _evict(self) -> None:
        cutoff = time.time() - _WINDOW_SECONDS
        while self._creates and self._creates[0].ts < cutoff:
            self._creates.popleft()


# ── 进程级单例 ────────────────────────────────────────────────────

sandbox_metrics = SandboxMetrics()


# ── 工具函数 ──────────────────────────────────────────────────────

def _percentile(sorted_data: list[float], p: int) -> float | None:
    if not sorted_data:
        return None
    idx = max(0, int(len(sorted_data) * p / 100) - 1)
    return round(sorted_data[idx], 2)
