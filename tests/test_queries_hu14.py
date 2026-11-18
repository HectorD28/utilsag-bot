from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bot.backend_client import BackendClient, BackendClientError
from bot.config import BotSettings
from bot.formatters import format_agent_response
from bot.handlers import text_message_handler


def test_format_agent_response_consulta_normal():
    text = format_agent_response(
        {"respuesta": "Hay 4 memorias RAM en Almacén.", "tool_calls": []}
    )
    assert text == "Hay 4 memorias RAM en Almacén."


def test_format_agent_response_con_propuesta_hitl_y_truncado():
    text = format_agent_response(
        {
            "respuesta": "Propuesta lista.",
            "tool_calls": [
                {
                    "tool_name": "registrar_movimiento",
                    "requiere_confirmacion": True,
                    "arguments": {
                        "id_pieza": 699,
                        "origen_id": 2,
                        "destino_id": 1,
                        "motivo": "Mantenimiento",
                    },
                }
            ],
        }
    )
    assert "Acción detectada: registrar_movimiento" in text
    assert "Pieza ID: 699" in text
    assert "Origen ID: 2 -> Destino ID: 1" in text

    long_text = format_agent_response({"respuesta": "A" * 5000, "tool_calls": []})
    assert len(long_text) <= 3800
    assert long_text.endswith("... (truncado)")


async def test_text_message_handler_consulta_ok():
    reply_mock = AsyncMock()
    send_action_mock = AsyncMock()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=111, username="tecnico1"),
        effective_chat=SimpleNamespace(id=9001),
        effective_message=SimpleNamespace(
            text="¿Cuántas RAM hay en Almacén?",
            reply_text=reply_mock,
        ),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=send_action_mock))
    backend = SimpleNamespace(
        consultar_agente=AsyncMock(
            return_value={"respuesta": "Hay 3 RAM disponibles.", "tool_calls": []}
        )
    )

    await text_message_handler(update, context, backend_client=backend)  # type: ignore[arg-type]

    send_action_mock.assert_awaited_once()
    backend.consultar_agente.assert_awaited_once_with(
        mensaje="¿Cuántas RAM hay en Almacén?",
        actor_externo="tg:111 (@tecnico1)",
        tecnico_id=1,
    )
    reply_mock.assert_awaited_once_with("Hay 3 RAM disponibles.")


async def test_text_message_handler_maneja_backend_error():
    reply_mock = AsyncMock()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=111, username=None),
        effective_chat=None,
        effective_message=SimpleNamespace(text="Hola", reply_text=reply_mock),
    )
    backend = SimpleNamespace(
        consultar_agente=AsyncMock(
            side_effect=BackendClientError("Kill switch activo", "KILLSWITCH_ACTIVE")
        )
    )

    await text_message_handler(update, None, backend_client=backend)  # type: ignore[arg-type]

    reply_mock.assert_awaited_once_with("Kill switch activo")


async def test_backend_client_consultar_agente_ok_y_killswitch(monkeypatch):
    def _mock_client_factory(status_code: int, json_body: dict):
        class _FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, url, json):
                return httpx.Response(
                    status_code=status_code,
                    json=json_body,
                    request=httpx.Request("POST", url),
                )

        return _FakeClient

    client = BackendClient(BotSettings(BACKEND_API_URL="http://test/api/v1"))

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _mock_client_factory(200, {"respuesta": "Stock OK", "tool_calls": []}),
    )
    res = await client.consultar_agente(mensaje="Stock RAM", actor_externo="tg:1")
    assert res["respuesta"] == "Stock OK"

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _mock_client_factory(
            503, {"error_code": "KILLSWITCH_ACTIVE", "detail": "Detenido"}
        ),
    )
    with pytest.raises(BackendClientError) as exc_info:
        await client.consultar_agente(mensaje="Stock RAM")
    assert exc_info.value.error_code == "KILLSWITCH_ACTIVE"

