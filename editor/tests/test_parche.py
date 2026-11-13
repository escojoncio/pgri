"""Importar parche: extraccion segura (temporal + cambio atomico + copias), informe de novedades (nuevas/cambiadas/borradas/movidas), flujo, garantia de no tocar
traducciones/ni ediciones/ni el es e idempotencia. Juego FALSO: datos sinteticos, sin instalacion real."""
import hashlib, json, os, re, shutil, subprocess, time
import pytest
from conftest import necesita_repo, HOJA, REPO
from gridania_editor import extractor, parche, flujo


# ------------------------------------------------------------------ utilidades
def hash_arbol(*raices):
    h = hashlib.sha1()
    for r in raices:
        for d, ds, fs in sorted(os.walk(r)):
            ds.sort()
            for f in sorted(fs):
                p = os.path.join(d, f); h.update(os.path.relpath(p, r).encode()); h.update(open(p, 'rb').read())
    return h.hexdigest()


def escribir_ja(raiz, hoja, filas, idioma='ja'):
    p = os.path.join(raiz, 'textos', idioma, *hoja.split('/')) + '.jsonl'
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        for (r, s, c), t in sorted(filas.items(), key=lambda x: (x[0][0], x[0][2])): f.write(json.dumps({'row': r, 'sub': s, 'col': c, 'text': t}, ensure_ascii=False) + '\n')


class Falla(BaseException):
    """simula una interrupcion a mitad (no es Exception: el extractor no la traga hoja a hoja)"""


class FakeX(object):
    def __init__(self, R, juego, falla_en=None):
        self.juego = juego; self.falla_en = falla_en; self.n = 0       # R no se usa: el juego falso no necesita tools/py (los tests corren tambien en CI)

    def write_sheet(self, out, hoja, rows, lang_dir='ja'):
        escribir_ja(os.path.dirname(out), hoja, {(r, s, c): t for (r, s), cols in rows.items() for c, (t, _) in cols.items()}, lang_dir)
        return [], sum(len(c) for c in rows.values())

    def Pack(self, ruta):
        exl = ('EXL,2\n' + '\n'.join('%s,0' % h for h in sorted(self.juego))).encode()
        return type('Pk', (), {'read': lambda s, p: exl if p == 'exd/root.exl' else None})()

    def exh(self, pk, hoja): return {'cols': [(0, 0)], 'langs': ['ja', 'fr']}

    def read_rows(self, pk, hoja, h, lang, stats):
        self.n += 1
        if self.falla_en and self.n >= self.falla_en: raise Falla('corte')
        rows = {}
        for (r, s, c), t in self.juego[hoja].items(): rows.setdefault((r, s), {})[c] = (t if lang == 'ja' else 'FR ' + t, None)
        return rows


class PR(object):
    def __init__(self, R, X): self._R = R; self.X = X
    def __getattr__(self, k): return getattr(self._R, k)       # sin R (CI sin tools/py): solo .X



def crear_pack(tmp_path, nombre, version):
    g = tmp_path / nombre / 'game'; ruta = g / 'sqpack' / 'ffxiv'
    ruta.mkdir(parents=True, exist_ok=True); (ruta / '0a0000.win32.index').write_bytes(b'x'); (g / 'ffxivgame.ver').write_text(version)
    return str(ruta)


def juego_simple(n, extra=()):
    return {'A/h1': {(i, None, 1): 'こんにちは%d。' % i for i in range(n)}, 'A/h2': {(0, None, 1): '別の文章です。', **dict(extra)}}


