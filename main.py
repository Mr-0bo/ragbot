import sys

# =========================================================
# INTERCEPTOR DE DIÁLOGOS (El que SÍ funcionaba)
# =========================================================
if "--tk-dir" in sys.argv:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    p = filedialog.askdirectory(title='Selecciona la carpeta de normativas')
    print(p if p else '')
    sys.exit(0)

if "--tk-file" in sys.argv:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    p = filedialog.askopenfilename(title='Selecciona el chat a importar',
                                   filetypes=[('Archivos JSON', '*.json'), ('Todos los archivos', '*.*')])
    print(p if p else '')
    sys.exit(0)

import inspect

# Parche estricto para evitar el crasheo de transformers/FlagEmbedding
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

import threading
import multiprocessing
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import get_base_dir
from backend.routers import user, chat, sync
from boot import iniciar_sistema


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.search_service import precargar_modelos_en_segundo_plano
    hilo_warmup = threading.Thread(
        target=precargar_modelos_en_segundo_plano,
        daemon=True,
        name="WarmupModelosThread"
    )
    hilo_warmup.start()
    yield


app = FastAPI(
    title="Copiloto de Normativas Técnicas",
    description="Asistente local para consulta técnica y normativa",
    version="1.0.0",
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


app.include_router(user.router)
app.include_router(chat.router)
app.include_router(sync.router)

if __name__ == "__main__":
    # ESTO EVITA LA BOMBA DE CLONACIÓN
    multiprocessing.freeze_support()

    iniciar_sistema(app_import_str=app, host="127.0.0.1", port=8000)