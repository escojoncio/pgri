import json, os, shutil
import pytest
from conftest import necesita_repo, necesita_juego, JUEGO, HOJA, REPO
from gridania_editor import indexer, builder, edits, extractor


def escribir(raiz, ruta, filas):
    p = os.path.join(raiz, *ruta.split('/')); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'w', encoding='utf-8').write(''.join(json.dumps(f, ensure_ascii=False) + '\n' for f in filas))


@necesita_repo
def test_colores_rojo_naranja_verde_blanco(tmp_path, R):
    G = R.G
    previo, nuevo, ed = str(tmp_path / 'repo'), str(tmp_path / 'juego'), str(tmp_path / 'ed')
    ja_old = {1: 'こんにちは', 2: 'さようなら', 3: 'ありがとう', 4: 'おはよう', 5: 'abc', 6: 'こんばんは'}
    escribir(previo, 'textos/ja/S.jsonl', [{'row': r, 'sub': None, 'col': 0, 'text': t} for r, t in ja_old.items()])
    ja_new = dict(ja_old); ja_new[2] = 'さよなら'; ja_new[7] = 'はじめまして'; ja_new[8] = 'ちがう'
    escribir(nuevo, 'textos/ja/S.jsonl', [{'row': r, 'sub': None, 'col': 0, 'text': t} for r, t in ja_new.items()])
    def tr(r, t, origen='fr-ja-retrad', estado='traducida'):
        return {'row': r, 'sub': None, 'col': 0, 'es': ['x'], 'estado': estado, 'h': G.hash_ja(t), 'origen': origen}
    escribir(previo, 'traducciones/S.jsonl', [tr(1, ja_old[1]), tr(2, ja_old[2]), tr(4, ja_old[4], origen='corpus'), tr(6, ja_old[6], estado='dudosa')])
    base = indexer.Base(str(tmp_path / 'db.sqlite'))
    # sin extraccion (nuevo == previo): 2 verde, resto con CJK = blanco; 'abc' (sin CJK ni traduccion) no se indexa
    indexer.indexar(R, base, previo, previo, ed, lambda m: None)
    c = indexer.contadores(base); assert c == {'rojo': 0, 'naranja': 0, 'verde': 2, 'blanco': 3}
    # con extraccion: 2 cambia (naranja), 7 y 8 nuevas (rojo), 3/4/6 blanco
    indexer.indexar(R, base, previo, nuevo, ed, lambda m: None)
    c = indexer.contadores(base); assert c == {'rojo': 2, 'naranja': 1, 'verde': 1, 'blanco': 3}
    # japones cambiado SIN traduccion -> rojo
    escribir(nuevo, 'textos/ja/S.jsonl', [{'row': r, 'sub': None, 'col': 0, 'text': t} for r, t in {**ja_new, 3: 'ありがとうございます'}.items()])
    indexer.indexar(R, base, previo, nuevo, ed, lambda m: None)
    assert indexer.contadores(base)['rojo'] == 3
    # una edicion del usuario (h del ja nuevo) pasa a verde
    escribir(ed, 'traducciones/S.jsonl', [dict(tr(7, ja_new[7]), origen='sesion')])
    indexer.indexar(R, base, previo, nuevo, ed, lambda m: None)
    assert indexer.contadores(base)['rojo'] == 2 and indexer.contadores(base)['verde'] == 2
    t, filas = indexer.listar(base, estados=['rojo'], q='ちがう'); assert t == 1 and filas[0]['row'] == 8
    assert indexer.hojas_resumen(base)[0]['hoja'] == 'S'


def test_puerta():
    assert builder.puerta(757594, 43, 0)[0]
    assert not builder.puerta(757593, 43, 0)[0] and not builder.puerta(757594, 44, 0)[0] and not builder.puerta(757594, 0, 1, relajar=True)[0]
    ok, m = builder.puerta(700000, 100, 0, relajar=True); assert ok and len(m) == 2


@necesita_repo
def test_fusionar_ediciones(tmp_path, R, mini_repo):
    ed = str(tmp_path / 'ed'); st = str(tmp_path / 'st' / 'traducciones'); shutil.copytree(os.path.join(mini_repo, 'traducciones'), st)
    ja = R.G.leer_ja(mini_repo, HOJA); k = (53, None, 1); h = R.G.hash_ja(ja[k][0])
    e = {'row': 53, 'sub': None, 'col': 1, 'es': ['a', 'b', 'c'], 'estado': 'traducida', 'h': h, 'origen': 'sesion'}
    escribir(ed, 'traducciones/' + HOJA + '.jsonl', [e])
    assert edits.fusionar_en(st, ed) == 1
    fila = [json.loads(l) for l in open(os.path.join(st, *HOJA.split('/')) + '.jsonl') if '"row":53' in l.replace(' ', '') and '"col":1' in l.replace(' ', '')]
    assert fila[-1]['es'] == ['a', 'b', 'c']
    # el original del repo no se toca
    assert 'a' != json.loads([l for l in open(os.path.join(mini_repo, 'traducciones', *HOJA.split('/')) + '.jsonl') if '"row":53,' in l][0])['es'][0]


@necesita_juego
def test_extractor_parcial_identico_al_repo(tmp_path, R):
    class P(R.X.Pack):
        def read(self, path):
            b = super().read(path)
            return b'exd,\nTown,0\n' if path == 'exd/root.exl' else b
    orig = R.X.Pack; R.X.Pack = P
    try:
        info = extractor.extraer(R, JUEGO, str(tmp_path / 'j'), ('ja', 'fr'), lambda m: None)
    finally:
        R.X.Pack = orig
    assert info['celdas']['ja'] > 0
    assert open(tmp_path / 'j' / 'textos' / 'ja' / 'Town.jsonl', 'rb').read() == open(os.path.join(REPO, 'textos', 'ja', 'Town.jsonl'), 'rb').read()
    with pytest.raises(ValueError): extractor.comprobar_ruta(str(tmp_path))


@necesita_juego
def test_generar_dat_de_extremo_a_extremo(tmp_path, mini_repo, R):
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'home'), repo_override=mini_repo)
    a.cfg.actualizar({'ruta_juego': JUEGO, 'min_entradas': 5, 'max_rechazos': 50})
    a._indexar(lambda m: None)
    i = a.base.q('SELECT id FROM celdas WHERE hoja=? AND row=53 AND col=1', (HOJA,))[0]['id']
    assert a.guardar(i, a.celda(i)['es_texto'].replace('sitio', 'lugar'))['guardado']
    log = []
    res = builder.generar(a.R(), a.cfg, str(tmp_path / 'out'), a.raiz_textos(), log.append)
    assert res['entradas'] >= 5 and res['elipsis'] == 0 and res['validacion']['fallos'] == 0 and len(res['sha256']) == 64 and os.path.getsize(res['ruta']) == res['tamano']
    import gzip
    zst = __import__('zst'); datos = zst.decompress(open(res['ruta'], 'rb').read()).decode()
    assert 'lugar ideal' in datos.replace('\\u00a0', ' ') or 'lugar' in datos
    # la puerta bloquea si faltan entradas
    a.cfg.actualizar({'min_entradas': 10 ** 7})
    with pytest.raises(builder.ErrorPuerta): builder.generar(a.R(), a.cfg, str(tmp_path / 'out2'), a.raiz_textos(), log.append)
