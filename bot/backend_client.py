import base64
import logging
from typing import Any

import httpx

from bot.config import BotSettings, get_bot_settings

logger = logging.getLogger(__name__)

_MUTATION_ENDPOINTS = {
    "registrar_movimiento": "/tools/movimientos",
    "registrar_baja_componente": "/tools/bajas",
}


class BackendClientError(Exception):
    """Error controlado al comunicarse con la API central FastAPI."""

    def __init__(self, user_message: str, error_code: str = "BACKEND_ERROR"):
        self.user_message = user_message
        self.error_code = error_code
        super().__init__(user_message)


class BackendClient:
    """Cliente HTTP asíncrono hacia la API central FastAPI (Capa 3)."""

    def __init__(self, settings: BotSettings | None = None) -> None:
        self._settings = settings or get_bot_settings()

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._settings.BACKEND_API_URL.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.BACKEND_TIMEOUT_SECONDS
            ) as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise BackendClientError(
                "La consulta tardó demasiado. Intenta nuevamente en unos segundos.",
                error_code="BACKEND_TIMEOUT",
            ) from exc
        except httpx.RequestError as exc:
            raise BackendClientError(
                "No se pudo conectar con el servidor central de UtilSAG-AI.",
                error_code="BACKEND_UNREACHABLE",
            ) from exc

        if resp.status_code >= 400:
            self._raise_http_error(resp)

        return resp.json()

    async def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self._settings.BACKEND_API_URL.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.BACKEND_TIMEOUT_SECONDS
            ) as client:
                resp = await client.get(url)
        except httpx.TimeoutException as exc:
            raise BackendClientError(
                "La consulta tardó demasiado. Intenta nuevamente en unos segundos.",
                error_code="BACKEND_TIMEOUT",
            ) from exc
        except httpx.RequestError as exc:
            raise BackendClientError(
                "No se pudo conectar con el servidor central de UtilSAG-AI.",
                error_code="BACKEND_UNREACHABLE",
            ) from exc

        if resp.status_code >= 400:
            self._raise_http_error(resp)

        return resp.json()

    def _raise_http_error(self, resp: httpx.Response) -> None:
        try:
            err_data = resp.json()
            err_code = err_data.get("error_code", "BACKEND_ERROR")
            detail = err_data.get("detail", "Error al procesar la solicitud.")
        except Exception:  # noqa: BLE001
            err_code = "BACKEND_ERROR"
            detail = "Error al procesar la solicitud."

        if err_code == "KILLSWITCH_ACTIVE":
            raise BackendClientError(
                "Operaciones del agente detenidas temporalmente por Kill Switch de emergencia.",
                error_code=err_code,
            )
        raise BackendClientError(str(detail), error_code=err_code)

    async def reportar_acceso_denegado(
        self,
        *,
        telegram_user_id: int,
        username: str | None,
        chat_id: int | None,
        detalle: str | None = None,
    ) -> dict[str, Any] | None:
        payload = {
            "telegram_user_id": telegram_user_id,
            "username": username,
            "chat_id": chat_id,
            "ip_address": self._settings.BOT_SOURCE_IP,
            "detalle": detalle,
        }
        try:
            return await self._post_json("/system/audit/telegram-denied", payload)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "No se pudo registrar auditoría de acceso denegado en backend: %s", exc
            )
            return None

    async def consultar_agente(
        self,
        *,
        mensaje: str,
        actor_externo: str | None = None,
        tecnico_id: int | None = None,
    ) -> dict[str, Any]:
        """Envía una consulta en lenguaje natural a POST /api/v1/agent/query (sin mutar BD)."""
        payload: dict[str, Any] = {
            "mensaje": mensaje,
            "origen_canal": "TELEGRAM",
            "actor_externo": actor_externo,
            "ejecutar_mutaciones": False,
        }
        if tecnico_id is not None:
            payload["tecnico_id"] = tecnico_id
        return await self._post_json("/agent/query", payload)

    async def ejecutar_mutacion(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Ejecuta una mutación confirmada vía HITL directamente en el endpoint determinista."""
        path = _MUTATION_ENDPOINTS.get(tool_name)
        if path is None:
            raise BackendClientError(
                f"Herramienta de mutación no soportada: {tool_name}",
                error_code="UNSUPPORTED_TOOL",
            )
        return await self._post_json(path, arguments)

    async def analizar_placa_ocr(
        self,
        *,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        """Envía una imagen en Base64 al módulo de visión LLM (HU-15 CA-2)."""
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return await self._post_json(
            "/agent/vision-ocr",
            {"imagen_base64": encoded, "mime_type": mime_type},
        )

    async def consultar_historial_equipo(
        self, *, codigo_patrimonial: str
    ) -> dict[str, Any]:
        """Obtiene ficha técnica e historial directo desde /tools/equipos/{codigo}/historial."""
        return await self._get_json(f"/tools/equipos/{codigo_patrimonial}/historial")
