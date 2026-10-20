# backend/auth.py
import re
import datetime
import uuid
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from backend.database import get_db, Usuario

# ==========================================
# CONFIGURACIÓN DE SEGURIDAD (JWT)
# ==========================================
SECRET_KEY = "walmart_toreo_secreto_local_super_seguro_para_rag"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 días

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


# ==========================================
# FUNCIONES AUXILIARES (NATIVAS CON BCRYPT)
# ==========================================
def validar_complejidad_password(password: str) -> None:
    if len(password) < 6 or len(password) > 60:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña debe tener entre 6 y 60 caracteres."
        )
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña debe incluir al menos una letra y un número."
        )


def verificar_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except ValueError:
        return False


def obtener_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def crear_token_acceso(data: dict, expires_delta: datetime.timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def obtener_usuario_actual(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    usuario = db.query(Usuario).filter(Usuario.username == username).first()
    if usuario is None:
        raise credentials_exception

    return usuario


# ==========================================
# ENDPOINTS DE LOGIN, REGISTRO Y GESTIÓN
# ==========================================
class RegistroUsuario(BaseModel):
    username: str
    password: str = Field(..., min_length=6, max_length=60)


class CambioPasswordRequest(BaseModel):
    password_anterior: str
    password_nueva: str = Field(..., min_length=6, max_length=60)


@router.post("/registrar", status_code=status.HTTP_201_CREATED)
def registrar_usuario(user_data: RegistroUsuario, db: Session = Depends(get_db)):
    validar_complejidad_password(user_data.password)

    usuario_existente = db.query(Usuario).filter(Usuario.username == user_data.username).first()
    if usuario_existente:
        raise HTTPException(status_code=400, detail="El nombre de usuario ya está en uso")

    nuevo_usuario = Usuario(
        id=str(uuid.uuid4()),
        username=user_data.username,
        password_hash=obtener_password_hash(user_data.password),
        nombre=user_data.username,
        pronombre=None,
        nombre_agente="Copiloto Técnico"
    )
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    return {"mensaje": "Usuario creado exitosamente", "username": nuevo_usuario.username}


@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.username == form_data.username).first()

    if not usuario or not verificar_password(form_data.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = crear_token_acceso(
        data={"sub": usuario.username}, expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "usuario": {
            "id": usuario.id,
            "username": usuario.username,
            "nombre": usuario.nombre
        }
    }


@router.post("/cambiar-password")
def cambiar_password(
    data: CambioPasswordRequest,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db)
):
    if not verificar_password(data.password_anterior, usuario_actual.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña anterior es incorrecta."
        )

    validar_complejidad_password(data.password_nueva)

    if data.password_anterior == data.password_nueva:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva contraseña no puede ser idéntica a la anterior."
        )

    usuario_actual.password_hash = obtener_password_hash(data.password_nueva)
    db.commit()

    return {"mensaje": "Contraseña actualizada exitosamente."}