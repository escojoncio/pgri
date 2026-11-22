"""Zstandard minimo via ctypes sobre libzstd.so.1 (sin pip)."""
import ctypes, ctypes.util
def _lib():
    for n in ('libzstd.so.1', ctypes.util.find_library('zstd') or 'libzstd.so'):
        try: return ctypes.CDLL(n)
        except OSError: pass
    raise RuntimeError('libzstd no disponible')
_z = _lib()
_z.ZSTD_compressBound.restype = ctypes.c_size_t; _z.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
_z.ZSTD_compress.restype = ctypes.c_size_t
_z.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
_z.ZSTD_isError.restype = ctypes.c_uint; _z.ZSTD_isError.argtypes = [ctypes.c_size_t]
_z.ZSTD_getErrorName.restype = ctypes.c_char_p; _z.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
_z.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong; _z.ZSTD_getFrameContentSize.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
_z.ZSTD_decompress.restype = ctypes.c_size_t
_z.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
_z.ZSTD_findFrameCompressedSize.restype = ctypes.c_size_t; _z.ZSTD_findFrameCompressedSize.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
def _chk(r):
    if _z.ZSTD_isError(r): raise RuntimeError(_z.ZSTD_getErrorName(r).decode())
    return r
def compress(data: bytes, level=19) -> bytes:
    cap = _z.ZSTD_compressBound(len(data)); buf = ctypes.create_string_buffer(cap)
    n = _chk(_z.ZSTD_compress(buf, cap, data, len(data), level)); return buf.raw[:n]
def decompress(blob: bytes) -> bytes:
    """Exige UN solo frame que ocupe todo el blob."""
    fs = _chk(_z.ZSTD_findFrameCompressedSize(blob, len(blob)))
    if fs != len(blob): raise RuntimeError('mas de un frame / bytes sobrantes')
    size = _z.ZSTD_getFrameContentSize(blob, len(blob))
    if size >= (1 << 63) - 2: raise RuntimeError('frame sin tamano de contenido')
    buf = ctypes.create_string_buffer(int(size) or 1)
    n = _chk(_z.ZSTD_decompress(buf, int(size), blob, len(blob))); return buf.raw[:n]
