"""Bounded LRU+TTL cache shared across upstream clients."""
import time
from collections import OrderedDict
from typing import Any

_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
MAX_ENTRIES = 5000


def get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, data = entry
    if expires_at < time.time():
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return data


def put(key: str, data: Any, ttl: float) -> None:
    _cache[key] = (time.time() + ttl, data)
    _cache.move_to_end(key)
    while len(_cache) > MAX_ENTRIES:
        _cache.popitem(last=False)


def stats() -> dict:
    now = time.time()
    fresh = sum(1 for (exp, _) in _cache.values() if exp >= now)
    return {"entries": len(_cache), "fresh": fresh, "max": MAX_ENTRIES}


def reset() -> None:
    _cache.clear()
