# backend/routers/sync.py
import gc
import json
import hashlib
import uuid
import sys
import time
from pathlib import Path
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from qdrant_client.http import models

from backend.database import get_db, SessionLocal, ConfiguracionApp, DocumentoNormativo
from backend.auth import obtener_usuario_actual
from backend.config import settings

router = APIRouter(prefix="/api/sync", tags=["Sincronización"])


def recopilar_archivos_pdf(carpetas: List[str]) -> List[Path]:
    pdfs = []
    for c in carpetas:
        if not c:
            continue
        p = Path(c).resolve()
        if p.exists() and p.is_dir():
            for archivo in p.rglob("*.pdf"):
                if not archivo.name.startswith("._") and archivo.is_file():
                    pdfs.append(archivo)
    return pdfs


def calcular_hash_archivo(ruta: Path) -> str:
    hasher = hashlib.md5()
    with open(ruta, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def obtener_directorios_activos(config: ConfiguracionApp) -> List[str]:
    """Retorna los directorios de la BD con fallback a la ruta de settings.DIRECTORIO_DOCUMENTOS."""
    dir_principal = (config.directorio_obligatorio if config and config.directorio_obligatorio else None) or (settings.DIRECTORIO_DOCUMENTOS if settings else None)
    directorios = [dir_principal]
    if config:
        if config.directorio_opcional_1:
            directorios.append(config.directorio_opcional_1)
        if config.directorio_opcional_2:
            directorios.append(config.directorio_opcional_2)
    return [d for d in directorios if d]


@router.get("/check")
def verificar_cambios_pendientes(
    db: Session = Depends(get_db),
    usuario_actual = Depends(obtener_usuario_actual)
):
    config = db.query(ConfiguracionApp).first()
    directorios = obtener_directorios_activos(config)

    if not directorios:
        return {"requiere_sincronizacion": False, "total_pendientes": 0}

    archivos_disco = recopilar_archivos_pdf(directorios)
    registrados = {doc.ruta_absoluta: doc for doc in db.query(DocumentoNormativo).all()}

    nuevos = 0
    modificados = 0

    for f in archivos_disco:
        ruta_str = str(f.resolve())
        if ruta_str not in registrados:
            nuevos += 1
        else:
            try:
                if f.stat().st_mtime > (registrados[ruta_str].mtime or 0):
                    modificados += 1
            except Exception:
                pass

    eliminados = max(0, len(registrados) - len(archivos_disco))
    total = nuevos + modificados + eliminados

    return {
        "requiere_sincronizacion": total > 0,
        "total_pendientes": total,
        "nuevos": nuevos,
        "modificados": modificados,
        "eliminados": eliminados
    }


def procesar_e_indexar_pdf(archivo: Path, region: str, db: Session) -> Dict[str, Any]:
    import torch
    from backend.search_service import (
        get_embedding_model,
        indexar_chunks_documento,
        eliminar_documento_por_ruta,
        formatear_vector_disperso
    )
    from ingestion.document_parser import extraer_markdown_de_pdf
    from ingestion.ingest_docs import limpiar_texto, dividir_en_chunks

    t_inicio_total = time.perf_counter()
    ruta_abs = str(archivo.resolve())
    nombre = archivo.name
    hash_actual = calcular_hash_archivo(archivo)
    stat = archivo.stat()

    doc_db = db.query(DocumentoNormativo).filter(DocumentoNormativo.ruta_absoluta == ruta_abs).first()

    if doc_db and doc_db.hash_md5 == hash_actual and doc_db.esta_indexado:
        print(f"[DEBUGGER] ⏭️ Omitiendo '{nombre}' (Sin cambios)")
        return {"omitido": True, "nombre": nombre}

    t0_parse = time.perf_counter()
    paginas = extraer_markdown_de_pdf(archivo, verbose=True)
    t_parse = time.perf_counter() - t0_parse
    total_paginas = len(paginas)

    t0_chunk = time.perf_counter()
    textos_chunk = []
    metadatos_chunk = []
    chunk_index = 0

    for item in paginas:
        num_pag = item["pagina"]
        texto_limpio = limpiar_texto(item["texto"])
        chunks = dividir_en_chunks(texto_limpio, chunk_size=1200, overlap=200)

        for sub_idx, chunk in enumerate(chunks):
            if len(chunk) < 20:
                continue

            chunk_index += 1
            textos_chunk.append(chunk)
            metadatos_chunk.append({
                "pagina": num_pag,
                "sub_idx": sub_idx,
                "caracteres": len(chunk),
                "texto": chunk
            })

    t_chunk = time.perf_counter() - t0_chunk

    print(f"\n[DEBUGGER CHUNKS] ✂️ '{nombre}': {len(textos_chunk)} fragmentos creados.")

    t_vectorizacion = 0.0
    t_qdrant = 0.0

    if textos_chunk:
        modelo = get_embedding_model()
        eliminar_documento_por_ruta(ruta_abs)

        lote_size = 12
        puntos_qdrant = []

        print(f"\n[DEBUGGER INFERENCIA] 🧠 Vectorizando {len(textos_chunk)} chunks con BGE-M3 (Dense + Sparse)...")

        for b in range(0, len(textos_chunk), lote_size):
            sub_lote = textos_chunk[b: b + lote_size]

            t0_v = time.perf_counter()
            salida = modelo.encode(
                sub_lote,
                batch_size=len(sub_lote),
                max_length=512,
                return_dense=True,
                return_sparse=True
            )
            t_vectorizacion += (time.perf_counter() - t0_v)

            v_densos = salida["dense_vecs"]
            v_dispersos = salida["lexical_weights"]

            for sub_i, meta_idx in enumerate(range(b, b + len(sub_lote))):
                meta = metadatos_chunk[meta_idx]
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{ruta_abs}_{meta['pagina']}_{meta['sub_idx']}"))

                vector_payload = {
                    "dense": v_densos[sub_i].tolist(),
                    "sparse": formatear_vector_disperso(v_dispersos[sub_i])
                }

                puntos_qdrant.append(
                    models.PointStruct(
                        id=point_id,
                        vector=vector_payload,
                        payload={
                            "documento": nombre,
                            "ruta_relativa": ruta_abs,
                            "ruta_absoluta": ruta_abs,
                            "pagina": meta["pagina"],
                            "contenido": meta["texto"],
                            "region": region.lower()
                        }
                    )
                )

        t0_qdrant = time.perf_counter()
        indexar_chunks_documento(puntos_qdrant)
        t_qdrant = time.perf_counter() - t0_qdrant

        del salida, puntos_qdrant
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif sys.platform == "darwin" and torch.backends.mps.is_available():
            torch.mps.empty_cache()
        gc.collect()

    if not doc_db:
        doc_db = DocumentoNormativo(
            id=str(uuid.uuid4()),
            ruta_absoluta=ruta_abs,
            nombre_archivo=nombre,
            ruta_relativa=ruta_abs,
            region=region.lower()
        )
        db.add(doc_db)

    doc_db.hash_md5 = hash_actual
    doc_db.mtime = stat.st_mtime
    doc_db.tamanio_bytes = stat.st_size
    doc_db.total_paginas = total_paginas
    doc_db.total_chunks = chunk_index
    doc_db.esta_indexado = True
    db.commit()

    duracion_total = time.perf_counter() - t_inicio_total

    print(f"⏱️ TIEMPO TOTAL: {duracion_total:.2f} s (Inferencia Híbrida: {t_vectorizacion:.2f} s)")

    return {
        "omitido": False,
        "nombre": nombre,
        "paginas": total_paginas,
        "chunks": chunk_index,
        "tiempo_total_s": round(duracion_total, 2),
        "tiempo_parse_s": round(t_parse, 2),
        "tiempo_chunk_ms": round(t_chunk * 1000, 2),
        "tiempo_vector_s": round(t_vectorizacion, 2),
        "tiempo_qdrant_s": round(t_qdrant, 2)
    }


def generador_indexacion_sse():
    db = SessionLocal()
    try:
        config = db.query(ConfiguracionApp).first()
        directorios = obtener_directorios_activos(config)

        if not directorios:
            yield f"data: {json.dumps({'tipo': 'error', 'mensaje': 'No hay directorios configurados ni en BD ni en .env.'})}\n\n"
            return

        archivos = recopilar_archivos_pdf(directorios)
        total = len(archivos)

        if total == 0:
            yield f"data: {json.dumps({'tipo': 'progreso', 'progreso': 100, 'archivo': 'Sin PDFs', 'mensaje': 'No se encontraron PDFs en las carpetas.'})}\n\n"
            yield f"data: {json.dumps({'tipo': 'fin'})}\n\n"
            return

        for i, archivo in enumerate(archivos, 1):
            nombre = archivo.name
            porcentaje = int((i / total) * 100)

            yield f"data: {json.dumps({'tipo': 'progreso', 'progreso': porcentaje, 'archivo': nombre, 'mensaje': f'Procesando {i} de {total}'})}\n\n"

            try:
                region_activa = config.region if config and config.region else "mexico"
                metricas = procesar_e_indexar_pdf(archivo, region=region_activa, db=db)
                yield f"data: {json.dumps({'tipo': 'telemetria', 'datos': metricas})}\n\n"
            except Exception as e:
                print(f"[WARN INDEX] Error al indexar {nombre}: {e}")
                yield f"data: {json.dumps({'tipo': 'error_archivo', 'archivo': nombre, 'error': str(e)})}\n\n"

        yield f"data: {json.dumps({'tipo': 'fin'})}\n\n"

    except Exception as e:
        print(f"[ERROR SSE] {e}")
        yield f"data: {json.dumps({'tipo': 'error', 'mensaje': str(e)})}\n\n"
    finally:
        db.close()


@router.get("/stream")
def stream_indexacion(usuario_actual = Depends(obtener_usuario_actual)):
    return StreamingResponse(
        generador_indexacion_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )