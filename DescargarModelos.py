# scripts/descargar_modelos.py
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT_DIR / "models_cache"
FASTEMBED_DIR = MODELS_DIR / "fastembed_cache"

MODELS_DIR.mkdir(parents=True, exist_ok=True)
FASTEMBED_DIR.mkdir(parents=True, exist_ok=True)

print(f"Ruta base limpia: {MODELS_DIR}\n")

# 1. BGE-M3
dense_path = MODELS_DIR / "bge-m3"
if not (dense_path / "model.safetensors").exists():
    print("[1/3] Descargando BAAI/bge-m3...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-m3")
    model.save(str(dense_path))
    print(" -> BGE-M3 completado.")
else:
    print("[1/3] BGE-M3 ya existe en disco.")

# Función auxiliar para descargar y descomprimir tar.gz de FastEmbed manualmente
def instalar_modelo_fastembed(nombre_carpeta: str, url_tar: str):
    destino = FASTEMBED_DIR / nombre_carpeta
    if destino.exists() and any(destino.iterdir()):
        print(f" -> {nombre_carpeta} ya existe.")
        return

    destino.mkdir(parents=True, exist_ok=True)
    archivo_tar = FASTEMBED_DIR / f"{nombre_carpeta}.tar.gz"

    print(f"Descargando {nombre_carpeta} desde {url_tar}...")
    urllib.request.urlretrieve(url_tar, archivo_tar)

    print(f"Extrayendo {archivo_tar.name}...")
    with tarfile.open(archivo_tar, "r:gz") as tar:
        tar.extractall(path=destino)

    if archivo_tar.exists():
        archivo_tar.unlink()
    print(f" -> {nombre_carpeta} instalado correctamente.")

# 2. Descarga explícita de BM25
print("\n[2/3] Instalando FastEmbed BM25...")
url_bm25 = "https://storage.googleapis.com/qdrant-fastembed/fast-bm25.tar.gz"
instalar_modelo_fastembed("bm25", url_bm25)

# 3. Descarga explícita de Reranker (bge-reranker-base)
print("\n[3/3] Instalando FastEmbed Reranker...")
url_reranker = "https://storage.googleapis.com/qdrant-fastembed/bge-reranker-base.tar.gz"
instalar_modelo_fastembed("bge-reranker-base", url_reranker)

# 4. Verificación e inferencia offline
print("\nVerificando carga offline de FastEmbed...")
from fastembed import SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

bm25 = SparseTextEmbedding(model_name="Qdrant/bm25", cache_dir=str(FASTEMBED_DIR), local_files_only=True)
list(bm25.embed(["prueba exitosa"]))
print("✓ BM25 operativo 100% offline.")

reranker = TextCrossEncoder(model_name="BAAI/bge-reranker-base", cache_dir=str(FASTEMBED_DIR), local_files_only=True)
list(reranker.rerank("query", ["doc"]))
print("✓ Reranker operativo 100% offline.")

print("\n" + "=" * 50)
print("¡TODOS LOS MODELOS INSTALADOS Y LISTOS!")
print("=" * 50)