from types import SimpleNamespace
from unittest.mock import AsyncMock

import cv2
import numpy as np

from bot.handlers import photo_message_handler, vision_callback_handler
from bot.vision import QRDecodeResult, decode_qr_local


def _make_blank_jpeg_bytes() -> bytes:
    img = np.full((120, 120, 3), 255, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _make_photo_update(image_bytes: bytes):
    tg_file = SimpleNamespace(
        download_as_bytearray=AsyncMock(return_value=bytearray(image_bytes))
    )
    photo = SimpleNamespace(get_file=AsyncMock(return_value=tg_file))
    message = SimpleNamespace(photo=[photo], reply_text=AsyncMock())
    return SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=9001),
    )


def test_decode_qr_local_sin_qr_retorna_none():
    assert decode_qr_local(b"") is None
    assert decode_qr_local(_make_blank_jpeg_bytes()) is None


async def test_photo_handler_qr_local_no_llama_ocr_llm(monkeypatch):
    monkeypatch.setattr(
        "bot.handlers.decode_qr_local",
        lambda _b: QRDecodeResult(
            codigo="740868655163", raw_payload="740868655163", metodo="QR_LOCAL_OPENCV"
        ),
    )
    backend = SimpleNamespace(analizar_placa_ocr=AsyncMock())
    update = _make_photo_update(b"fake-img")
    context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))

    await photo_message_handler(
        update, context, backend_client=backend  # type: ignore[arg-type]
    )

    backend.analizar_placa_ocr.assert_not_awaited()
    args, kwargs = update.effective_message.reply_text.call_args
    assert "740868655163" in args[0]
    assert "100%" in args[0]
    buttons = kwargs["reply_markup"].inline_keyboard[0]
    assert buttons[0].callback_data == "vision:hist:740868655163"


async def test_photo_handler_ocr_llm_confianza_baja_pide_reintento(monkeypatch):
    monkeypatch.setattr("bot.handlers.decode_qr_local", lambda _b: None)
    backend = SimpleNamespace(
        analizar_placa_ocr=AsyncMock(
            return_value={
                "codigo_sbn": "740868655163",
                "numero_serie": None,
                "confianza": 0.65,
                "requiere_reintento": True,
                "observacion": "Reflejo en la placa",
            }
        )
    )
    update = _make_photo_update(b"fake-img")
    context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))

    await photo_message_handler(
        update, context, backend_client=backend  # type: ignore[arg-type]
    )

    args, kwargs = update.effective_message.reply_text.call_args
    assert "65%" in args[0]
    assert "90%" in args[0]
    assert "reply_markup" not in kwargs


async def test_vision_callback_handler_consulta_historial():
    query = SimpleNamespace(
        data="vision:hist:740868655163",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)
    backend = SimpleNamespace(
        consultar_historial_equipo=AsyncMock(
            return_value={
                "equipo": {
                    "nombre_identificador": "PC-ALU-001",
                    "codigo_patrimonial": "740868655163",
                    "laboratorio_nombre": "Laboratorio 1",
                    "laboratorio_id": 2,
                    "estado": "OPERATIVO",
                },
                "componentes_instalados": [
                    {"id": 699, "tipo": "Mouse", "descripcion": "Genius basico"}
                ],
                "historial_movimientos": [],
            }
        )
    )

    await vision_callback_handler(
        update, None, backend_client=backend  # type: ignore[arg-type]
    )

    backend.consultar_historial_equipo.assert_awaited_once_with(
        codigo_patrimonial="740868655163"
    )
    edited = query.edit_message_text.call_args[0][0]
    assert "PC-ALU-001" in edited
    assert "740868655163" in edited