# ------------------------------------------------------------------ extraccion segura
def test_extraer_correcto_cambia_textos_copia_y_guarda_version(tmp_path):
    dest = str(tmp_path / 'juego'); copias = str(tmp_path / 'copias'); ruta = crear_pack(tmp_path, 'g', '2026.11.01.0000.0000')
    i1 = extractor.extraer(PR(None, FakeX(None, juego_simple(5))), ruta, dest, copias_dir=copias)
    assert i1['version'] == '2026.11.01.0000.0000' and json.load(open(os.path.join(dest, 'info.json')))['version'] == i1['version']
    assert not os.path.exists(os.path.join(dest, '_extrayendo')) and i1['copia_anterior'] == ''
    (tmp_path / 'g' / 'game' / 'ffxivgame.ver').write_text('2026.11.20.0000.0000')
    antes = hash_arbol(os.path.join(dest, 'textos'))
    i2 = extractor.extraer(PR(None, FakeX(None, juego_simple(6))), ruta, dest, copias_dir=copias)
    assert i2['version'] == '2026.11.20.0000.0000' and os.path.isdir(i2['copia_anterior']) and i2['copia_anterior'].endswith('_2026.11.01.0000.0000')
    assert hash_arbol(os.path.join(i2['copia_anterior'], 'textos')) == antes                     # la copia es la extraccion anterior intacta
    assert json.load(open(os.path.join(i2['copia_anterior'], 'info.json')))['version'] == '2026.11.01.0000.0000'


def test_copias_se_conservan_las_3_ultimas(tmp_path):
    dest = str(tmp_path / 'juego'); copias = str(tmp_path / 'copias'); ruta = crear_pack(tmp_path, 'g', 'v00')
    for i in range(6):
        (tmp_path / 'g' / 'game' / 'ffxivgame.ver').write_text('v%02d' % i)
        extractor.extraer(PR(None, FakeX(None, juego_simple(5 + i))), ruta, dest, copias_dir=copias)
    nombres = sorted(os.listdir(copias))
    assert len(nombres) == 3 and [n.split('_')[1] for n in nombres] == ['v02', 'v03', 'v04']      # copias de las versiones anteriores a la actual (v05)


@pytest.mark.parametrize('modo', ['corte', 'sin_celdas', 'incompleta', 'antes'])
def test_fallo_deja_textos_e_info_intactos(tmp_path, modo):
    dest = str(tmp_path / 'juego'); copias = str(tmp_path / 'copias'); ruta = crear_pack(tmp_path, 'g', '2026.11.01.0000.0000')
    extractor.extraer(PR(None, FakeX(None, juego_simple(20))), ruta, dest, copias_dir=copias)
    antes = hash_arbol(dest); (tmp_path / 'g' / 'game' / 'ffxivgame.ver').write_text('2026.12.01.0000.0000')
    cb = None
    if modo == 'corte': x = FakeX(None, juego_simple(20), falla_en=2); exc = Falla
    elif modo == 'sin_celdas': x = FakeX(None, {'A/h1': {}}); exc = ValueError
    elif modo == 'incompleta': x = FakeX(None, juego_simple(2)); exc = ValueError
    else:
        x = FakeX(None, juego_simple(21)); exc = RuntimeError
        def cb(tn, info): raise RuntimeError('fallo al comparar')
    with pytest.raises(exc):
        extractor.extraer(PR(None, x), ruta, dest, copias_dir=copias, antes_de_cambiar=cb)
    assert hash_arbol(dest) == antes and not os.path.exists(os.path.join(dest, '_extrayendo')) and not os.path.exists(copias)


def test_fallo_al_cambiar_deshace(tmp_path, monkeypatch):
    dest = str(tmp_path / 'juego'); ruta = crear_pack(tmp_path, 'g', 'v1')
    extractor.extraer(PR(None, FakeX(None, juego_simple(5))), ruta, dest, copias_dir=str(tmp_path / 'c'))
    antes = hash_arbol(dest); (tmp_path / 'g' / 'game' / 'ffxivgame.ver').write_text('v2')
    real = os.replace; llamadas = []
    def rota(a, b):
        llamadas.append((a, b))
        if len(llamadas) == 2: raise OSError('disco lleno')       # 1.º mover textos a la copia, 2.º poner el nuevo
        return real(a, b)
    monkeypatch.setattr(os, 'replace', rota)
    with pytest.raises(OSError): extractor.extraer(PR(None, FakeX(None, juego_simple(6))), ruta, dest, copias_dir=str(tmp_path / 'c'))
    monkeypatch.undo()
    assert hash_arbol(dest) == antes and not os.listdir(str(tmp_path / 'c'))


