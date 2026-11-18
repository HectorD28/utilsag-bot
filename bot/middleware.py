import logging

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.backend_client import BackendClient
from bot.config import BotSettings, get_bot_settings

logger = logging.getLogger(__name__)


def _extract_event_preview(update: Update) -> str | None:
    if update.message and update.message.text:
        return update.message.text[:200]
    if update.callback_query and update.callback_query.data:
        return f"callback:{update.callback_query.data[:180]}"
    return None


async def whitelist_middleware(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    settings: BotSettings | None = None,
    backend_client: BackendClient | None = None,
) -> None:
    """Intercepta todo evento entrante y bloquea usuarios fuera de TELEGRAM_WHITELIST_IDS."""
    cfg = settings or get_bot_settings()
    user = update.effective_user
    if user is None:
        raise ApplicationHandlerStop

    if user.id in cfg.whitelist_id_set:
        return

    chat_id = update.effective_chat.id if update.effective_chat else None
    username = user.username
    preview = _extract_event_preview(update)

    logger.warning(
        "Acceso denegado por Whitelist | user_id=%s username=%s chat_id=%s ip=%s",
        user.id,
        username,
        chat_id,
        cfg.BOT_SOURCE_IP,
    )

    client = backend_client or BackendClient(cfg)
    await client.reportar_acceso_denegado(
        telegram_user_id=user.id,
        username=username,
        chat_id=chat_id,
        detalle=preview,
    )

    if not cfg.TELEGRAM_SILENT_REJECT and update.effective_message is not None:
        await update.effective_message.reply_text(
            "Acceso denegado. Tu usuario de Telegram no está autorizado en UtilSAG-AI."
        )

    raise ApplicationHandlerStop

