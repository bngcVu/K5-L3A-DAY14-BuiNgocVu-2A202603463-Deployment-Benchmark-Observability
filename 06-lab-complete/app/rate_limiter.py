"""
Rate limiting — sliding window 60 giây bằng Redis sorted set.

State nằm trong Redis nên mọi worker / instance dùng chung và vẫn còn sau khi restart.
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60

# Xoá -> đếm -> thêm phải là một thao tác nguyên tử. Nếu tách thành nhiều lệnh, hai
# worker có thể cùng đếm thấy còn chỗ rồi cùng nhận, làm vượt giới hạn.
# Trả về 0 nếu được nhận, ngược lại là số mili giây phải chờ.
_SLIDING_WINDOW = r.register_script("""
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
if redis.call('ZCARD', key) >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  if oldest[2] then
    return math.max(1, tonumber(oldest[2]) + window - now)
  end
  return window
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, window)
return 0
""")


def check_rate_limit(key: str) -> None:
    # Không lưu API key dạng thô trong Redis.
    bucket = "rate:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    wait_ms = _SLIDING_WINDOW(
        keys=[bucket],
        args=[int(time.time() * 1000), WINDOW_SECONDS * 1000,
              settings.rate_limit_per_minute, uuid.uuid4().hex],
    )
    if wait_ms:
        retry_after = (int(wait_ms) + 999) // 1000
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} requests/minute",
            headers={"Retry-After": str(retry_after)},
        )
