from huggingface_hub import snapshot_download
import os

# Creamos una carpeta física en tu proyecto
os.makedirs("modelos_locales/bge-m3", exist_ok=True)

print("Descargando modelo para empaquetado offline...")
snapshot_download(
    repo_id="BAAI/bge-m3",
    local_dir="./modelos_locales/bge-m3",
    local_dir_use_symlinks=False # Obliga a descargar los archivos reales
)
print("¡Listo! El modelo ya vive en tu proyecto.")