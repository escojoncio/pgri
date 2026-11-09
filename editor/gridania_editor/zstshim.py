"""Zstandard multiplataforma. tools/py/zst.py usa ctypes + libzstd.so.1 (solo Linux). Si esa libreria no carga (Windows), se instala en sys.modules['zst']
un sustituto con el paquete `zstandard` y la misma API (compress(data, level) / decompress(blob)): UN frame con tamano de contenido, como zst.py."""
import sys, types


def _libzstd_ok():
    try:
        import ctypes, ctypes.util
    except Exception:
        return False
    for n in ('libzstd.so.1', ctypes.util.find_library('zstd') or 'libzstd.so'):
        try:
            ctypes.CDLL(n); return True
        except OSError:
            pass
    return False


def crear_modulo(zstandard):
    m = types.ModuleType('zst')
    m.__doc__ = 'sustituto de tools/py/zst.py sobre el paquete zstandard'

    def compress(data, level=19):
        return zstandard.ZstdCompressor(level=level, write_content_size=True, write_checksum=False).compress(data)

    def decompress(blob):
        d = zstandard.ZstdDecompressor()
        try:
            return d.decompress(blob)
        except Exception:
            # frame sin tamano de contenido: lectura en flujo
            import io
            return d.stream_reader(io.BytesIO(blob)).read()
    m.compress = compress; m.decompress = decompress
    return m


def instalar():
    """-> 'ctypes' | 'zstandard'. Llamar ANTES de importar build_blob/construir_dat."""
    if 'zst' in sys.modules:
        return 'ya'
    if _libzstd_ok():
        return 'ctypes'
    import zstandard   # dependencia declarada en requirements.txt
    sys.modules['zst'] = crear_modulo(zstandard)
    return 'zstandard'