def test_version_segura_no_permite_rutas():
    assert extractor.version_segura('../../x/y') == 'x_y' and '/' not in extractor.version_segura('a/b\\c') and extractor.version_segura('') == 'sin-version'


# ------------------------------------------------------------------ comparacion (unitaria, datos sinteticos)
def montar_comparacion(tmp_path):
    v, n, repo = str(tmp_path / 'v'), str(tmp_path / 'n'), str(tmp_path / 'repo')
    escribir_ja(v, 'Q/a', {(0, None, 1): '同じ文です。', (1, None, 1): '古い文です。', (2, None, 1): '消える文です。', (3, None, 1): '動く文です。', (4, None, 1): '消えるが訳なし。', (5, None, 0): 'KEY_5'})
    escribir_ja(n, 'Q/a', {(0, None, 1): '同じ文です。', (1, None, 1): '新しい文です。', (6, None, 1): '完全に新しい文です。', (7, None, 1): '動く文です。', (8, None, 0): 'KEY_8'})
    escribir_ja(n, 'Q/nueva', {(0, None, 1): '新しい文書。'})
    escribir_ja(v, 'Q/vieja', {(0, None, 1): '消える文書。'})
    tr = os.path.join(repo, 'traducciones', 'Q'); os.makedirs(tr)
    with open(os.path.join(tr, 'a.jsonl'), 'w', encoding='utf-8') as f:
        for r, es in ((0, 'igual'), (1, 'vieja traduccion'), (2, 'borrada'), (3, ['se mueve', 'dos trozos'])):
            f.write(json.dumps({'row': r, 'sub': None, 'col': 1, 'es': es, 'estado': 'traducida', 'h': 'x', 'origen': 'fr-ja-retrad'}, ensure_ascii=False) + '\n')
    return v, n, repo


def test_comparar_clasifica_nuevas_cambiadas_borradas_movidas(tmp_path):
    v, n, repo = montar_comparacion(tmp_path)
    antes = hash_arbol(repo, v, n)
    h = parche.comparar(v, n, repo, None)
    a = h['Q/a']
    assert [x[:3] for x in a['nuevas']] == [[6, None, 1], [7, None, 1]]                 # las claves KEY_* (sin CJK) no cuentan
    assert [(x[:3], x[3]) for x in a['cambiadas']] == [([1, None, 1], '古い文です。')]
    assert sorted(x[:3] for x in a['borradas']) == [[2, None, 1], [3, None, 1], [4, None, 1]]
    assert [x[4] for x in a['borradas'] if x[0] == 2] == ['borrada'] and [x[4] for x in a['borradas'] if x[0] == 4] == [None]
    assert a['movidas'] == [{'de': [3, None, 1], 'a': [7, None, 1], 'ja': '動く文です。', 'es': ['se mueve', 'dos trozos'], 'aceptada': False}]
    assert h['Q/nueva']['nuevas'] == [[0, None, 1]] and h['Q/vieja']['borradas'] == [[0, None, 1, '消える文書。', None]] and h['Q/nueva']['movidas'] == []
    assert parche.conteos(h) == {'nuevas': 3, 'cambiadas': 1, 'borradas': 4, 'movidas': 1}
    assert hash_arbol(repo, v, n) == antes                                                  # solo lectura


