# scripts/descargar_modelos.py
import os
import sys
from pathlib import Path

# 1. Asegurar acceso a internet limpiando variables restrictivas
for var in ["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"]:
    if var in os.environ:
        del os.environ[var]

# 2. Definir ruta absoluta dentro del proyecto
ROOT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT_DIR / "models_cache"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

print(f"Directorio de destino: {MODELS_DIR}\n")

# --- PASO 1: Descargar BGE-M3 (SentenceTransformers) ---
print("[1/3] Descargando BAAI/bge-m3...")
from sentence_transformers import SentenceTransformer

dense_path = MODELS_DIR / "bge-m3"
# Descargar pesos completos
model = SentenceTransformer("BAAI/bge-m3")
# Guardarlos físicamente en la carpeta del proyecto
model.save(str(dense_path))
print(f" -> BGE-M3 guardado en: {dense_path}")

# --- PASO 2: Descargar FastEmbed BM25 ---
print("\n[2/3] Descargando FastEmbed BM25 (Qdrant/bm25)...")
from fastembed import SparseTextEmbedding

fastembed_dir = str(MODELS_DIR / "fastembed_cache")
bm25_model = SparseTextEmbedding(model_name="Qdrant/bm25", cache_dir=fastembed_dir)
# Forzar descarga ejecutando un embedding de prueba
list(bm25_model.embed(["inicializar"]))
print(f" -> BM25 descargado y extraído en: {fastembed_dir}")

# --- PASO 3: Descargar FastEmbed Reranker ---
print("\n[3/3] Descargando FastEmbed Reranker (BAAI/bge-reranker-base)...")
from fastembed.rerank.cross_encoder import TextCrossEncoder

reranker_model = TextCrossEncoder(model_name="BAAI/bge-reranker-base", cache_dir=fastembed_dir)
# Forzar descarga ejecutando un rerank de prueba
list(reranker_model.rerank("consulta", ["documento"]))
print(f" -> Reranker descargado y extraído en: {fastembed_dir}")

print("\n" + "=" * 50)
print("¡TODOS LOS MODELOS DESCARGADOS CON ÉXITO!")
print("=" * 50)

# Verificación de archivos presentes
print("\nArchivos creados:")
for root, dirs, files in os.walk(MODELS_DIR):
    nivel = root.replace(str(MODELS_DIR), '').count(os.sep)
    indent = ' ' * 4 * nivel
    print(f"{indent}{os.path.basename(root)}/")
    subindent = ' ' * 4 * (nivel + 1)
    for f in files:
        ruta_archivo = Path(root) / f
        tam_mb = ruta_archivo.stat().st_size / (1024 * 1024)
        print(f"{subindent}{f} ({tam_mb:.1f} MB)")