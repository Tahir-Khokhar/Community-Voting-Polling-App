"""Lightweight, dependency-free vote-attempt rate limiting.

Limits how often a single IP can *attempt* to vote on a given poll. This is an
abuse brake, not a security boundary: the real one-vote-per-token guarantee
comes from the signed anonymous token plus the ``unique_ballot_per_token``
database constraint. The throttle only slows scripted spam / scraping of the
vote endpoint.

The counter lives in Django's cache framework (see ``CACHES`` in settings). In
production a shared backend (memcached/Redis) must be configured so the counter
is consistent across workers; with ``LocMemCache`` (the dev default) the
counter is per-process, which is fine for a single dev server.

Behind a reverse proxy, ``REMOTE_ADDR`` is the proxy's address, not the
client's. Configure your proxy to set ``X-Forwarded-For`` and trust it in
Django only if you run behind a trusted proxy (see SECURE_PROXY_SSL_HEADER for
the analogous pattern). For the dev server ``REMOTE_ADDR`` is the real client.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache


def _config():
    polls = settings.POLL_SETTINGS
    return (
        polls.get("VOTE_THROTTLE_WINDOW_SECONDS", 60),
        polls.get("VOTE_THROTTLE_MAX_ATTEMPTS", 10),
    )


def _key(ip: str, poll_id: int) -> str:
    return f"vote_throttle:{ip}:{poll_id}"


def client_ip(request) -> str:
    """Best-effort client IP. Uses REMOTE_ADDR (the transport-level peer)."""
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def vote_attempt_allowed(request, poll_id: int) -> bool:
    """Record a vote attempt and return True if still within the limit.

    Uses the cache's atomic add/incr so the counter is updated in one round
    trip. The check is deliberately approximate (a true lock-free throttle) —
    a tiny overrun under concurrency is acceptable for an abuse brake.
    """
    window, limit = _config()
    key = _key(client_ip(request), poll_id)
    # cache.add returns True only if the key was absent (sets value=1, ttl=window).
    if cache.add(key, 1, window):
        return True
    try:
        count = cache.incr(key)
    except ValueError:
        # Key evicted between add and incr — treat as first attempt.
        cache.add(key, 1, window)
        return True
    return count <= limit
