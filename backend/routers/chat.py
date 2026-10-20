# backend/routers/chat.py
import asyncio
import datetime
import uuid
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db, SessionLocal, SesionChat, Mensaje
from backend.rag_engine import clasificar_intencion_async, reformular_pregunta_con_historial_async
from backend.search_service import buscar_fragmentos
from backend.llm_orchestrator import generar_respuesta_chat_stream_async
from backend.auth import obtener_usuario_actual

router = APIRouter(prefix="/api", tags=["Chat"])

semaforo_ia = asyncio.Semaphore(1)


class ChatRequest(BaseModel):
    session_id: str
    pregunta: str = Field(..., min_length=1, description="Texto de la consulta")


class ImportRequest(BaseModel):
    ruta_archivo: Optional[str] = None
    titulo: Optional[str] = "Consulta"
    mensajes: Optional[List[dict]] = None


@router.post("/chat")
async def endpoint_chat_streaming(
    request: Request,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    usuario_actual=Depends(obtener_usuario_actual)
):
    pregunta_limpia = payload.pregunta.strip()
    if not pregunta_limpia:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")

    # 1. Validar propiedad y aislamiento de sesión
    sesion = db.query(SesionChat).filter(
        SesionChat.id == payload.session_id,
        SesionChat.usuario_id == usuario_actual.id
    ).first()

    if not sesion:
        raise HTTPException(status_code=403, detail="Sesión no encontrada o acceso denegado.")

    # Guardar mensaje del usuario en la BD de inmediato
    msg_user = Mensaje(
        id=str(uuid.uuid4()),
        sesion_id=payload.session_id,
        rol="user",
        contenido=pregunta_limpia,
        fuentes="[]",
        creado_en=datetime.datetime.utcnow()
    )
    db.add(msg_user)
    db.commit()

    async def generador_stream():
        db_stream = SessionLocal()
        texto_completo_acumulado = []
        fuentes_finales = []

        try:
            async with semaforo_ia:
                # 2. Clasificación de intención
                intencion = await clasificar_intencion_async(pregunta_limpia)

                # Obtener historial previo para contexto
                mensajes_previos = db_stream.query(Mensaje).filter(
                    Mensaje.sesion_id == payload.session_id
                ).order_by(Mensaje.creado_en.asc()).all()

                historial_dto = [{"rol": m.rol, "contenido": m.contenido} for m in mensajes_previos[:-1]]

                fragmentos_normativos = []
                etiquetas_fuentes = []
                contexto_textual = ""

                # Solo buscamos documentos si NO es conversacional
                if intencion != "CONVERSACIONAL":
                    subconsultas = await reformular_pregunta_con_historial_async(historial_dto, pregunta_limpia)
                    fragmentos_normativos = buscar_fragmentos(
                        consultas=subconsultas,
                        consulta_referencia=pregunta_limpia,
                        top_k=6
                    )

                    for f in fragmentos_normativos:
                        doc = f.get("documento", "Doc")
                        pag = f.get("pagina", "N/A")
                        etiqueta = f"{doc}, Pág. {pag}"
                        if etiqueta not in etiquetas_fuentes:
                            etiquetas_fuentes.append(etiqueta)
                        contexto_textual += f"\n--- [{etiqueta}] ---\n{f.get('contenido', '')}\n"

                fuentes_finales = etiquetas_fuentes

                # Emitir fuentes encontradas (irá como [] si es saludo o conversacional)
                yield f"data: {json.dumps({'tipo': 'meta', 'fuentes': fuentes_finales})}\n\n"

                # 3. Formular prompt del sistema
                nombre_usuario = usuario_actual.nombre or "Usuario"
                trato = usuario_actual.pronombre or "neutro"

                system_prompt = f"""Eres Vértice, asistente técnico de ingeniería y normativas corporativas.
Estás dialogando con {nombre_usuario} (Trato: {trato}).
Responde con precisión rigurosa, citando las fuentes normativas entre corchetes cuando uses datos técnicos.
Si el usuario solo te está saludando o agradeciendo, responde cordialmente sin inventar referencias.
"""

                if contexto_textual:
                    user_prompt = f"DOCUMENTACIÓN TÉCNICA RECUPERADA:\n{contexto_textual}\n\nPREGUNTA:\n{pregunta_limpia}"
                else:
                    user_prompt = pregunta_limpia

                # 4. Stream de tokens
                async for token in generar_respuesta_chat_stream_async(system_prompt, user_prompt, historial_dto):
                    if await request.is_disconnected():
                        print("[STREAM] Cliente desconectado o canceló la consulta.")
                        break

                    texto_completo_acumulado.append(token)
                    yield f"data: {json.dumps({'tipo': 'token', 'contenido': token})}\n\n"

                yield f"data: {json.dumps({'tipo': 'fin'})}\n\n"

        except Exception as e:
            print(f"[ERROR STREAM ROUTER] {e}")
            yield f"data: {json.dumps({'tipo': 'error', 'mensaje': str(e)})}\n\n"

        finally:
            # 5. Persistir la respuesta consolidada en SQLite
            respuesta_str = "".join(texto_completo_acumulado).strip()
            if respuesta_str:
                msg_assistant = Mensaje(
                    id=str(uuid.uuid4()),
                    sesion_id=payload.session_id,
                    rol="assistant",
                    contenido=respuesta_str,
                    fuentes=json.dumps(fuentes_finales),
                    creado_en=datetime.datetime.utcnow()
                )
                db_stream.add(msg_assistant)

                sesion_db = db_stream.query(SesionChat).filter(SesionChat.id == payload.session_id).first()
                if sesion_db:
                    sesion_db.actualizado_en = datetime.datetime.utcnow()
                    if sesion_db.titulo == "Nueva consulta" or sesion_db.titulo.startswith("Consulta"):
                        sesion_db.titulo = pregunta_limpia[:35] + ("..." if len(pregunta_limpia) > 35 else "")

                db_stream.commit()
            db_stream.close()

    return StreamingResponse(
        generador_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/sessions/import")
def importar_sesion_json(
    payload: ImportRequest,
    db: Session = Depends(get_db),
    usuario_actual=Depends(obtener_usuario_actual)
):
    mensajes = payload.mensajes or []
    titulo = payload.titulo or "Consulta"

    if not mensajes and payload.ruta_archivo:
        ruta = payload.ruta_archivo.strip()
        if not ruta.endswith(".json"):
            raise HTTPException(status_code=400, detail="Debes proporcionar un JSON válido.")
        try:
            with open(ruta, 'r', encoding='utf-8') as f:
                data = json.load(f)
                mensajes = data.get("mensajes", [])
                titulo = data.get("titulo", "Consulta")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"No se pudo leer el archivo: {e}")

    if not isinstance(mensajes, list):
        raise HTTPException(status_code=400, detail="Formato de mensajes inválido.")

    nueva_sesion_id = str(uuid.uuid4())
    nueva_sesion = SesionChat(
        id=nueva_sesion_id,
        usuario_id=usuario_actual.id,
        titulo=f"{titulo} (Importada)",
        creado_en=datetime.datetime.utcnow(),
        actualizado_en=datetime.datetime.utcnow()
    )
    db.add(nueva_sesion)

    for msg in mensajes:
        fuentes_lista = msg.get("fuentes", [])
        nuevo_mensaje = Mensaje(
            id=str(uuid.uuid4()),
            sesion_id=nueva_sesion_id,
            rol=msg.get("rol", "user"),
            contenido=msg.get("contenido", ""),
            fuentes=json.dumps(fuentes_lista) if fuentes_lista else "[]",
            creado_en=datetime.datetime.utcnow()
        )
        db.add(nuevo_mensaje)

    db.commit()

    return {
        "status": "success",
        "session_id": nueva_sesion_id,
        "titulo": nueva_sesion.titulo
    }