# diagnostico_red.py
import sys
import traceback
import time


def probar_modulo(nombre: str, func):
    print(f"\n{'=' * 60}")
    print(f"Probando inicialización de: {nombre}")
    print(f"{'=' * 60}")
    t0 = time.perf_counter()
    try:
        resultado = func()
        duracion = time.perf_counter() - t0
        print(f"✓ ÉXITO: {nombre} cargó correctamente en {duracion:.2f}s.")
        return True
    except Exception as e:
        duracion = time.perf_counter() - t0
        print(f"✗ ERROR en {nombre} (tras {duracion:.2f}s):")
        print(f"  Tipo de error: {type(e).__name__}")
        print(f"  Mensaje      : {e}")

        # Verificar si es error de resolución de red
        if "11001" in str(e) or "getaddrinfo" in str(e):
            print("\n  🚨 DIAGNÓSTICO: Este componente intentó resolver un dominio en internet")
            print("                 y falló por falta de conexión o bloqueo de DNS.")

        print("\nTraceback completo:")
        traceback.print_exc()
        return False


def main():
    print("Iniciando pruebas de carga individual de modelos...\n")

    # 1. Probar BGE-M3 (SentenceTransformers)
    from backend.search_service import get_embedding_model
    probar_modulo("1. Embeddings Densos (BGE-M3)", get_embedding_model)

    # 2. Probar BM25 (FastEmbed Sparse)
    from backend.search_service import get_sparse_model
    probar_modulo("2. BM25 Disperso (FastEmbed)", get_sparse_model)

    # 3. Probar Reranker (FastEmbed Cross-Encoder)
    from backend.search_service import get_reranker_model
    probar_modulo("3. Reranker (FastEmbed Cross-Encoder)", get_reranker_model)

    # 4. Probar Base de Datos Qdrant
    from backend.search_service import get_qdrant_client
    probar_modulo("4. Cliente Qdrant Local", get_qdrant_client)

    print(f"\n{'=' * 60}")
    print("Diagnóstico finalizado.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()