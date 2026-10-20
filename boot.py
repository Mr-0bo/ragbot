# boot.py
import sys
import socket
import uvicorn
import io
from contextlib import redirect_stdout


def obtener_ip_lan():
    """Detecta la IP local (LAN) de la máquina host."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def mostrar_banner():
    print("\033[H\033[J", end="")
    banner = r"""
___    __________________________________________________
__ |  / /__  ____/__  __ \__  __/___  _/_  ____/__  ____/
__ | / /__  __/  __  /_/ /_  /   __  / _  /    __  __/   
__ |/ / _  /___  _  _, _/_  /   __/ /  / /___  _  /___   
_____/  /_____/  /_/ |_| /_/    /___/  \____/  /_____/   

    """
    print("\033[96m" + banner + "\033[0m")
    print("\033[1m\033[97m  ========================================================================\033[0m")
    print("\033[1m\033[92m   [ SYSTEM LAUNCHER ] : AGENTE DE BÚSQUEDA 'VÉRTICE' (SERVER EDITION)\033[0m")
    print("\033[1m\033[97m  ========================================================================\033[0m")
    print("   \033[93mDeveloper\033[0m      : Mario García")
    print("   \033[93mVersion\033[0m        : v2.0.0-LAN")
    print("   \033[93mArchitecture\033[0m   : FastAPI Multi-User + Qdrant Vector Engine + JWT Auth")
    print("\033[1m\033[97m  ------------------------------------------------------------------------\033[0m\n")


def iniciar_sistema(app_import_str="main:app", host="0.0.0.0", port=8000):
    """Secuencia de arranque REAL. Carga los módulos en memoria antes de levantar la red."""
    ip_lan = obtener_ip_lan()
    mostrar_banner()

    # IMPORTACIONES REALES (Se hacen aquí para no ralentizar el inicio del script)
    from backend.config import settings
    from backend.database import engine, Base
    from backend.search_service import get_qdrant_client, get_embedding_model

    # 1. Verificar claves de API
    sys.stdout.write("  \033[94m[INIT]\033[0m Verificando variables de entorno y API Keys... ")
    sys.stdout.flush()
    if not settings.GEMINI_API_KEY:
        print("\033[91m[ ERROR ] FALTA GEMINI_API_KEY EN .ENV\033[0m")
        sys.exit(1)
    print("\033[92m[ OK ]\033[0m")

    # 2. Levantar SQLite
    sys.stdout.write("  \033[94m[INIT]\033[0m Estructurando base de datos relacional (SQLite)... ")
    sys.stdout.flush()
    Base.metadata.create_all(bind=engine)
    print("\033[92m[ OK ]\033[0m")

    # 3. Levantar Qdrant Local
    sys.stdout.write("  \033[94m[INIT]\033[0m Iniciando motor vectorial (Qdrant)... ")
    sys.stdout.flush()
    get_qdrant_client()
    print("\033[92m[ OK ]\033[0m")

    # 4. Cargar modelo BGE-M3 (Esta es la carga real que tomará unos segundos)
    sys.stdout.write("  \033[94m[INIT]\033[0m Cargando y alojando modelo BGE-M3 en RAM... ")
    sys.stdout.flush()

    # Silenciamos temporalmente los prints internos del modelo para no romper el diseño de consola
    f = io.StringIO()
    with redirect_stdout(f):
        get_embedding_model()

    print("\033[92m[ OK ]\033[0m")

    # 5. Listo para red
    sys.stdout.write("  \033[94m[INIT]\033[0m Asignando sockets y preparando servidor LAN... ")
    sys.stdout.flush()
    print("\033[92m[ OK ]\033[0m")

    print("\n  \033[97m\033[1m" + ("═" * 72) + "\033[0m")
    print("  \033[92m\033[1m  [✔] SERVIDOR VÉRTICE INICIALIZADO Y ESCUCHANDO CONEXIONES\033[0m")
    print(f"  \033[93m  [i] Entorno Local (Host) : http://127.0.0.1:{port}\033[0m")
    print(f"  \033[96m\033[1m  [★] URL PARA COMPARTIR   : http://{ip_lan}:{port}\033[0m")
    print("  \033[90m  [i] (Mantén esta terminal abierta para procesar las peticiones)\033[0m")
    print("  \033[97m\033[1m" + ("═" * 72) + "\033[0m\n")

    # Arrancamos FastAPI. Al tener workers=1 (por defecto), aprovechará todo lo que ya cargamos en RAM.
    uvicorn.run(app_import_str, host=host, port=port, reload=False, log_level="warning")