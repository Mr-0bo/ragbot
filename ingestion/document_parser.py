# ingestion/document_parser.py
import gc
import time
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Union
import fitz  # PyMuPDF

_ocr_engine = None

# Umbral máximo de caracteres por página para prevenir desbordamientos por objetos corruptos
MAX_CHARS_POR_PAGINA = 50000


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from paddleocr import PaddleOCR
            try:
                _ocr_engine = PaddleOCR(lang="es")
            except Exception:
                _ocr_engine = PaddleOCR(use_angle_cls=False, lang="es")
        except Exception as e:
            print(f"[WARN] No se pudo inicializar PaddleOCR: {e}", flush=True)
            _ocr_engine = False
    return _ocr_engine


def _extraer_tablas_pagina(page) -> str:
    """Extrae tablas de la página usando la detección nativa de PyMuPDF con control de fallos."""
    markdown_tablas = []
    try:
        tabs = page.find_tables()
        for tab in tabs:
            df = tab.extract()
            if not df or len(df) < 2:
                continue

            headers = [str(c or "").strip().replace("\n", " ") for c in df[0]]
            filas = []
            for row in df[1:]:
                fila_limpia = [str(c or "").strip().replace("\n", " ") for c in row]
                filas.append(f"| {' | '.join(fila_limpia)} |")

            separador = f"| {' | '.join(['---'] * len(headers))} |"
            tabla_md = f"| {' | '.join(headers)} |\n{separador}\n" + "\n".join(filas)
            markdown_tablas.append(tabla_md)
    except Exception:
        pass

    resultado = "\n\n".join(markdown_tablas)
    return resultado[:MAX_CHARS_POR_PAGINA] if len(resultado) > MAX_CHARS_POR_PAGINA else resultado


def _ejecutar_ocr_pagina(page) -> str:
    """Renderiza a 150 DPI y ejecuta PaddleOCR de manera segura."""
    ocr = _get_ocr_engine()
    if not ocr:
        return ""

    pix = None
    img_bytes = None
    try:
        rect = page.rect
        if rect.width > 2500 or rect.height > 2500:
            print(f"  [WARN OCR] Pág. {page.number + 1} excede tamaño estándar ({rect.width:.0f}x{rect.height:.0f}). Se omite OCR pesado.", flush=True)
            return ""

        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        resultado = ocr.ocr(img_bytes)

        lineas_texto = []
        if resultado and resultado[0]:
            for linea in resultado[0]:
                lineas_texto.append(linea[1][0])

        texto_ocr = "\n".join(lineas_texto)
        return texto_ocr[:MAX_CHARS_POR_PAGINA]
    except Exception as e:
        print(f"  [ERROR OCR] Falló OCR en pág. {page.number + 1}: {e}", flush=True)
        return ""
    finally:
        del pix
        del img_bytes


def extraer_markdown_de_pdf(ruta_pdf: Union[str, Path], verbose: bool = True) -> List[Dict]:
    """
    Extrae contenido página por página reportando métricas de rendimiento y blindado contra páginas corruptas.
    """
    ruta = Path(ruta_pdf)
    if not ruta.exists():
        raise FileNotFoundError(f"El archivo {ruta} no existe.")

    documento_paginas = []
    t_inicio_doc = time.perf_counter()

    doc = None
    try:
        doc = fitz.open(ruta)
        total_pags = len(doc)
        if verbose:
            print(f"\n[DEBUGGER PARSER] 📄 Abriendo '{ruta.name}' ({total_pags} págs)", flush=True)

        for idx_pagina in range(total_pags):
            t_inicio_pag = time.perf_counter()
            numero_pagina = idx_pagina + 1
            metodo = "nativo"
            texto_final = ""

            # INTERCEPTOR: Evita el crash nativo (0xC0000005) antes de invocar MuPDF en C
            if "cdp-010 ambiental" in ruta.name.lower() and numero_pagina == 15:
                if verbose:
                    print(f"  ├─ [OMITIDA POR SEGFAULT] Pág {numero_pagina:02d}/{total_pags:02d} saltada por corrupción interna en PDF.", flush=True)
                continue

            try:
                page = doc.load_page(idx_pagina)
            except Exception as e:
                print(f"  ├─ [ERROR FATAL PÁG] Pág {numero_pagina:02d}/{total_pags:02d} no pudo cargarse en memoria: {e}. Saltando...", flush=True)
                continue

            try:
                # 1. Extracción nativa de texto plano
                texto_nativo = ""
                try:
                    texto_nativo = page.get_text("text").strip()
                    if len(texto_nativo) > MAX_CHARS_POR_PAGINA:
                        texto_nativo = texto_nativo[:MAX_CHARS_POR_PAGINA]
                except Exception as e_text:
                    print(f"  [WARN] Falló lectura de texto nativo en pág {numero_pagina}: {e_text}", flush=True)

                # 2. Extracción de tablas
                tablas_md = _extraer_tablas_pagina(page)

                contenido_pagina = []
                if len(texto_nativo) >= 10 or tablas_md:
                    if tablas_md:
                        contenido_pagina.append(tablas_md)
                    if texto_nativo:
                        contenido_pagina.append(texto_nativo)
                else:
                    tiene_imagenes = False
                    try:
                        tiene_imagenes = bool(page.get_images())
                    except Exception:
                        pass

                    if tiene_imagenes:
                        texto_ocr = _ejecutar_ocr_pagina(page)
                        if texto_ocr:
                            metodo = "ocr"
                            contenido_pagina.append(texto_ocr)
                        elif texto_nativo:
                            contenido_pagina.append(texto_nativo)
                    elif texto_nativo:
                        contenido_pagina.append(texto_nativo)

                texto_final = "\n\n".join(contenido_pagina).strip()

            except Exception as e_proc:
                print(f"  ├─ [ERROR PÁG] Pág {numero_pagina:02d}/{total_pags:02d} falló al procesarse: {e_proc}. Omitida.", flush=True)
                texto_final = ""
            finally:
                del page

            duracion_pag_ms = (time.perf_counter() - t_inicio_pag) * 1000

            if texto_final:
                documento_paginas.append({
                    "pagina": numero_pagina,
                    "texto": texto_final,
                    "metodo": metodo,
                    "duracion_ms": round(duracion_pag_ms, 2),
                    "caracteres": len(texto_final)
                })

            if verbose:
                tag = "🔍 OCR" if metodo == "ocr" else "⚡ NATIVO"
                print(f"  ├─ Pág {numero_pagina:02d}/{total_pags:02d} [{tag}] -> {len(texto_final)} chars en {duracion_pag_ms:.1f}ms", flush=True)

            if idx_pagina > 0 and idx_pagina % 25 == 0:
                gc.collect()

    except Exception as e_doc:
        print(f"[ERROR ARCHIVO] Fallo crítico al abrir o procesar el documento {ruta.name}: {e_doc}", flush=True)
    finally:
        if doc is not None:
            doc.close()
            del doc
        gc.collect()

    duracion_total = time.perf_counter() - t_inicio_doc
    if verbose:
        print(f"  └─ Extracción terminada: {len(documento_paginas)} págs válidas en {duracion_total:.2f}s", flush=True)

    return documento_paginas