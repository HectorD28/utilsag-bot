import json
from dataclasses import dataclass

import cv2
import numpy as np

try:
    from pyzbar.pyzbar import decode as _pyzbar_decode
except Exception:  # noqa: BLE001 - libzbar0 puede no estar instalada en el SO
    _pyzbar_decode = None


@dataclass(frozen=True)
class QRDecodeResult:
    codigo: str
    raw_payload: str
    metodo: str


def _extract_codigo(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if cleaned.startswith("{"):
        try:
            data = json.loads(cleaned)
            for key in ("codigo_patrimonial", "codigo_sbn", "codigo", "id"):
                if data.get(key):
                    return str(data[key]).strip()
        except json.JSONDecodeError:
            pass
    return cleaned


def decode_qr_local(image_bytes: bytes) -> QRDecodeResult | None:
    """Decodifica códigos QR localmente usando pyzbar y OpenCV (HU-15 CA-1)."""
    if not image_bytes:
        return None

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None

    if _pyzbar_decode is not None:
        try:
            decoded = _pyzbar_decode(img)
            for item in decoded:
                raw = item.data.decode("utf-8", errors="ignore").strip()
                if raw:
                    return QRDecodeResult(
                        codigo=_extract_codigo(raw),
                        raw_payload=raw,
                        metodo="QR_LOCAL_PYZBAR",
                    )
        except Exception:  # noqa: BLE001
            pass

    detector = cv2.QRCodeDetector()
    raw_cv, _points, _ = detector.detectAndDecode(img)
    if raw_cv and raw_cv.strip():
        raw_text = raw_cv.strip()
        return QRDecodeResult(
            codigo=_extract_codigo(raw_text),
            raw_payload=raw_text,
            metodo="QR_LOCAL_OPENCV",
        )

    return None

