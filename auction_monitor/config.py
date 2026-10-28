from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    file_path = Path(path)
    if not file_path.exists():
        return
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    api_token: str
    database_path: str
    scrape_interval_seconds: int
    scraper_fixture_path: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_from: str | None
    smtp_to: str | None
    smtp_use_tls: bool
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.7-flash"
    ai_daily_limit: int = 10
    fipe_api_token: str | None = None
    reef_api_key: str | None = None
    market_daily_limit: int = 20


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "8080")),
        api_token=os.getenv("APP_API_TOKEN", "change-me"),
        database_path=os.getenv("DATABASE_PATH", "data/auction_monitor.sqlite3"),
        scrape_interval_seconds=int(os.getenv("SCRAPE_INTERVAL_SECONDS", "900")),
        scraper_fixture_path=os.getenv("SCRAPER_FIXTURE_PATH", "samples/lots.json"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        smtp_host=os.getenv("SMTP_HOST") or None,
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME") or None,
        smtp_password=os.getenv("SMTP_PASSWORD") or None,
        smtp_from=os.getenv("SMTP_FROM") or None,
        smtp_to=os.getenv("SMTP_TO") or None,
        smtp_use_tls=bool_env("SMTP_USE_TLS", True),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
        ai_daily_limit=int(os.getenv("AI_DAILY_LIMIT", "10")),
        fipe_api_token=os.getenv("FIPE_API_TOKEN") or None,
        reef_api_key=os.getenv("REEF_API_KEY") or None,
        market_daily_limit=int(os.getenv("MARKET_DAILY_LIMIT", "20")),
    )
