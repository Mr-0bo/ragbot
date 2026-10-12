# build_app.py
import os
import platform
import shutil
import PyInstaller.__main__


def limpiar_directorios():
    """Limpia compilaciones anteriores para evitar conflictos."""
    for carpeta in ['build', 'dist']:
        if os.path.exists(carpeta):
            print(f"[*] Eliminando carpeta {carpeta} antigua...")
            shutil.rmtree(carpeta)


def compilar_proyecto():
    sistema = platform.system()
    print(f"[*] Preparando compilación para: {sistema}")

    # En PyInstaller, Windows usa ';' para separar origen de destino, y Mac/Linux usan ':'
    sep = ';' if sistema == 'Windows' else ':'

    # --- 1. CONFIGURACIÓN BÁSICA ---
    # Asumo que main.py es tu arrancador (donde está uvicorn.run).
    # Si usas boot.py para arrancar, cámbialo aquí.
    entry_point = "main.py"
    nombre_app = "CopilotoRAG"

    args = [
        entry_point,
        f'--name={nombre_app}',
        '--onedir',  # Crea una carpeta con el ejecutable y librerías (arranque rápido)
        '--noconfirm',  # Sobrescribir salidas previas sin preguntar
        '--clean'  # Limpiar caché de PyInstaller
    ]

    # --- 2. ARCHIVOS ESTÁTICOS Y MODELOS ---
    # Aquí metemos las carpetas que vimos en tu estructura directamente a la app
    datos_extra = [
        f"frontend{sep}frontend",
        f"modelos_locales{sep}modelos_locales",
        f".env{sep}."
    ]

    for data in datos_extra:
        args.append(f'--add-data={data}')

    # --- 3. IMPORTACIONES OCULTAS ---
    # FastAPI, Uvicorn, PyTorch y el SDK de Google usan importaciones dinámicas
    # que el compilador no detecta automáticamente. Las forzamos aquí.
    hidden_imports = [
        'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
        'FlagEmbedding', 'torch', 'pymupdf', 'qdrant_client', 'sqlalchemy',
        'google.genai', 'pydantic', 'numpy'
    ]

    for imp in hidden_imports:
        args.append(f'--hidden-import={imp}')

    # --- 4. EXCLUSIONES ---
    # Evitamos que se empaqueten librerías gráficas pesadas que no usamos
    excludes = ['matplotlib', 'PyQt5', 'PyQt6']
    for exc in excludes:
        args.append(f'--exclude-module={exc}')

    # --- 5. EJECUCIÓN ---
    print("\n[*] Ejecutando PyInstaller, esto puede tomar unos minutos...")
    PyInstaller.__main__.run(args)
    print(f"\n[+] ¡Compilación exitosa! Revisa la carpeta 'dist/{nombre_app}'")


if __name__ == "__main__":
    limpiar_directorios()
    compilar_proyecto()