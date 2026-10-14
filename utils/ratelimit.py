"""Tiny in-memory rate limiter used to slow down password guessing.

It keeps timestamps of recent failures per key (IP + email). It is per
process, which is fine for a single small server; a shared store such as
Redis would be used for a large multi-server deployment.
"""
import time
from collections import defaultdict

_failures = defaultdict(list)


def _recent(key, window):
    now = time.time()
    _failures[key] = [t for t in _failures[key] if now - t < window]
    return _failures[key]


def is_blocked(key, max_attempts, window):
    return len(_recent(key, window)) >= max_attempts


def record_failure(key, window):
    _recent(key, window).append(time.time())


def reset(key):
    _failures.pop(key, None)


def clear_all():
    _failures.clear()
