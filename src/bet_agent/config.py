from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_key_values(path: Path) -> None:
    """Load KEY=VALUE pairs without ever logging their values."""
    if not path.exists():
        return
    raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    plain_values: list[str] = []
    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            if line and not line.startswith("#"):
                plain_values.append(line)
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    # Backward-compatible minimal format: line 1 is Olimp login, line 2 is password.
    if len(plain_values) == 2:
        os.environ.setdefault("OLIMP_LOGIN", plain_values[0])
        os.environ.setdefault("OLIMP_PASSWORD", plain_values[1])


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_channel_url: str
    telegram_post_prefix: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    olimp_url: str
    olimp_login: str | None
    olimp_password: str | None
    ollama_url: str
    ollama_model: str
    timezone: str
    active_from: str
    active_to: str
    poll_seconds: int
    headless: bool
    browser_channel: str | None
    data_dir: Path
    state_dir: Path

    @classmethod
    def load(cls) -> "Settings":
        _load_key_values(ROOT / ".env.local")
        _load_key_values(ROOT / "password.txt")
        return cls(
            telegram_channel_url=os.getenv(
                "TELEGRAM_CHANNEL_URL", "https://web.telegram.org/k/#-1144091308"
            ),
            telegram_post_prefix=os.getenv(
                "TELEGRAM_POST_PREFIX", "БЕСПЛАТНЫЙ ПРОГНОЗ НА МАТЧ"
            ),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            olimp_url=os.getenv("OLIMP_URL", "https://olimpbet.kz/"),
            olimp_login=os.getenv("OLIMP_LOGIN") or None,
            olimp_password=os.getenv("OLIMP_PASSWORD") or None,
            ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen3-vl:4b"),
            timezone=os.getenv("TIMEZONE", "Asia/Almaty"),
            active_from=os.getenv("ACTIVE_FROM", "12:00"),
            active_to=os.getenv("ACTIVE_TO", "22:00"),
            poll_seconds=int(os.getenv("POLL_SECONDS", "60")),
            headless=os.getenv("HEADLESS", "false").lower() in {"1", "true", "yes"},
            browser_channel=os.getenv("BROWSER_CHANNEL", "msedge") or None,
            data_dir=ROOT / "data",
            state_dir=ROOT / ".state",
        )
