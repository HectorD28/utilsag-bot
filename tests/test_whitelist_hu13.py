from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationHandlerStop

from bot.config import BotSettings
from bot.main import build_application
from bot.middleware import whitelist_middleware


def _make_update(*, user_id: int, username: str | None = "intruso", text: str = "hola"):
    reply_mock = AsyncMock()
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, username=username),
        effective_chat=SimpleNamespace(id=9001),
        effective_message=SimpleNamespace(reply_text=reply_mock),
        message=SimpleNamespace(text=text),
        callback_query=None,
    )


def test_whitelist_id_set_parsing():
    cfg = BotSettings(TELEGRAM_WHITELIST_IDS="101, 202 , 303")
    assert cfg.whitelist_id_set == frozenset({101, 202, 303})


async def test_middleware_permite_usuario_autorizado():
    cfg = BotSettings(TELEGRAM_WHITELIST_IDS="111,222")
    backend = SimpleNamespace(reportar_acceso_denegado=AsyncMock())
    update = _make_update(user_id=111, username="tecnico_ok")

    await whitelist_middleware(
        update, None, settings=cfg, backend_client=backend  # type: ignore[arg-type]
    )

    backend.reportar_acceso_denegado.assert_not_awaited()
    update.effective_message.reply_text.assert_not_awaited()


async def test_middleware_bloquea_y_audita_usuario_no_autorizado():
    cfg = BotSettings(TELEGRAM_WHITELIST_IDS="111,222", TELEGRAM_SILENT_REJECT=False)
    backend = SimpleNamespace(reportar_acceso_denegado=AsyncMock())
    update = _make_update(user_id=999, username="atacante", text="/stock RAM")

    with pytest.raises(ApplicationHandlerStop):
        await whitelist_middleware(
            update, None, settings=cfg, backend_client=backend  # type: ignore[arg-type]
        )

    backend.reportar_acceso_denegado.assert_awaited_once_with(
        telegram_user_id=999,
        username="atacante",
        chat_id=9001,
        detalle="/stock RAM",
    )
    update.effective_message.reply_text.assert_awaited_once()


async def test_middleware_rechazo_silencioso():
    cfg = BotSettings(TELEGRAM_WHITELIST_IDS="111", TELEGRAM_SILENT_REJECT=True)
    backend = SimpleNamespace(reportar_acceso_denegado=AsyncMock())
    update = _make_update(user_id=888, username=None, text="ping")

    with pytest.raises(ApplicationHandlerStop):
        await whitelist_middleware(
            update, None, settings=cfg, backend_client=backend  # type: ignore[arg-type]
        )

    backend.reportar_acceso_denegado.assert_awaited_once()
    update.effective_message.reply_text.assert_not_awaited()


def test_build_application_registra_middleware_en_grupo_menos_uno():
    with pytest.raises(ValueError):
        build_application(BotSettings(TELEGRAM_BOT_TOKEN=""))

    app = build_application(
        BotSettings(
            TELEGRAM_BOT_TOKEN="123456:TEST_TOKEN",
            TELEGRAM_WHITELIST_IDS="111",
        )
    )
    assert -1 in app.handlers
    assert 0 in app.handlers

