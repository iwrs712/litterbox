from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json

from redis import Redis

from orchestrator.utils import json_dumps


@dataclass(frozen=True)
class TTLEntry:
    sandbox_id: str
    ttl_token: str


class TTLQueueRepository:
    _POP_DUE_SCRIPT = """
local items = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
if #items == 0 then
  return {}
end
if tonumber(items[2]) > tonumber(ARGV[1]) then
  return {}
end
redis.call('ZREM', KEYS[1], items[1])
return items
"""

    def __init__(self, redis_url: str, queue_key: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.queue_key = queue_key
        self._pop_due = self.redis.register_script(self._POP_DUE_SCRIPT)

    @staticmethod
    def _member(entry: TTLEntry) -> str:
        return json_dumps({"sandbox_id": entry.sandbox_id, "ttl_token": entry.ttl_token})

    def schedule(self, entry: TTLEntry, expires_at: datetime) -> None:
        self.redis.zadd(self.queue_key, {self._member(entry): expires_at.timestamp()})

    def unschedule(self, entry: TTLEntry) -> None:
        self.redis.zrem(self.queue_key, self._member(entry))

    def pop_due(self, now: datetime) -> TTLEntry | None:
        result = self._pop_due(keys=[self.queue_key], args=[now.timestamp()])
        if not result:
            return None
        payload = json.loads(result[0])
        return TTLEntry(sandbox_id=payload["sandbox_id"], ttl_token=payload["ttl_token"])
