from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from bot.backend_client import BackendClient, BackendClientError
from bot.config import BotSettings, get_bot_settings
from bot.formatters import (
    format_agent_response,
    format_equipo_historial,
    format_hitl_summary,
    format_mutation_result,
)
from bot.hitl_store import HITLStore, hitl_store
from bot.vision import decode_qr_local


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Saludo inicial para técnicos autorizados por la Whitelist."""
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "Bienvenido a UtilSAG-AI. Tu usuario está autorizado para consultas e inventario.\n"
        "Escríbeme en lenguaje natural o usa /help para ver ejemplos."
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ayuda rápida de comandos y consultas en campo."""
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "Comandos disponibles:\n"
        "/start - Verificar acceso\n"
        "/help - Mostrar esta ayuda\n\n"
        "Ejemplos de consulta en lenguaje natural:\n"
        "• ¿Cuántos Mouse hay en Laboratorio 1?\n"
        "• Muéstrame los componentes del equipo 740868655163\n"
        "• Traslada la pieza 699 del laboratorio ID 1 al laboratorio ID 2 por reposición"
    )


async def text_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    backend_client: BackendClient | None = None,
    settings: BotSettings | None = None,
    store: HITLStore | None = None,
) -> None:
    """Reenvía consultas al orquestador LLM y despliega Inline Keyboards si requiere confirmación HITL."""
    message = update.effective_message
    user = update.effective_user
    if message is None or not message.text or user is None:
        return

    if update.effective_chat is not None and context is not None:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )

    cfg = settings or get_bot_settings()
    actor = f"tg:{user.id}" + (f" (@{user.username})" if user.username else "")
    client = backend_client or BackendClient(cfg)
    active_store = store or hitl_store

    try:
        data = await client.consultar_agente(
            mensaje=message.text,
            actor_externo=actor,
            tecnico_id=cfg.DEFAULT_TECNICO_ID,
        )
    except BackendClientError as exc:
        await message.reply_text(exc.user_message)
        return

    tool_calls = data.get("tool_calls") or []
    pending_tc = next((tc for tc in tool_calls if tc.get("requiere_confirmacion")), None)

    if pending_tc is not None:
        tool_name = str(pending_tc["tool_name"])
        arguments = dict(pending_tc.get("arguments") or {})
        pending = active_store.create_pending(
            user_id=user.id,
            tool_name=tool_name,
            arguments=arguments,
            ttl_seconds=cfg.HITL_TTL_SECONDS,
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Confirmar Operación",
                        callback_data=f"hitl:confirm:{pending.token}",
                    ),
                    InlineKeyboardButton(
                        "❌ Cancelar",
                        callback_data=f"hitl:cancel:{pending.token}",
                    ),
                ]
            ]
        )
        summary = format_hitl_summary(tool_name, arguments, cfg.HITL_TTL_SECONDS)
        await message.reply_text(summary, reply_markup=keyboard)
        return

    await message.reply_text(format_agent_response(data))


async def hitl_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    backend_client: BackendClient | None = None,
    settings: BotSettings | None = None,
    store: HITLStore | None = None,
) -> None:
    """Procesa los botones Confirmar / Cancelar de HU-16 con validación de TTL."""
    query = update.callback_query
    user = update.effective_user
    if query is None or query.data is None or user is None:
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "hitl":
        return

    action_type, token = parts[1], parts[2]
    cfg = settings or get_bot_settings()
    active_store = store or hitl_store

    pending, status = active_store.pop_pending(token=token, user_id=user.id)
    if status == "NOT_FOUND":
        await query.edit_message_text("Esta solicitud ya fue procesada o no existe.")
        return
    if status == "FORBIDDEN":
        await query.answer(
            "Solo el técnico que inició la operación puede confirmarla.",
            show_alert=True,
        )
        return
    if status == "EXPIRED" or pending is None:
        await query.edit_message_text(
            f"⏱️ Operación expirada (superó el TTL de {cfg.HITL_TTL_SECONDS}s). "
            "Envía la solicitud nuevamente."
        )
        return

    if action_type == "cancel":
        await query.edit_message_text(
            "❌ Operación cancelada por el usuario. No se modificó el inventario."
        )
        return

    client = backend_client or BackendClient(cfg)
    try:
        result = await client.ejecutar_mutacion(
            tool_name=pending.tool_name,
            arguments=pending.arguments,
        )
        await query.edit_message_text(
            format_mutation_result(pending.tool_name, result)
        )
    except BackendClientError as exc:
        await query.edit_message_text(f"⚠️ No se pudo completar la operación: {exc.user_message}")


