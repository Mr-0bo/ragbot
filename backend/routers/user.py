# backend/routers/user.py
import os
import sys
import uuid
import json
import datetime
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import case

from backend.database import get_db, Usuario, SesionChat, Mensaje, ConfiguracionApp

router = APIRouter(prefix="/api", tags=["Usuarios y Configuración"])


# ==========================================
# UTILIDADES DE VALIDACIÓN DE ONEDRIVE
# ==========================================
def obtener_rutas_onedrive_sistema() -> List[Path]:
    """Detecta las rutas oficiales de OneDrive en Windows y macOS."""
    rutas = []
    # 1. Variables de entorno comunes
    for var in ["OneDriveCommercial", "OneDriveConsumer", "OneDrive", "ONEDRIVE"]:
        val = os.getenv(var)
        if val and Path(val).is_dir():
            rutas.append(Path(val).resolve())

    # 2. macOS CloudStorage
    mac_cloud = Path.home() / "Library" / "CloudStorage"
    if mac_cloud.exists():
        for d in mac_cloud.iterdir():
            if d.is_dir() and "OneDrive" in d.name and d not in rutas:
                rutas.append(d.resolve())

    # 3. Directorio del perfil de usuario (Windows / macOS)
    perfil = Path.home()
    for d in perfil.iterdir():
        if d.is_dir() and "onedrive" in d.name.lower() and d.resolve() not in rutas:
            rutas.append(d.resolve())

    return rutas

def validar_carpeta_onedrive(ruta_str: str) -> Path:
    """Verifica que la ruta exista y sea un directorio (permite cualquier carpeta local)."""
    if not ruta_str or not ruta_str.strip():
        raise HTTPException(status_code=400, detail="La ruta no puede estar vacía.")

    ruta = Path(ruta_str.strip()).expanduser().resolve()
    if not ruta.exists() or not ruta.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"La ruta '{ruta_str}' no existe o no es un directorio válido."
        )

    return ruta


# ==========================================
# ESQUEMAS PYDANTIC
# ==========================================
class DirectorioValidacionRequest(BaseModel):
    ruta: str


class OnboardingRequest(BaseModel):
    user_id: str
    nombre: str = Field(..., min_length=1, max_length=30)
    pronombre: str
    nombre_agente: Optional[str] = Field("Copiloto Técnico", max_length=25)
    region: str = Field("mexico", pattern="^(mexico|centroamerica)$")
    directorio_obligatorio: str
    directorio_opcional_1: Optional[str] = None
    directorio_opcional_2: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    region: Optional[str] = Field(None, pattern="^(mexico|centroamerica)$")
    directorio_obligatorio: str
    directorio_opcional_1: Optional[str] = None
    directorio_opcional_2: Optional[str] = None


class UserStatusResponse(BaseModel):
    registrado: bool
    nombre: Optional[str] = None
    pronombre: Optional[str] = None
    nombre_agente: Optional[str] = "Copiloto Técnico"
    disclaimer_aceptado: bool = False
    onboarding_completado: bool = False
    region: str = "mexico"
    directorio_obligatorio: Optional[str] = None
    directorio_opcional_1: Optional[str] = None
    directorio_opcional_2: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    titulo: str
    fijado: bool = False


class RenameRequest(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=45)


class DisclaimerRequest(BaseModel):
    user_id: str
    no_volver_a_mostrar: bool


class MessageResponse(BaseModel):
    rol: str
    contenido: str
    fuentes: List[str] = []


# ==========================================
# ENDPOINTS DE CONFIGURACIÓN Y ONBOARDING (TKINTER NATIVO)
# ==========================================
@router.post("/browse-directory")
def examinar_directorio_nativo():
    """Abre el explorador de carpetas nativo instantáneamente usando Tkinter."""
    ruta_elegida = ""
    try:
        root = tk.Tk()
        root.withdraw()  # Oculta la ventana principal de tkinter
        root.attributes('-topmost', True)  # Forzar al frente
        ruta_elegida = filedialog.askdirectory(title="Selecciona la carpeta de normativas de OneDrive")
        root.destroy()
    except Exception as e:
        print(f"[WARN BROWSE DIR] Error en selector nativo: {e}")

    return {"ruta": ruta_elegida}


