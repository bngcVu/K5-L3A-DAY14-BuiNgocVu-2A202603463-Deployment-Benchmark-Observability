"""
Cost guard — cộng dồn chi phí LLM theo ngày (UTC) trong Redis.

Giới hạn đã biết: chi phí chỉ được cộng SAU khi gọi LLM, nên các request chạy song
song lúc gần hết ngân sách có thể làm tổng vượt nhẹ.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

KEY_TTL_SECONDS = 2 * 24 * 3600


def _today_key() -> str:
    return "cost:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    spent = float(r.get(_today_key()) or 0)
    if spent >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens * PRICE_INPUT_PER_1K + output_tokens * PRICE_OUTPUT_PER_1K) / 1000
    key = _today_key()
    pipe = r.pipeline()
    pipe.incrbyfloat(key, cost)
    pipe.expire(key, KEY_TTL_SECONDS)
    pipe.execute()
    return cost
