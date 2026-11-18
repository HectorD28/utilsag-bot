from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.backend_client import BackendClientError
from bot.config import BotSettings
from bot.handlers import hitl_callback_handler, text_message_handler
from bot.hitl_store import HITLStore


def _make_text_update(text: str, user_id: int = 111):
    reply_mock = AsyncMock()
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, username="tecnico1"),
        effective_chat=SimpleNamespace(id=9001),
        effective_message=SimpleNamespace(text=text, reply_text=reply_mock),
    )


def _make_callback_update(data: str, user_id: int = 111):
    query = SimpleNamespace(
        data=data,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id, username="tecnico1"),
    )


def test_hitl_store_ttl_expiracion_y_usuario_distinto():
    store = HITLStore()
    pending = store.create_pending(
        user_id=111,
        tool_name="registrar_movimiento",
        arguments={"id_pieza": 699},
        ttl_seconds=240,
        now=1000.0,
    )

    # Otro usuario no puede consumirlo
    act, status = store.pop_pending(token=pending.token, user_id=222, now=1010.0)
    assert act is None
    assert status == "FORBIDDEN"

    # Mismo usuario después del TTL -> EXPIRED
    act, status = store.pop_pending(token=pending.token, user_id=111, now=1250.0)
    assert act is None
    assert status == "EXPIRED"

    # Ya eliminado tras expirar
    act, status = store.pop_pending(token=pending.token, user_id=111, now=1251.0)
    assert act is None
    assert status == "NOT_FOUND"


async def test_text_handler_despliega_inline_keyboard_para_mutacion():
    store = HITLStore()
    cfg = BotSettings(HITL_TTL_SECONDS=240, DEFAULT_TECNICO_ID=1)
    update = _make_text_update("Mueve la pieza 699 del lab 1 al 2")
    context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
    backend = SimpleNamespace(
        consultar_agente=AsyncMock(
            return_value={
                "respuesta": "Propuesta lista.",
                "tool_calls": [
                    {
                        "tool_name": "registrar_movimiento",
                        "requiere_confirmacion": True,
                        "arguments": {
                            "id_pieza": 699,
                            "origen_id": 1,
                            "destino_id": 2,
                            "motivo": "Mantenimiento",
                            "tecnico_id": 1,
                        },
                    }
                ],
            }
        )
    )

    await text_message_handler(
        update, context, backend_client=backend, settings=cfg, store=store  # type: ignore[arg-type]
    )

    update.effective_message.reply_text.assert_awaited_once()
    args, kwargs = update.effective_message.reply_text.call_args
    assert "Confirmación requerida" in args[0]
    assert "240 segundos" in args[0]
    markup = kwargs["reply_markup"]
    buttons = markup.inline_keyboard[0]
    assert len(buttons) == 2
    assert buttons[0].callback_data.startswith("hitl:confirm:")
    assert buttons[1].callback_data.startswith("hitl:cancel:")


async def test_hitl_callback_confirmar_ejecuta_mutacion():
    store = HITLStore()
    pending = store.create_pending(
        user_id=111,
        tool_name="registrar_movimiento",
        arguments={
            "id_pieza": 699,
            "origen_id": 1,
            "destino_id": 2,
            "motivo": "Reposición",
            "tecnico_id": 1,
        },
        ttl_seconds=240,
    )
    update = _make_callback_update(f"hitl:confirm:{pending.token}", user_id=111)
    backend = SimpleNamespace(
        ejecutar_mutacion=AsyncMock(
            return_value={
                "movimiento_id": 4,
                "componente_id": 699,
                "tipo_movimiento": "TRASLADO",
                "estado_componente": "EN_STOCK",
                "audit_log_id": 12,
            }
        )
    )

    await hitl_callback_handler(
        update, None, backend_client=backend, store=store  # type: ignore[arg-type]
    )

    backend.ejecutar_mutacion.assert_awaited_once_with(
        tool_name="registrar_movimiento",
        arguments=pending.arguments,
    )
    edited_text = update.callback_query.edit_message_text.call_args[0][0]
    assert "Traslado ejecutado correctamente" in edited_text
    assert "Movimiento ID: 4" in edited_text
    assert "Audit Log ID: 12" in edited_text


async def test_hitl_callback_cancelar_no_ejecuta_mutacion():
    store = HITLStore()
    pending = store.create_pending(
        user_id=111,
        tool_name="registrar_baja_componente",
        arguments={"id_pieza": 699, "motivo_falla": "Corto", "tecnico_id": 1},
        ttl_seconds=240,
    )
    update = _make_callback_update(f"hitl:cancel:{pending.token}", user_id=111)
    backend = SimpleNamespace(ejecutar_mutacion=AsyncMock())

    await hitl_callback_handler(
        update, None, backend_client=backend, store=store  # type: ignore[arg-type]
    )

    backend.ejecutar_mutacion.assert_not_awaited()
    edited_text = update.callback_query.edit_message_text.call_args[0][0]
    assert "cancelada" in edited_text.lower()


async def test_hitl_callback_error_backend_muestra_mensaje():
    store = HITLStore()
    pending = store.create_pending(
        user_id=111,
        tool_name="registrar_movimiento",
        arguments={"id_pieza": 699},
        ttl_seconds=240,
    )
    update = _make_callback_update(f"hitl:confirm:{pending.token}", user_id=111)
    backend = SimpleNamespace(
        ejecutar_mutacion=AsyncMock(
            side_effect=BackendClientError("Conflicto de concurrencia", "ORIGEN_MISMATCH")
        )
    )

    await hitl_callback_handler(
        update, None, backend_client=backend, store=store  # type: ignore[arg-type]
    )

    edited_text = update.callback_query.edit_message_text.call_args[0][0]
    assert "Conflicto de concurrencia" in edited_text

