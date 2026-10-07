# backend/routers/chat.py
import datetime
import uuid
import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db, SesionChat, Mensaje
from backend.rag_engine import ejecutar_consulta_async

router = APIRouter(prefix="/api", tags=["Chat"])


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    pregunta: str = Field(..., min_length=1, description="Texto de la consulta")


class ChatResponse(BaseModel):
    respuesta: str
    fuentes: list[str]


@router.post("/chat", response_model=ChatResponse)
async def endpoint_chat(payload: ChatRequest, db: Session = Depends(get_db)):
    """Manejo asíncrono de consultas para evitar bloqueos del servidor."""
    pregunta_limpia = payload.pregunta.strip()
    if not pregunta_limpia:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")

    try:
        resultado = await ejecutar_consulta_async(
            user_id=payload.user_id,
            session_id=payload.session_id,
            pregunta=pregunta_limpia,
            db=db
        )

        sesion = db.query(SesionChat).filter(SesionChat.id == payload.session_id).first()
        if sesion:
            sesion.actualizado_en = datetime.datetime.utcnow()
            db.commit()

        return ChatResponse(
            respuesta=resultado["respuesta"],
            fuentes=resultado["fuentes"]
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"[ERROR ASYNC CHAT] {e}")
        raise HTTPException(
            status_code=500,
            detail="Ocurrió un error al procesar la consulta con el motor asíncrono."
        )


class ImportRequest(BaseModel):
    ruta_archivo: str


@router.post("/sessions/{user_id}/import")
def importar_sesion_json(
        payload: ImportRequest,
        user_id: str = Path(..., description="ID del usuario"),
        db: Session = Depends(get_db)
):
    ruta = payload.ruta_archivo.strip()
    if not ruta or not ruta.endswith(".json"):
        raise HTTPException(status_code=400, detail="Debes seleccionar un archivo .json válido.")

    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            contenido = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el archivo: {e}")

    if "mensajes" not in contenido or not isinstance(contenido["mensajes"], list):
        raise HTTPException(status_code=400, detail="El archivo JSON no tiene un formato válido.")

    nueva_sesion_id = str(uuid.uuid4())
    nueva_sesion = SesionChat(
        id=nueva_sesion_id,
        usuario_id=user_id,
        titulo=f"{contenido.get('titulo', 'Consulta')} (Importada)",
        creado_en=datetime.datetime.utcnow(),
        actualizado_en=datetime.datetime.utcnow()
    )
    db.add(nueva_sesion)

    mensajes_db = []
    for msg in contenido["mensajes"]:
        fuentes_lista = msg.get("fuentes", [])
        fuentes_str = json.dumps(fuentes_lista) if fuentes_lista else "[]"

        nuevo_mensaje = Mensaje(
            id=str(uuid.uuid4()),
            sesion_id=nueva_sesion_id,
            rol=msg.get("rol", "user"),
            contenido=msg.get("contenido", ""),
            fuentes=fuentes_str,
            creado_en=datetime.datetime.utcnow()
        )
        mensajes_db.append(nuevo_mensaje)

    try:
        db.add_all(mensajes_db)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[ERROR IMPORTACIÓN] {e}")
        raise HTTPException(status_code=500, detail="Error al guardar la sesión importada.")

    return {
        "status": "success",
        "session_id": nueva_sesion_id,
        "titulo": nueva_sesion.titulo
    }