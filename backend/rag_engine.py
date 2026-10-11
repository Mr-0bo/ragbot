# backend/rag_engine.py
import re
import uuid
import json
import asyncio
from typing import List
from sqlalchemy.orm import Session

from backend.database import Usuario, SesionChat, Mensaje, ConfiguracionApp
from backend.llm_orchestrator import (
    generar_respuesta_chat_async,
    clasificar_intencion,
    reformular_pregunta_con_historial_async
)
from backend.prompts import (
    generar_system_prompt,
    generar_prompt_consulta,
    generar_prompt_conversacional
)


def extraer_fuentes_citadas(texto_respuesta: str) -> List[str]:
    """Extrae SÓLO las citas explicitamente escritas por el LLM en la respuesta."""
    patron = r'\[([^\]]*?\.pdf[^\]]*?)\]'
    coincidencias = re.findall(patron, texto_respuesta, re.IGNORECASE)

    citas_unicas = []
    for cita in coincidencias:
        formato_corchete = f"[{cita.strip()}]"
        if formato_corchete not in citas_unicas:
            citas_unicas.append(formato_corchete)

    return citas_unicas


async def ejecutar_consulta_async(user_id: str, session_id: str, pregunta: str, db: Session) -> dict:
    usuario = db.query(Usuario).filter(Usuario.id == user_id).first()
    sesion = db.query(SesionChat).filter(SesionChat.id == session_id).first()

    if not usuario or not sesion:
        raise ValueError("Usuario o sesión no encontrados en la base de datos.")

    config = db.query(ConfiguracionApp).first()
    region_activa = config.region if config and config.region else "mexico"

    mensajes_anteriores = (
        db.query(Mensaje)
        .filter(Mensaje.sesion_id == sesion.id)
        .order_by(Mensaje.creado_en.asc())
        .all()
    )
    historial_lista = [{"rol": m.rol, "contenido": m.contenido} for m in mensajes_anteriores]

    msg_usuario = Mensaje(
        id=str(uuid.uuid4()),
        sesion_id=sesion.id,
        rol="user",
        contenido=pregunta
    )
    db.add(msg_usuario)

    if len(historial_lista) == 0:
        sesion.titulo = pregunta[:32] + ("..." if len(pregunta) > 32 else "")

    system_prompt = generar_system_prompt(
        nombre_agente=usuario.nombre_agente or "Copiloto Técnico",
        nombre_usuario=usuario.nombre or "Colaborador",
        pronombre=usuario.pronombre or "neutro"
    )

    intencion = clasificar_intencion(pregunta)
    print(f"\n[ROUTER INTENCIÓN LOCAL] '{pregunta}' -> Clasificado como: {intencion}")

    if intencion == "CONVERSACIONAL":
        prompt_conversacion = generar_prompt_conversacional(pregunta)
        respuesta_texto = await generar_respuesta_chat_async(
            system_prompt=system_prompt,
            user_prompt=prompt_conversacion,
            historial=historial_lista
        )
        fuentes_unicas = []
    else:
        from backend.search_service import buscar_fragmentos

        subconsultas = await reformular_pregunta_con_historial_async(historial_lista, pregunta)
        print(f"[REFORMULACIÓN / DESGLOSE (ASYNC)] -> {subconsultas}")

        # Búsqueda Densa Pura
        fragmentos_validos = await asyncio.to_thread(
            buscar_fragmentos,
            consultas=subconsultas,
            consulta_referencia=pregunta,
            region=region_activa,
            top_k=6,
            recall_k=12,
            max_por_doc=3,
            max_por_pagina=2
        )

        print(f"[RAG ENGINE] Fragmentos recuperados: {len(fragmentos_validos)}")
        print("\n" + "=" * 65)
        print(f"[RAG ENGINE] FRAGMENTOS ENVIADOS A GEMINI (XML) ({len(fragmentos_validos)}):")
        for idx, f in enumerate(fragmentos_validos):
            print(f" [{idx + 1}] {f.get('documento')} | Pág: {f.get('pagina')} | Score: {f.get('score', 0):.4f}")
        print("=" * 65 + "\n")

        if fragmentos_validos:
            prompt_usuario = generar_prompt_consulta(pregunta, fragmentos_validos)
            respuesta_texto = await generar_respuesta_chat_async(
                system_prompt=system_prompt,
                user_prompt=prompt_usuario,
                historial=historial_lista
            )

            # Extraemos ESTRICTAMENTE las fuentes que el modelo haya citado
            fuentes_unicas = extraer_fuentes_citadas(respuesta_texto)
            # NOTA: Se eliminó el código que forzaba las fuentes en el frontend
        else:
            print("\n[AVISO] No se encontraron documentos relevantes en Qdrant.\n")
            prompt_usuario = (
                f"El colaborador consulta: '{pregunta}'. "
                "Esta información técnica específica no se encuentra en los documentos indexados para la región seleccionada. "
                "Indica brevemente en una sola oración que la especificación o dato no está disponible en la base técnica actual."
            )
            respuesta_texto = await generar_respuesta_chat_async(
                system_prompt=system_prompt,
                user_prompt=prompt_usuario,
                historial=historial_lista
            )
            fuentes_unicas = []

    msg_asistente = Mensaje(
        id=str(uuid.uuid4()),
        sesion_id=sesion.id,
        rol="assistant",
        contenido=respuesta_texto,
        fuentes=json.dumps(fuentes_unicas) if fuentes_unicas else None
    )
    db.add(msg_asistente)
    db.commit()

    return {
        "respuesta": respuesta_texto,
        "fuentes": fuentes_unicas
    }