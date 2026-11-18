from typing import Any

_MAX_TELEGRAM_CHARS = 3800


def format_hitl_summary(
    tool_name: str,
    arguments: dict[str, Any],
    ttl_seconds: int,
) -> str:
    """Construye la ficha resumen de confirmación HITL para Telegram (HU-16 CA-1)."""
    if tool_name == "registrar_movimiento":
        lines = [
            "Confirmación requerida: Traslado de Componente",
            f"• Activo / Pieza ID: {arguments.get('id_pieza')}",
            f"• Origen (Lab ID): {arguments.get('origen_id')}",
            f"• Destino (Lab ID): {arguments.get('destino_id')}",
        ]
        if arguments.get("equipo_destino_id") is not None:
            lines.append(f"• Equipo Destino ID: {arguments['equipo_destino_id']}")
        lines.append(f"• Motivo: {arguments.get('motivo')}")
    else:
        lines = [
            "Confirmación requerida: Propuesta de Baja Técnica",
            f"• Activo / Pieza ID: {arguments.get('id_pieza')}",
            f"• Motivo de falla: {arguments.get('motivo_falla')}",
            "• Alcance: Propuesta preliminar USGOM (Directiva N.° 0006-2021-EF/54.01)",
        ]

    lines.append("")
    lines.append(f"Vigencia: {ttl_seconds} segundos para confirmar.")
    return "\n".join(lines)


def format_mutation_result(tool_name: str, result: dict[str, Any]) -> str:
    """Formatea el resultado real devuelto por PostgreSQL tras confirmar HITL."""
    if tool_name == "registrar_movimiento":
        return (
            "✅ Traslado ejecutado correctamente.\n"
            f"• Movimiento ID: {result.get('movimiento_id')}\n"
            f"• Pieza ID: {result.get('componente_id')}\n"
            f"• Tipo: {result.get('tipo_movimiento')}\n"
            f"• Nuevo estado: {result.get('estado_componente')}\n"
            f"• Audit Log ID: {result.get('audit_log_id')}"
        )
    return (
        "✅ Propuesta técnica de baja registrada.\n"
        f"• Baja ID: {result.get('baja_id')}\n"
        f"• Pieza ID: {result.get('componente_id')}\n"
        f"• Estado componente: {result.get('estado_componente')}\n"
        f"• Estado patrimonial: {result.get('estado_patrimonial')}\n"
        f"• Audit Log ID: {result.get('audit_log_id')}"
    )


def format_agent_response(data: dict[str, Any]) -> str:
    """Formatea la respuesta del agente de forma concisa y legible para pantallas móviles."""
    respuesta = str(data.get("respuesta") or "").strip()
    tool_calls = data.get("tool_calls") or []

    lines: list[str] = []
    if respuesta:
        lines.append(respuesta)

    for tc in tool_calls:
        if tc.get("requiere_confirmacion"):
            tool_name = tc.get("tool_name", "operacion")
            args = tc.get("arguments") or {}
            lines.append("")
            lines.append(
                f"Acción detectada: {tool_name} (pendiente de confirmación HITL)"
            )
            if "id_pieza" in args:
                lines.append(f"- Pieza ID: {args['id_pieza']}")
            if "origen_id" in args and "destino_id" in args:
                lines.append(
                    f"- Origen ID: {args['origen_id']} -> Destino ID: {args['destino_id']}"
                )
            if args.get("motivo"):
                lines.append(f"- Motivo: {args['motivo']}")

    text = "\n".join(lines).strip() or "No se obtuvo respuesta del asistente."
    if len(text) > _MAX_TELEGRAM_CHARS:
        return text[: _MAX_TELEGRAM_CHARS - 20].rstrip() + "\n... (truncado)"
    return text


def format_equipo_historial(data: dict[str, Any]) -> str:
    """Formatea la ficha técnica y componentes de un equipo para pantalla móvil."""
    equipo = data.get("equipo") or {}
    comps = data.get("componentes_instalados") or []
    movs = data.get("historial_movimientos") or []

    lines = [
        f"💻 {equipo.get('nombre_identificador', 'Equipo')} (SBN: {equipo.get('codigo_patrimonial')})",
        f"• Ubicación: {equipo.get('laboratorio_nombre')} (Lab ID: {equipo.get('laboratorio_id')})",
        f"• Estado: {equipo.get('estado')}",
        f"• Componentes instalados ({len(comps)}):",
    ]
    for c in comps[:12]:
        lines.append(f"  - [{c.get('id')}] {c.get('tipo')}: {c.get('descripcion')}")
    if len(comps) > 12:
        lines.append(f"  ... y {len(comps) - 12} más")
    lines.append(f"• Movimientos registrados: {len(movs)}")

    text = "\n".join(lines)
    if len(text) > _MAX_TELEGRAM_CHARS:
        return text[: _MAX_TELEGRAM_CHARS - 20].rstrip() + "\n... (truncado)"
    return text
