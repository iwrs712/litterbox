import { useEffect, useRef, useState, useCallback } from 'react';
import { useSandboxStore } from '@/store/sandboxStore';
import { useApp } from '@/contexts/AppContext';
import { apiClient } from '@/lib/api';
import type { MetricsSnapshot } from '@/types/sandbox';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorAlert } from '@/components/ErrorAlert';
import { Activity, Server, Loader2, TrendingUp, Clock, CheckCircle2 } from 'lucide-react';

// ── 工具函数 ─────────────────────────────────────────────────────

function fmtMs(s: number | null) {
  if (s === null) return '—';
  return `${Math.round(s * 1000)}ms`;
}
function fmtRate(r: number | null) {
  if (r === null) return '—';
  return `${(r * 100).toFixed(1)}%`;
}
function rateColor(r: number | null) {
  if (r === null) return '';
  if (r >= 0.95) return 'text-green-500';
  if (r >= 0.80) return 'text-yellow-500';
  return 'text-red-500';
}

// ── KPI Card ─────────────────────────────────────────────────────

function KpiCard({
  title, value, sub, icon, valueClass,
}: {
  title: string; value: string; sub?: string;
  icon: React.ReactNode; valueClass?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${valueClass ?? ''}`}>{value}</div>
        {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

// ── 主页面 ────────────────────────────────────────────────────────

const REFRESH_MS = 10_000;

export function Dashboard() {
  const { t } = useApp();
  const { pools, fetchPools, error, clearError } = useSandboxStore();

  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = useCallback(async () => {
    fetchPools();
    try {
      const data = await apiClient.getMetricsSnapshot();
      setMetrics(data);
      setLastUpdated(new Date());
      setMetricsError(null);
    } catch (e) {
      setMetricsError(e instanceof Error ? e.message : 'Failed to fetch metrics');
    } finally {
      setLoading(false);
    }
  }, [fetchPools]);

  useEffect(() => {
    fetchAll();
    timerRef.current = setInterval(fetchAll, REFRESH_MS);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [fetchAll]);

  const live = metrics?.live ?? null;

  if (loading && !metrics) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-muted-foreground mx-auto mb-4 animate-spin" />
          <p className="text-muted-foreground">{t.dashboard.loading}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t.dashboard.title}</h1>
          <p className="text-muted-foreground mt-1">{t.dashboard.subtitle}</p>
        </div>
        <span className="text-sm text-muted-foreground">
          {lastUpdated ? `${t.dashboard.lastUpdated}: ${lastUpdated.toLocaleTimeString()}` : ''}
        </span>
      </div>

      {(error || metricsError) && (
        <ErrorAlert error={error ?? metricsError ?? ''} onDismiss={clearError} />
      )}

      {/* ── 实时状态 KPI ────────────────────────────────────────── */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total Sandboxes"
          value={String(live?.total ?? '—')}
          sub="All sandboxes"
          icon={<Server className="h-4 w-4 text-muted-foreground" />}
        />
        <KpiCard
          title="Running"
          value={String(live?.running ?? '—')}
          sub="Active sandboxes"
          icon={<Activity className="h-4 w-4 text-green-500" />}
          valueClass="text-green-500"
        />
        <KpiCard
          title="Creating"
          value={String(live?.creating ?? '—')}
          sub="Provisioning"
          icon={<Loader2 className="h-4 w-4 text-blue-500" />}
          valueClass="text-blue-500"
        />
        <KpiCard
          title="Stopped"
          value={String(live?.stopped ?? '—')}
          sub="Inactive sandboxes"
          icon={<Server className="h-4 w-4 text-muted-foreground" />}
          valueClass="text-muted-foreground"
        />
      </div>

      {/* ── Pool 状态（精简） ────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            {t.dashboard.poolStatistics}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!pools || pools.length === 0 ? (
            <div className="py-6 text-center text-sm text-muted-foreground">
              {t.dashboard.noPools}
            </div>
          ) : (
            <div className="space-y-3">
              {pools.map((pool) => {
                const pct = pool.target_ready > 0
                  ? Math.min((pool.ready / pool.target_ready) * 100, 100)
                  : 0;
                const statusLabel = pool.ready === 0 && pool.min_ready > 0
                  ? <span className="text-red-500">{t.dashboard.poolExhausted}</span>
                  : pool.ready < pool.min_ready
                  ? <span className="text-yellow-500">{t.dashboard.warming}</span>
                  : <span className="text-green-500">{t.dashboard.healthy}</span>;

                return (
                  <div key={pool.template_id} className="border rounded-lg p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-medium">{pool.template_id}</span>
                        {pool.enabled
                          ? <span className="text-xs text-green-500 flex items-center gap-1">
                              <Activity className="h-3 w-3 animate-pulse" />Enabled
                            </span>
                          : <span className="text-xs text-muted-foreground">Disabled</span>
                        }
                      </div>
                      <div className="flex items-center gap-4 text-sm">
                        <span className="text-muted-foreground">
                          Ready <span className="font-bold text-foreground">{pool.ready}</span>
                          <span className="text-muted-foreground">/{pool.target_ready}</span>
                        </span>
                        <span className="text-muted-foreground">
                          Allocated <span className="font-bold text-blue-500">{pool.allocated}</span>
                        </span>
                        <span className="text-muted-foreground">
                          Creating <span className="font-bold text-yellow-500">{pool.creating}</span>
                        </span>
                      </div>
                    </div>
                    {pool.target_ready > 0 && (
                      <div className="space-y-1">
                        <div className="w-full bg-secondary rounded-full h-1.5">
                          <div
                            className="bg-green-500 h-1.5 rounded-full transition-all"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <div className="flex justify-between text-xs text-muted-foreground">
                          {statusLabel}
                          <span>{pct.toFixed(0)}% ready</span>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── 创建指标 KPI ────────────────────────────────────────── */}
      {metrics && (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <KpiCard
              title="Created (1h)"
              value={String(metrics.total)}
              sub={`${metrics.success} succeeded · ${metrics.fail} failed`}
              icon={<TrendingUp className="h-4 w-4 text-muted-foreground" />}
            />
            <KpiCard
              title="Success Rate"
              value={fmtRate(metrics.success_rate)}
              sub={
                metrics.success_rate === null ? 'No data yet'
                  : metrics.success_rate >= 0.95 ? 'Healthy'
                  : metrics.success_rate >= 0.80 ? 'Degraded'
                  : 'Unhealthy'
              }
              icon={<CheckCircle2 className="h-4 w-4 text-muted-foreground" />}
              valueClass={rateColor(metrics.success_rate)}
            />
            <KpiCard
              title="P50 Latency"
              value={fmtMs(metrics.p50_seconds)}
              sub="Median creation time"
              icon={<Clock className="h-4 w-4 text-blue-500" />}
              valueClass="text-blue-500"
            />
            <KpiCard
              title="P90 Latency"
              value={fmtMs(metrics.p90_seconds)}
              sub="90th percentile"
              icon={<Activity className="h-4 w-4 text-orange-500" />}
              valueClass="text-orange-500"
            />
          </div>

          {/* 按 Template 明细 */}
          {Object.keys(metrics.by_template).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>By Template — last hour</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="text-left py-2 pr-4 font-medium">Template</th>
                        <th className="text-right py-2 px-3 font-medium">Total</th>
                        <th className="text-right py-2 px-3 font-medium">Success</th>
                        <th className="text-right py-2 px-3 font-medium">Fail</th>
                        <th className="text-right py-2 px-3 font-medium">Rate</th>
                        <th className="text-right py-2 px-3 font-medium">P50</th>
                        <th className="text-right py-2 pl-3 font-medium">P90</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(metrics.by_template).map(([tid, s]) => (
                        <tr key={tid} className="border-b last:border-0 hover:bg-muted/50">
                          <td className="py-2 pr-4 font-mono text-xs">{tid}</td>
                          <td className="text-right py-2 px-3">{s.total}</td>
                          <td className="text-right py-2 px-3 text-green-500">{s.success}</td>
                          <td className="text-right py-2 px-3 text-red-400">{s.fail}</td>
                          <td className={`text-right py-2 px-3 font-medium ${rateColor(s.success_rate)}`}>
                            {fmtRate(s.success_rate)}
                          </td>
                          <td className="text-right py-2 px-3 text-blue-500">{fmtMs(s.p50)}</td>
                          <td className="text-right py-2 pl-3 text-orange-400">{fmtMs(s.p90)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
