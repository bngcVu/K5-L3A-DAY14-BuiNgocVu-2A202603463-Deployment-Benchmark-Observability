"""
Production AI Agent — Part 6 Final Project

Chuỗi bảo vệ của /ask: API key (401) → rate limit (429) → cost guard (402) → LLM.
Kiểm tra: python check_production_ready.py
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Mỗi dòng log là 1 JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
logger = logging.getLogger("agent")
logger.handlers = [_handler]
logger.setLevel(settings.log_level)
logger.propagate = False


def log(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


# Graceful shutdown: uvicorn tự bắt SIGTERM, ngừng nhận kết nối mới, chờ request
# đang chạy xong rồi mới chạy phần sau `yield`. Không tự đăng ký signal handler
# để khỏi ghi đè handler của uvicorn.
@asynccontextmanager
async def lifespan(_: FastAPI):
    log("startup", environment=settings.environment)
    if not settings.agent_api_key:
        log("config_warning", logging.WARNING,
            detail="AGENT_API_KEY is empty, every /ask request will get 401")
    yield
    r.close()
    log("shutdown_complete")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Stack trace chỉ ghi vào log, client chỉ nhận thông báo chung.
        logger.error("unhandled_error", exc_info=True,
                     extra={"fields": {"path": request.url.path}})
        response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
    log("request", method=request.method, path=request.url.path, status=response.status_code,
        ms=round((time.perf_counter() - started) * 1000, 1))
    return response


@app.exception_handler(redis.RedisError)
def redis_unavailable(_: Request, exc: redis.RedisError):
    # Không kiểm tra được rate limit / ngân sách thì từ chối (fail closed).
    log("redis_error", logging.ERROR, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})


class AskRequest(BaseModel):
    # strip: câu hỏi chỉ toàn khoảng trắng bị coi là rỗng → 422
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness: không phụ thuộc Redis, nếu không Redis chết sẽ kéo theo restart agent."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness: Redis không kết nối được → 503 để ngừng nhận traffic."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return {"status": "ready"}


def _estimate_tokens(text: str) -> int:
    # Mock LLM không trả usage; ước lượng ~4 ký tự / token.
    return max(1, len(text) // 4)


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    cost = record_cost(_estimate_tokens(body.question), _estimate_tokens(answer))
    return {"question": body.question, "answer": answer, "cost_usd": round(cost, 8)}
