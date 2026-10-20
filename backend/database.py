# backend/database.py
import datetime
from sqlalchemy import create_engine, Column, String, Text, DateTime, ForeignKey, Boolean, Integer, Float
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from backend.config import settings

# Conexión usando la ruta segura
engine = create_engine(
    settings.sqlite_url if settings else "sqlite:///./normativas_chat.db",
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ==========================================
# GESTIÓN DE CONFIGURACIÓN Y ONBOARDING
# ==========================================
class ConfiguracionApp(Base):
    __tablename__ = "configuracion_app"

    id = Column(Integer, primary_key=True, default=1)
    region = Column(String, default="mexico")  # "mexico" o "centroamerica"
    directorio_obligatorio = Column(String, nullable=True)
    directorio_opcional_1 = Column(String, nullable=True)
    directorio_opcional_2 = Column(String, nullable=True)
    onboarding_completado = Column(Boolean, default=False)
    actualizado_en = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


# ==========================================
# MANIFIESTO DE CONTROL INCREMENTAL (HASHES)
# ==========================================
class DocumentoNormativo(Base):
    __tablename__ = "documentos_normativos"

    id = Column(String, primary_key=True, index=True)  # Hash MD5 o ID único
    nombre_archivo = Column(String, index=True)
    ruta_absoluta = Column(String, unique=True, index=True)
    ruta_relativa = Column(String, index=True)
    region = Column(String, index=True)  # "mexico" | "centroamerica"
    hash_md5 = Column(String, index=True)
    tamanio_bytes = Column(Integer)
    mtime = Column(Float)
    total_paginas = Column(Integer, default=0)
    total_chunks = Column(Integer, default=0)
    esta_indexado = Column(Boolean, default=False)
    ultimo_escaneo = Column(DateTime, default=datetime.datetime.utcnow)


# ==========================================
# MODELOS DE CHAT Y USUARIO (MULTI-USUARIO)
# ==========================================
class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(String, primary_key=True, index=True)

    # NUEVOS CAMPOS PARA AUTENTICACIÓN
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)

    # Preferencias y personalización
    nombre = Column(String, nullable=True)
    pronombre = Column(String, nullable=True)
    nombre_agente = Column(String, default="Asistente Técnico")
    disclaimer_aceptado = Column(Boolean, default=False)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow)

    sesiones = relationship("SesionChat", back_populates="usuario")


class SesionChat(Base):
    __tablename__ = "sesiones_chat"
    id = Column(String, primary_key=True, index=True)
    usuario_id = Column(String, ForeignKey("usuarios.id"))
    titulo = Column(String, default="Nueva consulta")
    fijado = Column(Boolean, default=False)
    fijado_en = Column(DateTime, nullable=True)
    actualizado_en = Column(DateTime, default=datetime.datetime.utcnow)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow)

    usuario = relationship("Usuario", back_populates="sesiones")
    mensajes = relationship("Mensaje", back_populates="sesion", cascade="all, delete-orphan")


class Mensaje(Base):
    __tablename__ = "mensajes"
    id = Column(String, primary_key=True, index=True)
    sesion_id = Column(String, ForeignKey("sesiones_chat.id"))
    rol = Column(String)
    contenido = Column(Text)
    fuentes = Column(Text, nullable=True)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow)

    sesion = relationship("SesionChat", back_populates="mensajes")


def get_db():
    """Generador de sesiones para inyección de dependencias en FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Crear las tablas automáticamente
Base.metadata.create_all(bind=engine)