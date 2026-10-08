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

# Umbral de corte ajustado para el Cross-Encoder (Reranker)
UMBRAL_SIMILITUD_MINIMO = 0.0


def extraer_fuentes_citadas(texto_respuesta: str) -> List[str]:
    """
    Busca patrones de citación en el texto generado como:
    [Norma_Tecnica.pdf, Pág. 3] o [Especificacion.pdf, Pág. 2, 9]
    Devuelve las citas preservando el formato de corchetes, orden y sin duplicados.
    """
    patron = r'\[([^\]]*?\.pdf[^\]]*?)\]'
    coincidencias = re.findall(patron, texto_respuesta, re.IGNORECASE)

    citas_unicas = []
    for cita in coincidencias:
        formato_corchete = f"[{cita.strip()}]"
        if formato_corchete not in citas_unicas:
            citas_unicas.append(formato_corchete)

    return citas_unicas


async def ejecutar_consulta_async(user_id: str, session_id: str, pregunta: str, db: Session) -> dict:
    """
    Pipeline RAG asíncrono optimizado con dos etapas de recuperación:
    - Clasificación de intención local en CPU.
    - Reformulación y desglose asíncrono con Gemini.
    - Retrieval Híbrido en Qdrant (Dense BGE-M3 + BM25 con RRF, recall_k=12 optimizado).
    - Reranking semántico local vía BGE-Reranker-Base en threadpool aislado.
    - Encapsulado de contexto en bloques XML.
    - Síntesis técnica y citas normativas asíncronas con Gemini.
    """
    # 1. Validar existencia de usuario y sesión
    usuario = db.query(Usuario).filter(Usuario.id == user_id).first()
    sesion = db.query(SesionChat).filter(SesionChat.id == session_id).first()

    if not usuario or not sesion:
        raise ValueError("Usuario o sesión no encontrados en la base de datos.")

    # 2. Obtener la región activa configurada en la aplicación
    config = db.query(ConfiguracionApp).first()
    region_activa = config.region if config and config.region else "mexico"

    # 3. Recuperar historial de turnos previos
    mensajes_anteriores = (
        db.query(Mensaje)
        .filter(Mensaje.sesion_id == sesion.id)
        .order_by(Mensaje.creado_en.asc())
        .all()
    )
    historial_lista = [{"rol": m.rol, "contenido": m.contenido} for m in mensajes_anteriores]

    # 4. Guardar mensaje entrante del usuario
    msg_usuario = Mensaje(
        id=str(uuid.uuid4()),
        sesion_id=sesion.id,
        rol="user",
        contenido=pregunta
    )
    db.add(msg_usuario)

    # 5. Generar título preliminar si es el primer turno
    if len(historial_lista) == 0:
        sesion.titulo = pregunta[:32] + ("..." if len(pregunta) > 32 else "")

    # 6. Construir system prompt adaptado al estilo del usuario
    system_prompt = generar_system_prompt(
        nombre_agente=usuario.nombre_agente or "Copiloto Técnico",
        nombre_usuario=usuario.nombre or "Colaborador",
        pronombre=usuario.pronombre or "neutro"
    )

    # 7. Clasificar intención en local
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
        # Import diferido de búsqueda para no frenar el inicio del servidor
        from backend.search_service import buscar_fragmentos

        # Reformulación y desglose asíncrono
        subconsultas = await reformular_pregunta_con_historial_async(historial_lista, pregunta)
        print(f"[REFORMULACIÓN / DESGLOSE (ASYNC)] -> {subconsultas}")

        # Búsqueda híbrida + Reranking en thread separado (no bloquea FastAPI)
        todos_los_fragmentos = await asyncio.to_thread(
            buscar_fragmentos,
            consultas=subconsultas,
            consulta_referencia=pregunta,
            region=region_activa,
            top_k=6,
            recall_k=12,
            max_por_doc=3,
            max_por_pagina=2
        )

        fragmentos_validos = [f for f in todos_los_fragmentos if f.get("score", 0.0) >= UMBRAL_SIMILITUD_MINIMO]
        print(f"Fragmentos sobre umbral Reranker ({UMBRAL_SIMILITUD_MINIMO}): {len(fragmentos_validos)}/{len(todos_los_fragmentos)}")

        # Monitoreo detallado del contexto documental entregado
        print("\n" + "=" * 65)
        print(f"[RAG ENGINE] FRAGMENTOS ENVIADOS A GEMINI (XML) ({len(fragmentos_validos)}):")
        for idx, f in enumerate(fragmentos_validos):
            print(f" [{idx + 1}] {f.get('documento')} | Pág: {f.get('pagina')} | Score Reranker: {f.get('score', 0):.4f}")
        print("=" * 65 + "\n")

        if fragmentos_validos:
            # Construcción de prompt con validación XML estricta
            prompt_usuario = generar_prompt_consulta(pregunta, fragmentos_validos)

            # Generación técnica asíncrona
            respuesta_texto = await generar_respuesta_chat_async(
                system_prompt=system_prompt,
                user_prompt=prompt_usuario,
                historial=historial_lista
            )

            fuentes_unicas = extraer_fuentes_citadas(respuesta_texto)

            if not fuentes_unicas:
                indicadores_negativos_totales = [
                    "no se encuentra disponible en los documentos",
                    "no aparece en los documentos indexados",
                    "no está disponible en la base técnica"
                ]
                resp_low = respuesta_texto.lower()
                if not any(ind in resp_low for ind in indicadores_negativos_totales):
                    fuentes_unicas = list({f"[{f['documento']}, Pág. {f['pagina']}]" for f in fragmentos_validos})
        else:
            print("\n[AVISO] No se superó el umbral documental post-reranking.\n")
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

    # 8. Persistir intercambio en SQLite
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