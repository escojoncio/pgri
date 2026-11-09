import json, os, stat, sys, zlib
from gridania_editor import config, zstshim


def test_token_no_sale_en_publico_ni_en_redactar(tmp_path):
    c = config.Config(str(tmp_path))
    c.actualizar({'token': 'ghp_SECRETO123', 'repo': 'a/b'})
    assert 'ghp_SECRETO123' not in json.dumps(c.publico()) and c.publico()['token_guardado'] is True
    assert 'ghp_SECRETO123' not in c.redactar('fallo con ghp_SECRETO123 en la url')
    c.actualizar({'token': ''})                      # vacio = conservar
    assert c['token'] == 'ghp_SECRETO123'
    if os.name == 'posix': assert stat.S_IMODE(os.stat(c.ruta).st_mode) == 0o600
    c.borrar_token(); assert c['token'] == '' and not c.publico()['token_guardado']
    assert config.Config(str(tmp_path))['repo'] == 'a/b'


def test_token_solo_en_la_carpeta_de_trabajo(tmp_path):
    c = config.Config(str(tmp_path)); c.actualizar({'token': 'ghp_X'})
    assert os.path.dirname(c.ruta) == str(tmp_path)


def test_zstshim_sustituto_con_api_de_zst():
    class FakeC:
        def __init__(self, level=3, write_content_size=True, write_checksum=False): pass
        def compress(self, d): return zlib.compress(d)
    class FakeD:
        def decompress(self, b): return zlib.decompress(b)
    fake = type(sys)('zstandard'); fake.ZstdCompressor = FakeC; fake.ZstdDecompressor = FakeD
    m = zstshim.crear_modulo(fake)
    assert m.decompress(m.compress(b'hola' * 100, 19)) == b'hola' * 100


def test_instalar_en_linux_usa_libzstd():
    assert zstshim.instalar() in ('ctypes', 'ya', 'zstandard')
