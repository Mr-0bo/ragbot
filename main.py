import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import get_base_dir
from backend.routers import user, chat, sync
from boot import iniciar_sistema


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. El servidor arranca y el puerto 8000 abre al instante (< 1 seg)
    # 2. Se lanza el calentamiento de modelos en segundo plano sin congelar la app
    from backend.search_service import precargar_modelos_en_segundo_plano
    hilo_warmup = threading.Thread(
        target=precargar_modelos_en_segundo_plano,
        daemon=True,
        name="WarmupModelosThread"
    )
    hilo_warmup.start()

    yield
    # Código opcional de cierre al apagar la app


app = FastAPI(
    title="Copiloto de Normativas Técnicas",
    description="Asistente local para consulta técnica y normativa",
    version="1.0.0",
    lifespan=lifespan
)

# Resolución de rutas compatible con desarrollo y binarios congelados (PyInstaller)
BASE_DIR = get_base_dir()
FRONTEND_DIR = BASE_DIR / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


@app.get("/")
def home():
    index_path = FRONTEND_DIR / "index.html"
    return FileResponse(str(index_path))


# Registro de routers modulares
app.include_router(user.router)
app.include_router(chat.router)
app.include_router(sync.router)


if __name__ == "__main__":
    # Inicia con la animación de boot, apertura de navegador y servidor
    iniciar_sistema(app_import_str="main:app", host="127.0.0.1", port=8000)