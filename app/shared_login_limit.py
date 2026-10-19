"""Atomic shared login throttling using Redis. Fail closed when unavailable.

Keys use HMAC to avoid storing raw account names or client IP addresses.
The Redis INCR/EXPIRE operation is atomic via Lua across workers.
"""
import hashlib
import hmac
import os
from fastapi import HTTPException

_SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {n, redis.call('TTL', KEYS[1])}
"""

def check(kind, username, ip):
    if os.getenv("SCHOOL_ENV") != "production":
        return False
    url = os.getenv("SCHOOL_RATE_LIMIT_REDIS_URL")
    secret = os.getenv("SCHOOL_RATE_LIMIT_KEY_SECRET", "")
    if not url or len(secret) < 32 or not url.startswith(("rediss://", "redis://")):
        raise HTTPException(503, "Authentication temporarily unavailable")
    try:
        import redis
        client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        blocked = 0
        for scope, identity, limit in (("account", username.strip().casefold(), 5),
                                       ("ip", ip, 30)):
            digest = hmac.new(secret.encode(), f"{kind}:{scope}:{identity}".encode(), hashlib.sha256).hexdigest()
            count, ttl = client.eval(_SCRIPT, 1, "school:login:"+digest, 300)
            if int(count) > limit:
                # Keep evaluating both dimensions to prevent a blocked account from
                # bypassing source-IP accounting. The Lua script remains atomic.
                blocked = max(blocked, int(ttl))
        if blocked:
            raise HTTPException(429, "Too many login attempts; try again later",
                                headers={"Retry-After": str(max(1, blocked))})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Authentication temporarily unavailable")
    return True
