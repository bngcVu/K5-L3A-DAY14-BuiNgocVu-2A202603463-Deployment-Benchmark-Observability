"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

Không có secret mặc định: AGENT_API_KEY rỗng thì mọi request /ask đều bị 401.
"""
import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    # Biến đặt rỗng (vd "PORT=") được coi như chưa đặt.
    return os.getenv(name) or default


@dataclass
class Settings:
    port: int = field(default_factory=lambda: int(_env("PORT", "8000")))
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO").upper())
    agent_api_key: str = field(default_factory=lambda: _env("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0"))
    rate_limit_per_minute: int = field(
        default_factory=lambda: int(_env("RATE_LIMIT_PER_MINUTE", "10")))
    daily_budget_usd: float = field(
        default_factory=lambda: float(_env("DAILY_BUDGET_USD", "1.0")))


settings = Settings()
