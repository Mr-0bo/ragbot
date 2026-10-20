# backend/routers/user.py
import json
import datetime
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import case

from backend.database import get_db, Usuario, SesionChat, Mensaje, ConfiguracionApp
from backend.auth import obtener_usuario_actual

router = APIRouter(prefix="/api", tags=["Usuarios y Configuración"])


# ==========================================
# ESQUEMAS PYDANTIC
# ==========================================
class OnboardingRequest(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=30)
    pronombre: str
    nombre_agente: Optional[str] = Field("Copiloto Técnico", max_length=25)


class UserStatusResponse(BaseModel):
    registrado: bool
    username: str
    nombre: Optional[str] = None
    pronombre: Optional[str] = None
    nombre_agente: Optional[str] = "Copiloto Técnico"
    disclaimer_aceptado: bool = False
    region: str = "mexico"


class SessionResponse(BaseModel):
    id: str
    titulo: str
    fijado: bool = False


class RenameRequest(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=45)


class DisclaimerRequest(BaseModel):
    no_volver_a_mostrar: bool


class MessageResponse(BaseModel):
    rol: str
    contenido: str
    fuentes: List[str] = []


# ==========================================
# ENDPOINTS DE USUARIO Y CONFIGURACIÓN
# ==========================================

@router.get("/user/me", response_model=UserStatusResponse)
def consultar_usuario(
        usuario_actual=Depends(obtener_usuario_actual),
        db: Session = Depends(get_db)
):
    """Devuelve la información del usuario autenticado."""
    config = db.query(ConfiguracionApp).first()

    # Se considera completado solo si definió su pronombre y su nombre es distinto al username
    ha_completado_onboarding = bool(
        usuario_actual.pronombre and
        usuario_actual.nombre and
        usuario_actual.nombre != usuario_actual.username
    )

    return UserStatusResponse(
        registrado=ha_completado_onboarding,
        username=usuario_actual.username,
        nombre=usuario_actual.nombre if ha_completado_onboarding else "",
        pronombre=usuario_actual.pronombre,
        nombre_agente=usuario_actual.nombre_agente or "Copiloto Técnico",
        disclaimer_aceptado=bool(usuario_actual.disclaimer_aceptado),
        region=config.region if config else "mexico"
    )


@router.post("/user/disclaimer")
def registrar_disclaimer(
        data: DisclaimerRequest,
        usuario_actual=Depends(obtener_usuario_actual),
        db: Session = Depends(get_db)
):
    usuario_actual.disclaimer_aceptado = data.no_volver_a_mostrar
    db.commit()
    return {"status": "ok"}


@router.post("/user/onboarding")
def guardar_onboarding(
        data: OnboardingRequest,
        usuario_actual=Depends(obtener_usuario_actual),
        db: Session = Depends(get_db)
):
    """Guarda las preferencias personales del usuario."""
    usuario_actual.nombre = data.nombre.strip()
    usuario_actual.pronombre = data.pronombre
    usuario_actual.nombre_agente = data.nombre_agente.strip() if data.nombre_agente else "Copiloto Técnico"

    db.commit()
    return {"status": "ok"}


# ==========================================
# ENDPOINTS DE SESIONES Y MENSAJES AISLADOS
# ==========================================

@router.get("/sessions", response_model=List[SessionResponse])
def obtener_sesiones(
        usuario_actual=Depends(obtener_usuario_actual),
        db: Session = Depends(get_db)
):
    """Obtiene SOLO las sesiones del usuario logueado."""
    sesiones = (
        db.query(SesionChat)
        .filter(SesionChat.usuario_id == usuario_actual.id)
        .order_by(
            case((SesionChat.fijado == True, 0), else_=1),
            SesionChat.fijado_en.desc(),
            SesionChat.actualizado_en.desc(),
            SesionChat.creado_en.desc()
        )
        .all()
    )
    return [SessionResponse(id=s.id, titulo=s.titulo, fijado=bool(s.fijado)) for s in sesiones]


