# descargar_definitivo.py
from pathlib import Path
from huggingface_hub import snapshot_download

ROOT_DIR = Path(__file__).resolve().parent
MODELS_DIR = ROOT_DIR / "models_cache"
FASTEMBED_DIR = MODELS_DIR / "fastembed_cache"

MODELS_DIR.mkdir(parents=True, exist_ok=True)
FASTEMBED_DIR.mkdir(parents=True, exist_ok=True)

print("1. Descargando repositorio BM25 desde Hugging Face...")
# FastEmbed usa la caché estándar de huggingface dentro de su cache_dir
ruta_bm25 = snapshot_download(
    repo_id="Qdrant/bm25",
    cache_dir=str(FASTEMBED_DIR),
    local_dir_use_symlinks=False
)
print(f" -> Guardado en: {ruta_bm25}")

print("\n2. Descargando repositorio Reranker desde Hugging Face...")
ruta_reranker = snapshot_download(
    repo_id="BAAI/bge-reranker-base",
    cache_dir=str(FASTEMBED_DIR),
    local_dir_use_symlinks=False
)
print(f" -> Guardado en: {ruta_reranker}")

print("\n3. Descargando BGE-M3 denso...")
ruta_dense = MODELS_DIR / "bge-m3"
if not (ruta_dense / "model.safetensors").exists():
    snapshot_download(
        repo_id="BAAI/bge-m3",
        local_dir=str(ruta_dense),
        local_dir_use_symlinks=False
    )
print(f" -> Guardado en: {ruta_dense}")

print("\n--- PROBANDO INICIALIZACIÓN CON FASTEMBED ---")
from fastembed import SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

# Probamos cargarlos pasándoles la carpeta
bm25 = SparseTextEmbedding("Qdrant/bm25", cache_dir=str(FASTEMBED_DIR), local_files_only=True)
res_bm25 = list(bm25.embed(["Hola mundo"]))
print("✓ BM25 cargó y generó vector con éxito.")

reranker = TextCrossEncoder("BAAI/bge-reranker-base", cache_dir=str(FASTEMBED_DIR), local_files_only=True)
res_rerank = list(reranker.rerank("pregunta", ["documento de prueba"]))
print("✓ Reranker cargó y evaluó con éxito.")

print("\n¡TODO CONFIGURADO Y FUNCIONANDO EN LOCAL!")