async def photo_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    backend_client: BackendClient | None = None,
    settings: BotSettings | None = None,
) -> None:
    """Procesa fotos de etiquetas QR (local) o placas SBN (OCR LLM >= 90%) (HU-15)."""
    message = update.effective_message
    if message is None or not message.photo:
        return

    if update.effective_chat is not None and context is not None:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )

    photo = message.photo[-1]
    tg_file = await photo.get_file()
    image_bytes = bytes(await tg_file.download_as_bytearray())

    qr_res = decode_qr_local(image_bytes)
    if qr_res is not None:
        codigo = qr_res.codigo
        metodo = qr_res.metodo
        confianza = 1.0
        serie = None
    else:
        cfg = settings or get_bot_settings()
        client = backend_client or BackendClient(cfg)
        try:
            ocr = await client.analizar_placa_ocr(
                image_bytes=image_bytes, mime_type="image/jpeg"
            )
        except BackendClientError as exc:
            await message.reply_text(f"⚠️ {exc.user_message}")
            return

        confianza = float(ocr.get("confianza") or 0.0)
        codigo = ocr.get("codigo_sbn")
        serie = ocr.get("numero_serie")
        metodo = "OCR_LLM"

        if ocr.get("requiere_reintento") or not codigo or confianza < 0.90:
            obs = ocr.get("observacion") or "Imagen poco nítida o etiqueta deteriorada."
            await message.reply_text(
                f"📷 Lectura con baja confianza ({confianza:.0%}, mínimo requerido 90%).\n"
                f"Detalle: {obs}\n"
                "Por favor, toma otra foto más nítida o escribe el código SBN manualmente."
            )
            return

    lines = [
        f"🔎 Activo identificado ({metodo} — confianza {confianza:.0%})",
        f"• Código SBN: {codigo}",
    ]
    if serie:
        lines.append(f"• N.° Serie: {serie}")

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📋 Ver Ficha e Historial",
                    callback_data=f"vision:hist:{codigo}",
                ),
                InlineKeyboardButton(
                    "🔄 Cómo Trasladar",
                    callback_data=f"vision:move:{codigo}",
                ),
            ]
        ]
    )
    await message.reply_text("\n".join(lines), reply_markup=keyboard)


async def vision_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    backend_client: BackendClient | None = None,
    settings: BotSettings | None = None,
) -> None:
    """Ejecuta acciones rápidas tras identificar un activo por QR/OCR (HU-15)."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    await query.answer()
    parts = query.data.split(":", 2)
    if len(parts) != 3 or parts[0] != "vision":
        return

    action, codigo = parts[1], parts[2]
    if action == "move":
        await query.edit_message_text(
            f"Para trasladar un componente del equipo {codigo}, consulta primero su ficha "
            "para ver el ID de pieza y luego escribe, por ejemplo:\n"
            '"Traslada la pieza <ID> del laboratorio ID <origen> al laboratorio ID <destino> por <motivo>"'
        )
        return

    if action == "hist":
        cfg = settings or get_bot_settings()
        client = backend_client or BackendClient(cfg)
        try:
            data = await client.consultar_historial_equipo(codigo_patrimonial=codigo)
            await query.edit_message_text(format_equipo_historial(data))
        except BackendClientError as exc:
            await query.edit_message_text(f"⚠️ {exc.user_message}")
