import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from bot.config import BotSettings, get_bot_settings
from bot.handlers import (
    help_handler,
    hitl_callback_handler,
    photo_message_handler,
    start_handler,
    text_message_handler,
    vision_callback_handler,
)
from bot.middleware import whitelist_middleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def build_application(settings: BotSettings | None = None) -> Application:
    """Construye la aplicación de Telegram con el middleware de Whitelist en group=-1."""
    cfg = settings or get_bot_settings()
    if not cfg.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN no configurado en .env")

    app = Application.builder().token(cfg.TELEGRAM_BOT_TOKEN).build()

    # HU-13 CA-1: group=-1 garantiza intercepción antes de cualquier handler (group=0)
    app.add_handler(TypeHandler(Update, whitelist_middleware), group=-1)

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(
        CallbackQueryHandler(
            hitl_callback_handler, pattern=r"^hitl:(confirm|cancel):[a-f0-9]+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            vision_callback_handler, pattern=r"^vision:(hist|move):.+$"
        )
    )
    app.add_handler(MessageHandler(filters.PHOTO, photo_message_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler)
    )
    return app


def main() -> None:
    app = build_application()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

