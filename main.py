# main.py
import sys
import inspect
import threading
import multiprocessing
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import get_base_dir, settings
from backend.routers import user, chat, sync
from backend.auth import router as auth_router
from backend.database import SessionLocal, ConfiguracionApp
from boot import iniciar_sistema

# =========================================================
# PARCHES DE COMPATIBILIDAD (MANTENIDOS)
# =========================================================
_original_getsourcelines = inspect.getsourcelines

def _patched_getsourcelines(obj):
    try:
        return _original_getsourcelines(obj)
    except OSError:
        return (["def dummy(): pass\n"], 0)

_original_getsource = inspect.getsource

def _patched_getsource(obj):
    try:
        return _original_getsource(obj)
    except OSError:
        return "def dummy(): pass\n"

inspect.getsourcelines = _patched_getsourcelines
inspect.getsource = _patched_getsource


# =========================================================
# INICIALIZACIÓN AUTOMÁTICA DE LA RUTA DEL REPOSITORIO
# =========================================================
def inicializar_repositorio_central():
    """Garantiza que la ruta del .env quede persistida en la BD al arrancar."""
    if not settings or not settings.DIRECTORIO_DOCUMENTOS:
        return

    db = SessionLocal()
    try:
        config = db.query(ConfiguracionApp).first()
        ruta_env = str(settings.DIRECTORIO_DOCUMENTOS).strip()

        if not config:
            config = ConfiguracionApp(
                id=1,
                directorio_obligatorio=ruta_env,
                region="mexico",
                onboarding_completado=True
            )
            db.add(config)
            db.commit()
            print(f"[BOOT] Repositorio central registrado: {ruta_env}")
        elif not config.directorio_obligatorio or config.directorio_obligatorio != ruta_env:
            config.directorio_obligatorio = ruta_env
            db.commit()
            print(f"[BOOT] Repositorio central sincronizado desde .env: {ruta_env}")
    except Exception as e:
        print(f"[BOOT WARN] Error al inicializar repositorio central en BD: {e}")
        db.rollback()
    finally:
        db.close()


def indexar_repositorio_en_segundo_plano():
    """Escanea e indexa automáticamente los documentos del repositorio al iniciar el servidor."""
    from backend.routers.sync import recopilar_archivos_pdf, procesar_e_indexar_pdf

    db = SessionLocal()
    try:
        config = db.query(ConfiguracionApp).first()
        if not config or not config.directorio_obligatorio:
            return

        archivos = recopilar_archivos_pdf([config.directorio_obligatorio])
        print(f"\n[AUTO-SYNC] Verificando {len(archivos)} documentos en '{config.directorio_obligatorio}'...")

        for archivo in archivos:
            try:
                res = procesar_e_indexar_pdf(archivo, region=config.region or "mexico", db=db)
                if not res.get("omitido"):
                    print(f"[AUTO-SYNC] ✅ Indexado: {res['nombre']} ({res['chunks']} chunks en {res['tiempo_total_s']}s)")
                else:
                    print(f"[AUTO-SYNC] ⏭️ Omitido (sin cambios): {res['nombre']}")
            except Exception as e:
                print(f"[AUTO-SYNC ERROR] Falló {archivo.name}: {e}")

        print("[AUTO-SYNC] Revisión e indexación de repositorio completada con éxito.\n")
    except Exception as e:
        print(f"[AUTO-SYNC WARN] Error durante la sincronización de fondo: {e}")
    finally:
        db.close()


# =========================================================
# LIFESPAN & SERVIDOR
# =========================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Asegurar la ruta del .env en la base de datos SQLite
    inicializar_repositorio_central()

    # 2. Precarga de modelos híbridos y reranker en segundo plano
    from backend.search_service import precargar_modelos_en_segundo_plano
    hilo_warmup = threading.Thread(
        target=precargar_modelos_en_segundo_plano,
        daemon=True,
        name="WarmupModelosThread"
    )
    hilo_warmup.start()

    # 3. Indexación automática en segundo plano sin bloquear el arranque web
    hilo_sync = threading.Thread(
        target=indexar_repositorio_en_segundo_plano,
        daemon=True,
        name="AutoSyncThread"
    )
    hilo_sync.start()

    yield

app = FastAPI(
    title="Copiloto de Normativas Técnicas LAN",
    description="Servidor centralizado para consulta técnica y normativa corporativa",
    version="2.0.0",
    lifespan=lifespan
)

BASE_DIR = get_base_dir()
FRONTEND_DIR = BASE_DIR / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")

@app.get("/")
def home():
    index_path = FRONTEND_DIR / "index.html"
    return FileResponse(str(index_path))

# Registrar los enrutadores (APIs)
app.include_router(auth_router)
app.include_router(user.router)
app.include_router(chat.router)
app.include_router(sync.router)

if __name__ == "__main__":
    multiprocessing.freeze_support()
    iniciar_sistema(app_import_str=app, host="0.0.0.0", port=8000)