def test_movida_no_cruza_hojas_ni_pisa_traduccion_propia(tmp_path):
    v, n, repo = montar_comparacion(tmp_path)
    escribir_ja(n, 'Q/otra', {(0, None, 1): '消える文です。'})                               # misma frase que la borrada Q/a:2 pero en OTRA hoja: no es movida
    with open(os.path.join(repo, 'traducciones', 'Q', 'a.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps({'row': 7, 'sub': None, 'col': 1, 'es': 'ya traducida', 'estado': 'traducida', 'h': 'y', 'origen': 'fr-ja-retrad'}) + '\n')
    h = parche.comparar(v, n, repo, None)
    assert h['Q/a']['movidas'] == [] and h['Q/otra']['movidas'] == []


def test_informe_idempotente_y_conserva_aceptadas(tmp_path):
    v, n, repo = montar_comparacion(tmp_path); d = str(tmp_path / 'parches')
    inf = parche.crear_informe('2026.11.20', '2026.11.01', parche.comparar(v, n, repo, None))
    r, escrito = parche.guardar_informe(d, inf); assert escrito
    ruta = os.path.join(d, '2026.11.20.json'); b1 = open(ruta, 'rb').read()
    vacio = parche.crear_informe('2026.11.20', '2026.11.20', {})
    r2, escrito2 = parche.guardar_informe(d, vacio)
    assert not escrito2 and open(ruta, 'rb').read() == b1 and r2['conteos'] == inf['conteos']        # reimportar el mismo parche no pierde el informe
    inf['hojas']['Q/a']['movidas'][0]['aceptada'] = True; parche.guardar_informe(d, inf)
    otra = parche.crear_informe('2026.11.20', 'x', parche.comparar(v, n, repo, None))
    r3, _ = parche.guardar_informe(d, otra); assert r3['hojas']['Q/a']['movidas'][0]['aceptada'] is True
    assert [p['version'] for p in parche.listar_informes(d)] == ['2026.11.20']


def test_marcar_flujo_respeta_hecho_y_devuelve_cambiadas(tmp_path):
    f = flujo.Flujo(str(tmp_path / 'flujo.json'))
    inf = {'version': 'v9', 'hojas': {'H': {'nuevas': [[1, None, 1], [2, None, 1]], 'cambiadas': [[3, None, 1, 'viejo']], 'borradas': [], 'movidas': []}}}
    f.poner([('H', 2, None, 1), ('H', 3, None, 1)], 'hecho')
    r = parche.marcar_flujo(f, inf)
    assert f.estado('H', 1, None, 1) == 'por_hacer' and f.estado('H', 2, None, 1) == 'hecho' and f.estado('H', 3, None, 1) == 'por_hacer'
    assert r == {'por_hacer': 2, 'respetadas_hecho': 1} and f.etiqueta('H', 3, None, 1) == {'version': 'v9', 'tipo': 'cambiada'} and f.etiqueta('H', 2, None, 1) is None
    assert flujo.Flujo(str(tmp_path / 'flujo.json')).etiqueta('H', 1, None, 1) == {'version': 'v9', 'tipo': 'nueva'}     # persiste


# ------------------------------------------------------------------ integracion: Aplicacion + juego falso
def esperar(app):
    t0 = time.time()
    while time.time() - t0 < 180:
        t = app.tarea.ver()
        if t['estado'] != 'ejecutando': return t
        time.sleep(0.1)
    raise AssertionError('la tarea no termina')


@pytest.fixture()
def app(tmp_path, mini_repo, R):
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'home'), repo_override=mini_repo)
    a._indexar(lambda m: None)
    a._R = PR(R, None)
    return a


def juego_parcheado():
    """texto del repo de HOJA + cambios: row1 cambiada, row3 borrada, row2 'movida' a 902, nuevas 901 y una hoja entera nueva"""
    filas = {}
    for l in open(os.path.join(REPO, 'textos', 'ja', HOJA + '.jsonl'), encoding='utf-8'):
        j = json.loads(l); filas[(j['row'], j['sub'], j['col'])] = j['text']
    orig = dict(filas)
    filas[(1, None, 1)] = filas[(1, None, 1)] + '【改訂】'
    movido = filas.pop((2, None, 1)); filas[(902, None, 1)] = movido
    filas.pop((3, None, 1)); filas[(901, None, 1)] = '新しい台詞がここに入ります。'
    return {HOJA: filas, 'quest/000/NuevaHoja': {(0, None, 1): '完全に新しい任務です。', (1, None, 1): '二つ目の文です。'}}, orig