@router.post("/browse-file")
def examinar_archivo_nativo():
    """Abre el explorador de archivos nativo (.json) instantáneamente usando Tkinter."""
    ruta_elegida = ""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        ruta_elegida = filedialog.askopenfilename(
            title="Selecciona el chat a importar",
            filetypes=[("Archivos JSON", "*.json"), ("Todos los archivos", "*.*")]
        )
        root.destroy()
    except Exception as e:
        print(f"[WARN BROWSE FILE] Error en selector nativo: {e}")

    return {"ruta": ruta_elegida}


@router.post("/validate-directory")
def validar_directorio(data: DirectorioValidacionRequest):
    """Valida en tiempo real si una carpeta es de OneDrive antes de guardarla."""
    ruta_validada = validar_carpeta_onedrive(data.ruta)
    return {
        "status": "ok",
        "ruta_normalizada": str(ruta_validada)
    }


@router.get("/user/{user_id}", response_model=UserStatusResponse)
def consultar_usuario(user_id: str, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.id == user_id).first()
    config = db.query(ConfiguracionApp).first()

    return UserStatusResponse(
        registrado=bool(usuario and usuario.nombre),
        nombre=usuario.nombre if usuario else None,
        pronombre=usuario.pronombre if usuario else None,
        nombre_agente=usuario.nombre_agente if usuario else "Copiloto Técnico",
        disclaimer_aceptado=bool(usuario and usuario.disclaimer_aceptado),
        onboarding_completado=bool(config and config.onboarding_completado),
        region=config.region if config else "mexico",
        directorio_obligatorio=config.directorio_obligatorio if config else None,
        directorio_opcional_1=config.directorio_opcional_1 if config else None,
        directorio_opcional_2=config.directorio_opcional_2 if config else None
    )


@router.post("/user/disclaimer")
def registrar_disclaimer(data: DisclaimerRequest, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.id == data.user_id).first()
    if not usuario:
        usuario = Usuario(id=data.user_id)
        db.add(usuario)

    usuario.disclaimer_aceptado = data.no_volver_a_mostrar
    db.commit()
    return {"status": "ok"}


@router.post("/user/onboarding")
def guardar_onboarding(data: OnboardingRequest, db: Session = Depends(get_db)):
    # 1. Validar directorio obligatorio
    ruta_obligatoria = validar_carpeta_onedrive(data.directorio_obligatorio)

    # 2. Validar opcionales si se proporcionaron
    ruta_opc1 = str(validar_carpeta_onedrive(data.directorio_opcional_1)) if data.directorio_opcional_1 else None
    ruta_opc2 = str(validar_carpeta_onedrive(data.directorio_opcional_2)) if data.directorio_opcional_2 else None

    # 3. Guardar o actualizar usuario
    usuario = db.query(Usuario).filter(Usuario.id == data.user_id).first()
    if not usuario:
        usuario = Usuario(id=data.user_id)
        db.add(usuario)

    usuario.nombre = data.nombre.strip()
    usuario.pronombre = data.pronombre
    usuario.nombre_agente = data.nombre_agente.strip() if data.nombre_agente else "Copiloto Técnico"

    # 4. Guardar configuración de directorios y región
    config = db.query(ConfiguracionApp).first()
    if not config:
        config = ConfiguracionApp(id=1)
        db.add(config)

    config.region = data.region
    config.directorio_obligatorio = str(ruta_obligatoria)
    config.directorio_opcional_1 = ruta_opc1
    config.directorio_opcional_2 = ruta_opc2
    config.onboarding_completado = True

    db.commit()
    return {"status": "ok"}


