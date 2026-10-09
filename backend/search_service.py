# backend/search_service.py
import os
import sys
import threading
from typing import List, Dict, Optional, Union
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.http import models
from FlagEmbedding import BGEM3FlagModel
from backend.config import settings

DIMENSION_BGE_M3 = 1024

_lock_modelos = threading.Lock()

_qdrant_client: Optional[QdrantClient] = None
_bge_m3_model: Optional[BGEM3FlagModel] = None


def get_embedding_model() -> BGEM3FlagModel:
    """Carga BAAI/bge-m3 con FlagEmbedding para soporte simultáneo Dense + Sparse."""
    global _bge_m3_model
    with _lock_modelos:
        if _bge_m3_model is None:
            import torch

            if torch.cuda.is_available():
                dispositivo = "cuda"
            elif sys.platform == "darwin" and torch.backends.mps.is_available():
                dispositivo = "mps"
            else:
                dispositivo = "cpu"

            ruta_local = Path(settings.dense_model_path)
            modelo_origen = str(ruta_local) if (ruta_local.exists() and any(ruta_local.iterdir())) else settings.EMBEDDING_MODEL_NAME

            print(f"[INFO EMBEDDINGS] Inicializando BGE-M3 (Dense + Sparse nativo) en: {dispositivo.upper()}")

            _bge_m3_model = BGEM3FlagModel(
                modelo_origen,
                use_fp16=(dispositivo in ["cuda", "mps"]),
                device=dispositivo
            )
    return _bge_m3_model


# Funciones señuelo para evitar errores si algún archivo antiguo intenta importarlas
def get_sparse_model():
    return None

def get_reranker_model():
    return None


def get_qdrant_client() -> QdrantClient:
    """Inicializa la base de datos vectorial local."""
    global _qdrant_client
    with _lock_modelos:
        if _qdrant_client is None:
            _qdrant_client = QdrantClient(path=str(settings.qdrant_path))
            _inicializar_coleccion(_qdrant_client)
    return _qdrant_client


def _inicializar_coleccion(client: QdrantClient):
    """Crea la colección híbrida: Dense BGE-M3 (1024) + Sparse Lexical BGE-M3."""
    if not client.collection_exists(settings.QDRANT_COLLECTION_NAME):
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            vectors_config={
                "dense": models.VectorParams(
                    size=DIMENSION_BGE_M3,
                    distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(
                        on_disk=False,
                    )
                )
            }
        )


def buscar_fragmentos(
        consultas: Union[str, List[str]],
        consulta_referencia: Optional[str] = None,
        region: str = "mexico",
        top_k: int = 6,
        recall_k: int = 12,
        max_por_doc: int = 3,
        max_por_pagina: int = 2
) -> List[Dict]:
    """Búsqueda Híbrida nativa: Dense + Sparse (Lexical) de BGE-M3 fusionados con RRF."""
    try:
        client = get_qdrant_client()
        modelo = get_embedding_model()

        if isinstance(consultas, str):
            lista_consultas = [consultas]
        else:
            lista_consultas = consultas if consultas else [""]

        subconsultas_validas = [q.strip() for q in lista_consultas if q.strip()]
        if not subconsultas_validas:
            return []

        filtro_region = models.Filter(
            must=[
                models.FieldCondition(
                    key="region",
                    match=models.MatchValue(value=region.lower())
                )
            ]
        )

        prefetches: List[models.Prefetch] = []

        for sub_query in subconsultas_validas:
            salida = modelo.encode([sub_query], return_dense=True, return_sparse=True)
            v_denso = salida["dense_vecs"][0].tolist()
            lexical_dict = salida["lexical_weights"][0]

            indices_sparse = [int(k) for k in lexical_dict.keys()]
            values_sparse = [float(v) for v in lexical_dict.values()]

            prefetches.append(
                models.Prefetch(
                    query=v_denso,
                    using="dense",
                    limit=recall_k * 2,
                    filter=filtro_region
                )
            )
            if indices_sparse:
                prefetches.append(
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=indices_sparse,
                            values=values_sparse
                        ),
                        using="sparse",
                        limit=recall_k * 2,
                        filter=filtro_region
                    )
                )

        respuesta = client.query_points(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            prefetch=prefetches,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=filtro_region,
            limit=top_k * 3,
            with_payload=True
        )

        puntos_fusionados = respuesta.points or []
        if not puntos_fusionados:
            return []

        candidatos_finales = []
        conteo_doc: Dict[str, int] = {}
        conteo_pag: Dict[str, int] = {}
        ids_vistos = set()

        for p in puntos_fusionados:
            if p.id in ids_vistos:
                continue

            pl = p.payload or {}
            doc = str(pl.get("documento", "Desconocido"))
            pag = str(pl.get("pagina", "N/A"))
            clave_pag = f"{doc}_{pag}"

            if conteo_pag.get(clave_pag, 0) >= max_por_pagina:
                continue
            if conteo_doc.get(doc, 0) >= max_por_doc:
                continue

            ids_vistos.add(p.id)
            conteo_pag[clave_pag] = conteo_pag.get(clave_pag, 0) + 1
            conteo_doc[doc] = conteo_doc.get(doc, 0) + 1

            candidatos_finales.append({
                "documento": doc,
                "ruta_relativa": pl.get("ruta_relativa", ""),
                "pagina": pl.get("pagina", "N/A"),
                "contenido": pl.get("contenido", ""),
                "region": pl.get("region", region),
                "score": float(p.score)
            })

            if len(candidatos_finales) >= top_k:
                break

        return candidatos_finales

    except Exception as e:
        print(f"[ERROR BÚSQUEDA QDRANT HÍBRIDA BGE-M3] {e}")
        return []


def eliminar_documento_por_ruta(ruta_relativa: str):
    client = get_qdrant_client()
    client.delete(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="ruta_relativa",
                        match=models.MatchValue(value=ruta_relativa)
                    )
                ]
            )
        )
    )


def indexar_chunks_documento(puntos: List[models.PointStruct]):
    if not puntos:
        return
    client = get_qdrant_client()
    client.upsert(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        points=puntos
    )


def precargar_modelos_en_segundo_plano():
    try:
        print("\n[WARM-UP] Iniciando precarga silenciosa de BGE-M3 (Dense + Sparse)...")
        get_embedding_model()
        get_qdrant_client()
        print("[WARM-UP] BGE-M3 precargado exitosamente en RAM. Listo para inferencia híbrida.\n")
    except Exception as e:
        print(f"[WARM-UP WARN] Error en precarga: {e}")