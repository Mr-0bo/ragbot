# ingestion/document_parser.py
import time
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Union
import fitz  # PyMuPDF

_ocr_engine = None


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
            print(f"[WARN] No se pudo inicializar PaddleOCR: {e}")
            _ocr_engine = False
    return _ocr_engine


def _extraer_tablas_pagina(page) -> str:
    """Extrae tablas de la página usando la detección nativa de PyMuPDF."""
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

    return "\n\n".join(markdown_tablas)


def _ejecutar_ocr_pagina(page) -> str:
    """Renderiza a 150 DPI y ejecuta PaddleOCR."""
    ocr = _get_ocr_engine()
    if not ocr:
        return ""

    try:
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        resultado = ocr.ocr(img_bytes)

        del pix, img_bytes

        lineas_texto = []
        if resultado and resultado[0]:
            for linea in resultado[0]:
                lineas_texto.append(linea[1][0])

        return "\n".join(lineas_texto)
    except Exception as e:
        print(f"  [ERROR OCR] Falló OCR en pág. {page.number + 1}: {e}")
        return ""


def extraer_markdown_de_pdf(ruta_pdf: Union[str, Path], verbose: bool = True) -> List[Dict]:
    """
    Extrae contenido página por página reportando métricas de rendimiento por página.
    """
    ruta = Path(ruta_pdf)
    if not ruta.exists():
        raise FileNotFoundError(f"El archivo {ruta} no existe.")

    documento_paginas = []
    t_inicio_doc = time.perf_counter()

    with fitz.open(ruta) as doc:
        total_pags = len(doc)
        if verbose:
            print(f"\n[DEBUGGER PARSER] 📄 Abriendo '{ruta.name}' ({total_pags} págs)")

        for idx_pagina, page in enumerate(doc):
            t_inicio_pag = time.perf_counter()
            numero_pagina = idx_pagina + 1

            texto_nativo = page.get_text("text").strip()
            tablas_md = _extraer_tablas_pagina(page)

            contenido_pagina = []
            metodo = "nativo"

            if len(texto_nativo) >= 10 or tablas_md:
                if tablas_md:
                    contenido_pagina.append(tablas_md)
                if texto_nativo:
                    contenido_pagina.append(texto_nativo)
            else:
                if page.get_images():
                    texto_ocr = _ejecutar_ocr_pagina(page)
                    if texto_ocr:
                        metodo = "ocr"
                        contenido_pagina.append(texto_ocr)
                    elif texto_nativo:
                        contenido_pagina.append(texto_nativo)
                elif texto_nativo:
                    contenido_pagina.append(texto_nativo)

            texto_final = "\n\n".join(contenido_pagina).strip()
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
                print(f"  ├─ Pág {numero_pagina:02d}/{total_pags:02d} [{tag}] -> {len(texto_final)} chars en {duracion_pag_ms:.1f}ms")

    duracion_total = time.perf_counter() - t_inicio_doc
    if verbose:
        print(f"  └─ Extracción terminada: {len(documento_paginas)}/{total_pags} págs válidas en {duracion_total:.2f}s")

    return documento_paginas