@router.post("/sessions", response_model=SessionResponse)
def crear_nueva_sesion(
        usuario_actual=Depends(obtener_usuario_actual),
        db: Session = Depends(get_db)
):
    ahora = datetime.datetime.utcnow()
    nueva = SesionChat(
        id=str(uuid.uuid4()),
        usuario_id=usuario_actual.id,
        titulo="Nueva consulta",
        actualizado_en=ahora,
        creado_en=ahora
    )
    db.add(nueva)
    db.commit()
    return SessionResponse(id=nueva.id, titulo=nueva.titulo, fijado=False)


@router.patch("/sessions/{session_id}/pin")
def alternar_fijar_sesion(
        session_id: str,
        usuario_actual=Depends(obtener_usuario_actual),
        db: Session = Depends(get_db)
):
    sesion = db.query(SesionChat).filter(
        SesionChat.id == session_id,
        SesionChat.usuario_id == usuario_actual.id
    ).first()

    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada o acceso denegado.")

    if sesion.fijado:
        sesion.fijado = False
        sesion.fijado_en = None
    else:
        fijados_actuales = (
            db.query(SesionChat)
            .filter(SesionChat.usuario_id == usuario_actual.id, SesionChat.fijado == True)
            .count()
        )
        if fijados_actuales >= 3:
            raise HTTPException(
                status_code=400,
                detail="Límite alcanzado: solo puedes fijar hasta 3 chats simultáneamente."
            )
        sesion.fijado = True
        sesion.fijado_en = datetime.datetime.utcnow()

    db.commit()
    return {"status": "ok", "fijado": sesion.fijado}


@router.patch("/sessions/{session_id}/rename")
def renombrar_sesion(
        session_id: str,
        data: RenameRequest,
        usuario_actual=Depends(obtener_usuario_actual),
        db: Session = Depends(get_db)
):
    sesion = db.query(SesionChat).filter(
        SesionChat.id == session_id,
        SesionChat.usuario_id == usuario_actual.id
    ).first()

    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada o acceso denegado.")

    sesion.titulo = data.titulo.strip()
    db.commit()
    return {"status": "ok", "titulo": sesion.titulo}


@router.delete("/sessions/single/{session_id}")
def eliminar_sesion_individual(
        session_id: str,
        usuario_actual=Depends(obtener_usuario_actual),
        db: Session = Depends(get_db)
):
    sesion = db.query(SesionChat).filter(
        SesionChat.id == session_id,
        SesionChat.usuario_id == usuario_actual.id
    ).first()

    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada o acceso denegado.")

    db.delete(sesion)
    db.commit()
    return {"status": "ok", "id": session_id}


@router.delete("/sessions/clear-all")
def eliminar_todas_las_sesiones(
        usuario_actual=Depends(obtener_usuario_actual),
        db: Session = Depends(get_db)
):
    sesiones = db.query(SesionChat).filter(SesionChat.usuario_id == usuario_actual.id).all()
    for s in sesiones:
        db.delete(s)
    db.commit()
    return {"status": "ok", "eliminadas": len(sesiones)}


@router.get("/messages/{session_id}", response_model=List[MessageResponse])
def obtener_historial_sesion(
        session_id: str,
        usuario_actual=Depends(obtener_usuario_actual),
        db: Session = Depends(get_db)
):
    sesion = db.query(SesionChat).filter(
        SesionChat.id == session_id,
        SesionChat.usuario_id == usuario_actual.id
    ).first()

    if not sesion:
        raise HTTPException(status_code=403, detail="Acceso denegado a esta sesión.")

    mensajes = (
        db.query(Mensaje)
        .filter(Mensaje.sesion_id == session_id)
        .order_by(Mensaje.creado_en.asc())
        .all()
    )

    salida = []
    for m in mensajes:
        fuentes_lista = []
        if getattr(m, "fuentes", None):
            try:
                fuentes_lista = json.loads(m.fuentes)
            except Exception:
                fuentes_lista = []
        salida.append(
            MessageResponse(
                rol=m.rol,
                contenido=m.contenido,
                fuentes=fuentes_lista
            )
        )
    return salida