@router.put("/config/directories")
def actualizar_configuracion_directorios(data: ConfigUpdateRequest, db: Session = Depends(get_db)):
    """Actualiza las carpetas desde el panel de ajustes (prohibido dejar 0 carpetas)."""
    ruta_obligatoria = validar_carpeta_onedrive(data.directorio_obligatorio)
    ruta_opc1 = str(validar_carpeta_onedrive(data.directorio_opcional_1)) if data.directorio_opcional_1 else None
    ruta_opc2 = str(validar_carpeta_onedrive(data.directorio_opcional_2)) if data.directorio_opcional_2 else None

    config = db.query(ConfiguracionApp).first()
    if not config:
        config = ConfiguracionApp(id=1)
        db.add(config)

    if data.region:
        config.region = data.region
    config.directorio_obligatorio = str(ruta_obligatoria)
    config.directorio_opcional_1 = ruta_opc1
    config.directorio_opcional_2 = ruta_opc2

    db.commit()
    return {"status": "ok"}


# ==========================================
# ENDPOINTS DE SESIONES Y MENSAJES
# ==========================================
@router.get("/sessions/{user_id}", response_model=List[SessionResponse])
def obtener_sesiones(user_id: str, db: Session = Depends(get_db)):
    sesiones = (
        db.query(SesionChat)
        .filter(SesionChat.usuario_id == user_id)
        .order_by(
            case((SesionChat.fijado == True, 0), else_=1),
            SesionChat.fijado_en.desc(),
            SesionChat.actualizado_en.desc(),
            SesionChat.creado_en.desc()
        )
        .all()
    )
    return [SessionResponse(id=s.id, titulo=s.titulo, fijado=bool(s.fijado)) for s in sesiones]


@router.post("/sessions/{user_id}", response_model=SessionResponse)
def crear_nueva_sesion(user_id: str, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not usuario:
        usuario = Usuario(id=user_id)
        db.add(usuario)
        db.commit()

    ahora = datetime.datetime.utcnow()
    nueva = SesionChat(
        id=str(uuid.uuid4()),
        usuario_id=user_id,
        titulo="Nueva consulta",
        actualizado_en=ahora,
        creado_en=ahora
    )
    db.add(nueva)
    db.commit()
    return SessionResponse(id=nueva.id, titulo=nueva.titulo, fijado=False)


@router.patch("/sessions/{session_id}/pin")
def alternar_fijar_sesion(session_id: str, db: Session = Depends(get_db)):
    sesion = db.query(SesionChat).filter(SesionChat.id == session_id).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    if sesion.fijado:
        sesion.fijado = False
        sesion.fijado_en = None
    else:
        fijados_actuales = (
            db.query(SesionChat)
            .filter(SesionChat.usuario_id == sesion.usuario_id, SesionChat.fijado == True)
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
def renombrar_sesion(session_id: str, data: RenameRequest, db: Session = Depends(get_db)):
    sesion = db.query(SesionChat).filter(SesionChat.id == session_id).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    sesion.titulo = data.titulo.strip()
    db.commit()
    return {"status": "ok", "titulo": sesion.titulo}


@router.delete("/sessions/single/{session_id}")
def eliminar_sesion_individual(session_id: str, db: Session = Depends(get_db)):
    sesion = db.query(SesionChat).filter(SesionChat.id == session_id).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    db.delete(sesion)
    db.commit()
    return {"status": "ok", "id": session_id}


@router.delete("/sessions/{user_id}/clear-all")
def eliminar_todas_las_sesiones(user_id: str, db: Session = Depends(get_db)):
    sesiones = db.query(SesionChat).filter(SesionChat.usuario_id == user_id).all()
    for s in sesiones:
        db.delete(s)
    db.commit()
    return {"status": "ok", "eliminadas": len(sesiones)}


@router.get("/messages/{session_id}", response_model=List[MessageResponse])
def obtener_historial_sesion(session_id: str, db: Session = Depends(get_db)):
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