@necesita_repo
def test_importar_parche_extremo_a_extremo_idempotente_y_sin_tocar_es(tmp_path, app, mini_repo, R):
    ruta = crear_pack(tmp_path, 'g', '2026.11.20.0000.0000')
    juego, orig = juego_parcheado(); app._R = PR(R, FakeX(None, juego))
    ed = app.cfg.ediciones_dir; os.makedirs(ed, exist_ok=True)
    app.flujo.poner([(HOJA, 901, None, 1), (HOJA, 1, None, 1)], 'hecho')            # 901: marca previa «hecho» (se respeta); 1: cambiada «hecho» (vuelve a Por hacer)
    es1 = app.base.q('SELECT es,es_json FROM celdas WHERE hoja=? AND row=1 AND col=1', (HOJA,))[0]
    tr_antes = hash_arbol(os.path.join(mini_repo, 'traducciones'), ed); tr_trad = hash_arbol(os.path.join(mini_repo, 'traducciones'))
    app.tarea_extraer(ruta); t = esperar(app)
    assert t['estado'] == 'ok', t['error']
    # garantia: ni traducciones/ ni ediciones/ cambian; el es de la cambiada sigue igual
    assert hash_arbol(os.path.join(mini_repo, 'traducciones'), ed) == tr_antes
    es1b = app.base.q('SELECT es,es_json,estado FROM celdas WHERE hoja=? AND row=1 AND col=1', (HOJA,))[0]
    assert es1b['es'] == es1['es'] and es1b['es_json'] == es1['es_json'] and es1b['estado'] == 'naranja'
    inf = parche.leer_informe(app.cfg.parches_dir, '2026.11.20.0000.0000')
    c = inf['conteos']; assert c['nuevas'] == 4 and c['cambiadas'] == 1 and c['borradas'] == 2 and c['movidas'] == 1, c
    assert json.load(open(os.path.join(app.cfg.juego_dir, 'info.json')))['version'] == '2026.11.20.0000.0000'
    assert app.flujo.estado(HOJA, 1, None, 1) == 'por_hacer' and app.flujo.estado(HOJA, 901, None, 1) == 'hecho'
    assert app.flujo.estado(HOJA, 902, None, 1) == 'por_hacer' and app.flujo.estado('quest/000/NuevaHoja', 0, None, 1) == 'por_hacer'
    assert app.flujo.etiqueta('quest/000/NuevaHoja', 1, None, 1)['version'] == '2026.11.20.0000.0000'
    assert app.base.q("SELECT COUNT(*) n FROM celdas WHERE flujo='por_hacer'")[0]['n'] == 4          # 902, 1, y las 2 de la hoja nueva (901 ya era «hecho»)
    # vistas de novedades
    hs = app.parche_hojas(None, 'nuevas'); assert {h['hoja'] for h in hs['hojas']} == {HOJA, 'quest/000/NuevaHoja'}
    assert [h['hoja'] for h in app.parche_hojas(None, 'cambiadas')['hojas']] == [HOJA]
    d = app.parche_hoja(None, HOJA, 'cambiadas'); marcadas = [x for x in d['celdas'] if x['novedad']]
    assert len(marcadas) == 1 and marcadas[0]['ja_anterior'] == orig[(1, None, 1)] and any(x.get('contexto') for x in d['celdas'])
    assert len(d['borradas']) == 2 and d['movidas'][0]['a'] == [902, None, 1]
    # idempotencia: importar de nuevo el mismo parche
    estado1 = (open(app.flujo.ruta, 'rb').read(), open(os.path.join(app.cfg.parches_dir, '2026.11.20.0000.0000.json'), 'rb').read(), app.base.q('SELECT COUNT(*) n FROM celdas')[0]['n'])
    app.tarea_extraer(ruta); t2 = esperar(app); assert t2['estado'] == 'ok', t2['error']
    assert t2['resultado']['parche']['ya_importado'] is True
    estado2 = (open(app.flujo.ruta, 'rb').read(), open(os.path.join(app.cfg.parches_dir, '2026.11.20.0000.0000.json'), 'rb').read(), app.base.q('SELECT COUNT(*) n FROM celdas')[0]['n'])
    assert estado1 == estado2 and (not os.path.exists(app.cfg.copias_dir) or not os.listdir(app.cfg.copias_dir))      # mismo parche: sin copia nueva
    assert hash_arbol(os.path.join(mini_repo, 'traducciones'), ed) == tr_antes
    # arrastrar la traduccion de la movida: solo al aceptar
    pv = app.parche_movidas(); assert pv['total'] == 1 and pv['movidas'][0]['estado_destino'] == 'rojo' and pv['movidas'][0]['es']
    assert not os.listdir(ed)                                                         # nada aplicado solo
    r = app.parche_arrastrar(None, HOJA); assert r['aplicadas'] == 1 and not r['fallos'], r
    fila = [json.loads(l) for l in open(os.path.join(ed, 'traducciones', *HOJA.split('/')) + '.jsonl')]
    assert len(fila) == 1 and fila[0]['row'] == 902 and fila[0]['origen'] == 'sesion' and fila[0]['estado'] == 'traducida'
    assert app.base.q('SELECT estado FROM celdas WHERE hoja=? AND row=902 AND col=1', (HOJA,))[0]['estado'] == 'verde'
    assert hash_arbol(os.path.join(mini_repo, 'traducciones')) == tr_trad       # arrastrar escribe SOLO en ediciones/, nunca en traducciones/
    assert app.parche_arrastrar(None, HOJA)['aplicadas'] == 0                         # ya aceptada: no se repite


