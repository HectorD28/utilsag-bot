from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Configuración del Bot de Telegram UtilSAG-AI."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WHITELIST_IDS: str = ""
    TELEGRAM_SILENT_REJECT: bool = False

    BACKEND_API_URL: str = "http://127.0.0.1:8000/api/v1"
    BACKEND_TIMEOUT_SECONDS: float = 15.0
    BOT_SOURCE_IP: str = "telegram-polling"

    # HITL (HU-16)
    HITL_TTL_SECONDS: int = 240
    DEFAULT_TECNICO_ID: int = 1

    @property
    def whitelist_id_set(self) -> frozenset[int]:
        ids: set[int] = set()
        for raw in self.TELEGRAM_WHITELIST_IDS.split(","):
            token = raw.strip()
            if token:
                ids.add(int(token))
        return frozenset(ids)


@lru_cache
def get_bot_settings() -> BotSettings:
    return BotSettings()

