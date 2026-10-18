"""Rate limiting for logins, resets, chat, check-in guesses and AI calls.

By default the counters live in this process's memory, which is fine for one server. Set REDIS_URL
and they are kept in Redis instead, so every web worker and every server shares the same limits.
If Redis is unreachable the limiter falls back to memory rather than blocking everyone out.
"""
import logging
import time
import uuid
from collections import defaultdict

log = logging.getLogger("bloodlink.ratelimit")
_failures = defaultdict(list)
_redis = None                      # set by init_redis(); None means "use memory"


def init_redis(url=None, client=None):
    """Use Redis for the counters. ``client`` lets tests pass a fake."""
    global _redis
    if client is not None:
        _redis = client
    elif url:
        import redis
        _redis = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
    else:
        _redis = None


def using_redis():
    return _redis is not None


def _k(key):
    return f"bloodlink:rl:{key}"


def _recent(key, window):
    now = time.time()
    _failures[key] = [t for t in _failures[key] if now - t < window]
    return _failures[key]


def is_blocked(key, max_attempts, window):
    if _redis is not None:
        try:
            _redis.zremrangebyscore(_k(key), 0, time.time() - window)
            return _redis.zcard(_k(key)) >= max_attempts
        except Exception as exc:
            log.warning("redis unavailable, using memory: %s", type(exc).__name__)
    return len(_recent(key, window)) >= max_attempts


def record_failure(key, window):
    if _redis is not None:
        try:
            now = time.time()
            pipe = _redis.pipeline()
            pipe.zadd(_k(key), {f"{now}:{uuid.uuid4().hex[:8]}": now})
            pipe.expire(_k(key), int(window) + 1)
            pipe.execute()
            return
        except Exception as exc:
            log.warning("redis unavailable, using memory: %s", type(exc).__name__)
    _recent(key, window).append(time.time())


def reset(key):
    if _redis is not None:
        try:
            _redis.delete(_k(key))
        except Exception:
            pass
    _failures.pop(key, None)


def clear_all():
    if _redis is not None:
        try:
            for k in _redis.scan_iter(_k("*")):
                _redis.delete(k)
        except Exception:
            pass
    _failures.clear()