@necesita_repo
def test_importar_con_fallo_deja_textos_intactos_y_error_claro(tmp_path, app, mini_repo, R):
    ruta = crear_pack(tmp_path, 'g', '2026.11.20.0000.0000')
    juego, _ = juego_parcheado(); app._R = PR(R, FakeX(None, juego))
    app.tarea_extraer(ruta); assert esperar(app)['estado'] == 'ok'
    antes = hash_arbol(app.cfg.juego_dir)
    (tmp_path / 'g' / 'game' / 'ffxivgame.ver').write_text('2026.12.01.0000.0000')
    app._R = PR(R, FakeX(None, juego, falla_en=2))
    app.tarea_extraer(ruta); t = esperar(app)
    assert t['estado'] == 'error' and 'corte' in t['error'] and hash_arbol(app.cfg.juego_dir) == antes
    assert parche.listar_informes(app.cfg.parches_dir)[0]['version'] == '2026.11.20.0000.0000' and len(parche.listar_informes(app.cfg.parches_dir)) == 1


# ------------------------------------------------------------------ JS
@pytest.mark.skipif(not shutil.which('node'), reason='sin node')
def test_js_inline_de_index_html_es_sintacticamente_valido(tmp_path):
    t = open(os.path.join(os.path.dirname(__file__), '..', 'gridania_editor', 'ui', 'index.html'), encoding='utf-8').read()
    f = tmp_path / 'inline.js'; f.write_text('\n'.join(re.findall(r'<script>(.*?)</script>', t, re.S)), encoding='utf-8')
    r = subprocess.run([shutil.which('node'), '--check', str(f)], capture_output=True, text=True); assert r.returncode == 0, r.stderr
    for ident in ('bNov', 'dNov', 'nvAbrir', 'Importar parche', '/api/parche_arrastrar'): assert ident in t
