import json, os, threading, urllib.request, urllib.error
import pytest
from conftest import necesita_repo, HOJA

pytestmark = necesita_repo


@pytest.fixture()
def app(tmp_path, mini_repo):
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'home'), repo_override=mini_repo)
    a._indexar(lambda m: None)
    return a


def hallar(app, row, col=1):
    r = app.base.q('SELECT id FROM celdas WHERE hoja=? AND row=? AND col=?', (HOJA, row, col))
    return r[0]['id']


def test_indexado_estados_y_fr(app):
    c = app.estado()['contadores']
    assert c['verde'] > 0 and c['rojo'] == 0 and sum(c.values()) > 10
    assert app.base.q("SELECT COUNT(*) n FROM celdas WHERE fr<>''")[0]['n'] > 0


def test_celda_tres_paneles_contexto_y_vistas(app):
    d = app.celda(hallar(app, 53))
    assert d['vista_ja']['ventanas'] and d['vista_fr'] and d['contexto']['anterior'] and d['contexto']['siguiente']
    assert '\n' in d['es_texto'] and d['perfil']['tipo'] == 'dialogo'
    assert 'hablante' in d


def test_preview_incluye_vistas_ja_fr_y_errores(app):
    i = hallar(app, 53)
    r = app.preview(i, 'hola')
    assert r['errores'] and r['errores'][0][0] == 'ESTRUCTURA'
    t = app.celda(i)['es_texto']
    r = app.preview(i, t.replace('técnicas', 'tecnicas…'))
    assert r['vista_ja'] and any('…' in str(x) or x[0] == 'AUTOCORREGIDO' for x in r['avisos'])


def test_guardar_sesion_h_correcto_y_bloquea_errores(app):
    i = hallar(app, 53); t = app.celda(i)['es_texto']
    assert app.guardar(i, t.replace('sitio', 'sitio ustedes'))['guardado'] is False       # LATINISMO (ustedes)
    r = app.guardar(i, t.replace('sitio', 'lugar'))
    assert r['guardado']
    f = [json.loads(l) for l in open(os.path.join(app.cfg.ediciones_dir, 'traducciones', *HOJA.split('/')) + '.jsonl')]
    assert len(f) == 1 and f[0]['origen'] == 'sesion' and f[0]['estado'] == 'traducida' and f[0]['h'] == app.celda(i)['h']
    assert app.estado()['ediciones']['filas'] == 1
    assert app.buscar({'texto': 'lugar ideal', 'campos': ['es']})['total'] == 1


def test_reemplazo_previa_y_aplicar(app):
    q = {'texto': 'Gridania', 'campos': ['es'], 'modo': 'palabra', 'reemplazo': 'Gridania', 'aplicar': False}
    assert app.buscar(q)['total'] > 0
    q['texto'] = 'instalaciones'; q['reemplazo'] = 'instalaciones'
    prev = app.reemplazar(q); assert prev['n_cambios'] == 0               # reemplazo identico: nada cambia
    q['reemplazo'] = 'sedes'
    prev = app.reemplazar(q)
    assert prev['n_cambios'] + prev['n_rechazadas'] > 0 and app.estado()['ediciones']['filas'] == 0   # la previa no escribe
    ap = app.reemplazar(dict(q, aplicar=True))
    assert app.estado()['ediciones']['filas'] == ap['n_cambios'] and ap['n_cambios'] > 0
    assert app.buscar({'texto': 'sedes', 'campos': ['es']})['total'] >= ap['n_cambios']
    # mismas validaciones: latinismo (ustedes) rechazado
    r = app.reemplazar({'texto': 'sitio ideal', 'reemplazo': 'ustedes ideal', 'aplicar': True})
    assert r['n_cambios'] == 0 and r['n_rechazadas'] == 1


def test_exportar_busqueda_y_ediciones(app, tmp_path):
    r = app.exportar_busqueda({'texto': 'Gridania', 'destino': str(tmp_path / 'o')})
    assert r['celdas'] > 0 and os.path.exists(r['ruta'])
    i = hallar(app, 53); app.guardar(i, app.celda(i)['es_texto'].replace('sitio', 'lugar'))
    e = app.exportar(str(tmp_path / 'ex')); assert e['filas'] == 1 and os.path.isdir(os.path.join(e['carpeta'], 'traducciones'))


def test_servidor_auth_host_y_token(app):
    from gridania_editor.servidor import Servidor
    app.cfg.actualizar({'token': 'ghp_SECRETO'})
    s = Servidor(app); s.arrancar()
    try:
        def get(ruta, k=True, host=None):
            h = {'X-K': s.clave} if k else {}
            if host: h['Host'] = host
            return urllib.request.urlopen(urllib.request.Request(s.url.rstrip('/') + ruta, headers=h))
        with pytest.raises(urllib.error.HTTPError) as e: get('/api/estado', k=False)
        assert e.value.code == 401
        with pytest.raises(urllib.error.HTTPError) as e: get('/api/estado', host='evil.example')
        assert e.value.code == 403
        cuerpo = get('/api/estado').read().decode()
        assert 'ghp_SECRETO' not in cuerpo and json.loads(cuerpo)['config']['token_guardado'] is True
        assert s.clave in urllib.request.urlopen(s.url).read().decode()
        req = urllib.request.Request(s.url + 'api/buscar', data=json.dumps({'texto': 'Gridania'}).encode(), headers={'X-K': s.clave, 'Content-Type': 'application/json'})
        assert json.loads(urllib.request.urlopen(req).read())['total'] > 0
    finally:
        s.parar()


def test_variantes_genero_y_vista_ingame(app):
    i = hallar(app, 53); t = app.celda(i)['es_texto']
    r = app.preview(i, t)
    assert r['suavizado'] is not None and 'hablante' in r['vista']
    m = app.motor(); reg = app.base.q('SELECT hoja,row,sub,col FROM celdas WHERE id=?', (i,))[0]
    c = m.contexto(reg['hoja'], reg['row'], reg['sub'], reg['col'])
    res = {}; m._poner_vistas(res, m.vista, c, 'Hola <Gender>amiga<GenderElse>amigo<GenderEnd>.', 'masc')
    assert set(res['variantes']) == {'fem', 'masc'} and res['vista'] is res['variantes']['masc']
    txt = lambda v: ''.join(l for w in v['ventanas'] for l in w)
    assert 'amiga' in txt(res['variantes']['fem']) and 'amigo' in txt(res['variantes']['masc'])
    res = {}; m._poner_vistas(res, m.vista, c, 'Hola amigo.', 'masc')
    assert res['variantes'] is None and res['vista']


def test_flujo_marcar_filtros_y_fichero_local(app):
    i = hallar(app, 53)
    assert app.celda(i)['flujo'] == 'sin' and app.celda(i)['clase'] == 'Misiones'
    app.flujo_marcar({'estado': 'hecho', 'ids': [i]})
    assert app.celda(i)['flujo'] == 'hecho' and os.path.exists(os.path.join(app.cfg.home, 'flujo.json'))
    r = app.flujo_marcar({'estado': 'por_hacer', 'tabla': {'hoja': HOJA, 'estados': ['verde'], 'clase': 'Misiones'}})
    assert r['marcadas'] > 1 and app.flujo.totales()['por_hacer'] == r['marcadas']
    assert app.flujo.estado(HOJA, *[app.base.q('SELECT row,sub,col FROM celdas WHERE id=?', (i,))[0][k] for k in ('row', 'sub', 'col')]) == 'por_hacer'
    b = app.buscar({'texto': 'Gridania', 'campos': ['es'], 'flujo': 'por_hacer', 'clase': 'Misiones'}); assert b['total'] > 0
    assert app.buscar({'texto': 'Gridania', 'campos': ['es'], 'clase': 'Objetos'})['total'] == 0
    e = app.flujo_exportar(os.path.join(app.cfg.home, 'out')); assert e['filas'] == r['marcadas']
    app.flujo_marcar({'estado': 'sin', 'tabla': {'hoja': HOJA}})
    assert app.flujo.totales() == {'por_hacer': 0, 'hecho': 0}
    assert app.flujo_importar(open(e['ruta'], encoding='utf-8').read())['importadas'] == e['filas']
    # nunca en traducciones/
    assert not os.path.exists(os.path.join(app.cfg.repo_dir, 'flujo.json'))


def test_misiones_y_hoja_celdas(app):
    m = app.misiones()
    assert m['total'] == 1 and m['misiones'][0]['hoja'] == HOJA and m['misiones'][0]['total'] > 10
    assert app.misiones(q='noexiste')['total'] == 0 and app.misiones(clase='Escenas')['total'] == 0
    h = app.hoja_celdas(HOJA); ks = [(c['row'], -1 if c['sub'] is None else c['sub'], c['col']) for c in h['celdas']]
    assert ks == sorted(ks) and len(ks) == m['misiones'][0]['total']


def test_sin_saltos_y_suavizar_en_bloque_con_deshacer(app):
    i = hallar(app, 53); t = app.celda(i)['es_texto']
    r = app.sin_saltos_texto(i, t)
    if r['cambia']: assert r['texto'].count('\n') <= t.count('\n')
    # bloque: previa no escribe; aplicar y deshacer restauran el es original
    antes = app.base.q("SELECT id,es_json FROM celdas WHERE hoja=? ORDER BY id", (HOJA,))
    sel = {'tabla': {'hoja': HOJA, 'estados': ['verde']}}
    for modo in ('suavizar', 'sin_saltos', 'sin_saltos_suavizar'):
        p = app.suavizar_previa(dict(sel, modo=modo)); assert app.estado()['ediciones']['filas'] == 0
        assert p['n_cambios'] == len(p['cambios']) or p['n_cambios'] > 100
    with pytest.raises(ValueError): app.suavizar_previa(dict(sel, modo='raro'))
    ap = app.suavizar_aplicar(dict(sel, modo='sin_saltos_suavizar'))
    if ap['aplicadas']:
        assert app.estado()['ediciones']['filas'] == ap['aplicadas']
        d = app.suavizar_deshacer(); assert d['restauradas'] == ap['aplicadas']
        despues = app.base.q("SELECT id,es_json FROM celdas WHERE hoja=? ORDER BY id", (HOJA,))
        assert [json.loads(a['es_json']) if a['es_json'] else None for a in antes] == [json.loads(a['es_json']) if a['es_json'] else None for a in despues]
    else:
        with pytest.raises(ValueError): app.suavizar_deshacer()


def test_motor_sin_saltos_quita_solo_extras(app):
    m = app.motor(); probados = 0
    for r in app.base.q("SELECT hoja,row,sub,col,es_json FROM celdas WHERE es_json IS NOT NULL"):
        c = m.contexto(r['hoja'], r['row'], r['sub'], r['col']); es = json.loads(r['es_json'])
        trozos = es if isinstance(es, list) else [es]
        for k, x in enumerate(trozos):
            if not isinstance(x, str) or ' ' not in x.strip(' '): continue
            pos = x.index(' ', 1) if ' ' in x[1:] else -1
            if pos < 1: continue
            cand_t = list(trozos); cand_t[k] = x[:pos] + '<NewLine>' + x[pos + 1:]
            cand = cand_t if isinstance(es, list) else cand_t[0]
            if not m._validar(c, cand): continue       # solo cuando el contrato admite ese NewLine extra
            nuevo = m.sin_saltos(c, cand); probados += 1
            assert nuevo is not None, 'el salto extra admitido debe poder quitarse'
            if isinstance(es, list): assert len(nuevo) == len(es)
            assert nuevo == es or m._validar(c, nuevo)
            assert (nuevo[k] if isinstance(es, list) else nuevo).replace('<NewLine>', '') == (nuevo[k] if isinstance(es, list) else nuevo)
            break
        if probados >= 5: break
    assert probados > 0
    # lo que el japones exige no se borra: sobre las traducciones tal cual, el resultado sigue siendo valido
    for r in app.base.q("SELECT hoja,row,sub,col,es_json FROM celdas WHERE es_json IS NOT NULL LIMIT 60"):
        c = m.contexto(r['hoja'], r['row'], r['sub'], r['col']); es = json.loads(r['es_json']); nuevo = m.sin_saltos(c, es)
        assert nuevo is None or m._validar(c, nuevo)


def test_servidor_rutas_nuevas(app):
    from gridania_editor.servidor import Servidor
    s = Servidor(app); s.arrancar()
    try:
        def call(ruta, cuerpo=None):
            rq = urllib.request.Request(s.url.rstrip('/') + ruta, headers={'X-K': s.clave, 'Content-Type': 'application/json'}, data=None if cuerpo is None else json.dumps(cuerpo).encode())
            return json.loads(urllib.request.urlopen(rq).read())
        d = call('/api/celdas?estados=verde&clase=Misiones&flujo=sin')
        assert d['total'] > 0 and 'contadores_flujo' in d and 'contadores_clase' in d and d['filas'][0]['clase'] == 'Misiones'
        assert call('/api/celdas?estados=verde&clase=Objetos')['total'] == 0
        i = d['filas'][0]['id']
        assert call('/api/flujo_marcar', {'estado': 'hecho', 'ids': [i]})['marcadas'] == 1
        assert call('/api/celdas?flujo=hecho')['total'] == 1
        assert call('/api/estado')['flujo']['hecho'] == 1 and 'Misiones' in call('/api/estado')['clases']
        assert call('/api/misiones?q=ManFst')['total'] == 1 and call('/api/hoja_celdas?hoja=' + HOJA.replace('/', '%2F'))['celdas']
        pv = call('/api/preview', {'id': i, 'texto': app.celda(i)['es_texto']}); assert 'variantes' in pv and 'suavizado' in pv
        assert call('/api/sin_saltos_texto', {'id': i, 'texto': app.celda(i)['es_texto']})['texto']
        assert call('/api/suavizar_previa', {'ids': [i], 'modo': 'suavizar'})['omitidas'] >= 0
    finally:
        s.parar()


def _celdas_con_cambio(app, modo='sin_saltos_suavizar'):
    sel = {'tabla': {'hoja': HOJA, 'estados': ['verde']}}
    return sel, app.suavizar_previa(dict(sel, modo=modo))


def _estado_celdas(app):
    return {r['id']: (r['es_json'], r['origen'], r['editada'], r['h_es']) for r in app.base.q('SELECT id,es_json,origen,editada,h_es FROM celdas WHERE hoja=?', (HOJA,))}


def _forzar_cambio(app):
    """siembra un salto extra admitido por el contrato en una celda verde (solo en la base, origen intacto) y devuelve (cuerpo de seleccion, id)"""
    m = app.motor(); hallada = []
    for r in app.base.q("SELECT id,hoja,row,sub,col,es_json FROM celdas WHERE es_json IS NOT NULL AND estado='verde' ORDER BY id"):
        c = m.contexto(r['hoja'], r['row'], r['sub'], r['col']); es = json.loads(r['es_json'])
        trozos = es if isinstance(es, list) else [es]
        for k, x in enumerate(trozos):
            if not isinstance(x, str) or ' ' not in x[1:]: continue
            pos = x.index(' ', 1); t = list(trozos); t[k] = x[:pos] + '<NewLine>' + x[pos + 1:]
            cand = t if isinstance(es, list) else t[0]
            if m._validar(c, cand) and m.sin_saltos(c, cand) is not None: hallada.append((r['id'], cand)); break
        if hallada: break
    assert hallada, 'el mini repo debe tener una celda que admita un salto extra'
    i, cand = hallada[0]
    app.base.x('UPDATE celdas SET es_json=?, es=? WHERE id=?', (json.dumps(cand, ensure_ascii=False), indexer_plano(cand), i))
    sel = {'ids': [i], 'modo': 'sin_saltos'}
    assert app.suavizar_previa(sel)['n_cambios'] == 1
    return sel, i


def test_suavizado_solo_cambia_saltos_y_espacios(app):
    m = app.motor()
    for modo in ('suavizar', 'sin_saltos', 'sin_saltos_suavizar'):
        c = app._suavizar_candidatas({'tabla': {'hoja': HOJA, 'estados': ['verde']}, 'modo': modo})[0]
        for x in c: assert app._solo_saltos(x['es_antes'], x['es_despues'])
    assert app._solo_saltos(['a b', 'c'], ['a<NewLine>b ', 'c'])
    assert not app._solo_saltos(['a...', 'c'], ['a…', 'c'])
    assert not app._solo_saltos(['a b c'], ['a b', 'c'])
    assert not app._solo_saltos('x', ['x'])
    assert not app._solo_saltos(['ab cd'], ['a b cd'])      # partir palabra
    assert not app._solo_saltos(['a b'], ['ab'])            # fusionar palabras
    assert not app._solo_saltos(['a b'], ['b a'])           # reordenar
    assert not app._solo_saltos(['<Gender>a b<GenderElse>c<GenderEnd>', 'd'], ['<Gender>a', 'b<GenderElse>c<GenderEnd> d'])   # macro partida
    assert not app._solo_saltos(['a b', 'c'], ['a b c', ''])   # trozo vaciado
    assert not app._solo_saltos(['a b', ''], ['a', 'b'])       # trozo vacio llenado
    assert app._solo_saltos(['a b c', 'd'], ['a b', 'c d'])    # mover palabras sin macros
    assert app._solo_saltos(['<Gender>a b<GenderElse>c<GenderEnd> d', 'e'], ['<Gender>a<NewLine>b<GenderElse>c<GenderEnd><NewLine>d', 'e'])
    assert app._solo_saltos(['a b', 'c'], ['a', 'b<NewLine#3>c'])  # salto numerado
    assert app._solo_saltos(['a b', 'c'], ['a', 'b c'])     # mover palabras entre trozos
    assert not app._solo_saltos(['a b', 'c'], ['a', 'bc'])  # fusion
    assert not app._solo_saltos(['ab', 'c'], ['a', 'b c'])  # particion
    assert not app._solo_saltos(['a b', 'c'], ['c', 'a b']) # reorden entre trozos
    assert not app._solo_saltos(['a b', 'c'], ['a b c'])    # distinto n. de trozos


def test_aplicar_deshacer_restaura_texto_y_origen(app):
    sel, i = _forzar_cambio(app); antes = _estado_celdas(app)
    ap = app.suavizar_aplicar(sel); assert ap['aplicadas'] == 1
    assert _estado_celdas(app)[i][1] == 'sesion' and app.estado()['ediciones']['filas'] == 1
    d = app.suavizar_deshacer(); assert d['restauradas'] == 1 and d['cambiadas_despues'] == 0
    assert _estado_celdas(app) == antes
    assert app.estado()['ediciones']['filas'] == 0


def test_deshacer_tras_edicion_manual_avisa_y_no_pisa(app):
    sel, i = _forzar_cambio(app)
    app.suavizar_aplicar(sel)
    t = app.celda(i)['es_texto'] + ' '
    assert app.guardar(i, t)['guardado']
    manual = app.base.q('SELECT es_json FROM celdas WHERE id=?', (i,))[0]['es_json']
    d = app.suavizar_deshacer()
    assert d['restauradas'] == 0 and d['cambiadas_despues'] == 1   # avisa de la celda editada a mano
    assert app.base.q('SELECT es_json FROM celdas WHERE id=?', (i,))[0]['es_json'] == manual   # y no la pisa


def test_deshacer_formato_antiguo_se_salta_y_no_bloquea(app):
    ruta = app._ruta_deshacer()
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump([{'fecha': 'x', 'celdas': [{'hoja': 'H', 'row': 1, 'sub': None, 'col': 0, 'es_antes': ['a']}]}], f)
    d = app.suavizar_deshacer()
    assert d['restauradas'] == 0 and d['incompatibles'] == 1 and d['quedan'] == 0
    assert json.load(open(ruta, encoding='utf-8')) == []
    with pytest.raises(ValueError): app.suavizar_deshacer()


def test_ruta_segura_ignora_mayusculas_segun_plataforma(app, monkeypatch):
    ok = os.path.join(app.cfg.home, 'x.tsv')
    assert app._ruta_segura(ok)
    monkeypatch.setattr(os.path, 'normcase', lambda s: s.lower())
    monkeypatch.setattr(os.path, 'realpath', lambda s: s if s != app.cfg.home else app.cfg.home.upper())
    assert app._ruta_segura(ok)


def indexer_plano(es):
    from gridania_editor import indexer
    return indexer.plano(es)


def indexer_obtener(app, i):
    from gridania_editor import indexer
    return indexer.obtener(app.base, i)


def test_rutas_flujo_restringidas(app, tmp_path):
    for malo in ('relativa/x', str(tmp_path / 'home' / '..' / 'fuera'), '/etc'):
        with pytest.raises(ValueError): app.flujo_exportar(malo)
    with pytest.raises(ValueError): app.flujo_importar(ruta='/etc/passwd')
    with pytest.raises(ValueError): app.flujo_importar(ruta=str(tmp_path / 'home' / '..' / 'x.tsv'))
    ok = app.flujo_exportar(str(tmp_path / 'home' / 'sub_exp')); assert os.path.isfile(ok['ruta'])
    assert app.flujo_importar(ruta=ok['ruta'])['ignoradas'] == 0
    elegida = tmp_path / 'elegida'; elegida.mkdir(); app.cfg.actualizar({'carpeta_dat': str(elegida)})
    assert os.path.isfile(app.flujo_exportar(str(elegida))['ruta'])


def test_misiones_ignora_marcas_huerfanas(app):
    i = hallar(app, 53); app.flujo_marcar({'estado': 'hecho', 'ids': [i]})
    app.flujo.poner([(HOJA, 99999, None, 1), ('no/existe', 1, None, 1)], 'por_hacer')
    m = app.misiones(); assert m['misiones'][0]['hecho'] == 1 and m['misiones'][0]['por_hacer'] == 0


def test_servidor_flujo_http_y_rutas_rechazadas(app):
    from gridania_editor.servidor import Servidor
    s = Servidor(app); s.arrancar()
    try:
        def call(ruta, cuerpo):
            rq = urllib.request.Request(s.url.rstrip('/') + ruta, headers={'X-K': s.clave, 'Content-Type': 'application/json'}, data=json.dumps(cuerpo).encode())
            try: return 200, json.loads(urllib.request.urlopen(rq).read())
            except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
        cod, e = call('/api/flujo_exportar', {}); assert cod == 200 and e['filas'] == 0
        assert call('/api/flujo_exportar', {'destino': '/etc'})[0] == 400
        assert call('/api/flujo_importar', {'ruta': '/etc/passwd'})[0] == 400
        cod, im = call('/api/flujo_importar', {'contenido': 'hoja\trow\tsub\tcol\testado\n%s\t53\t\t1\thecho\n' % HOJA}); assert cod == 200 and im['importadas'] == 1
        assert call('/api/suavizar_deshacer', {})[0] == 400
    finally:
        s.parar()


def test_ui_escapa_comillas_y_apostrofes():
    ui = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gridania_editor', 'ui', 'index.html')
    linea = [l for l in open(ui, encoding='utf-8') if l.startswith('function esc(')][0]
    assert '&quot;' in linea and '&#39;' in linea and '&lt;' in linea


def test_ruta_segura_con_carpeta_dat(app, tmp_path):
    dat = tmp_path / 'salida_dat'; dat.mkdir()
    fuera = tmp_path / 'otra'; fuera.mkdir()
    with pytest.raises(ValueError): app._ruta_segura(str(dat / 'x.tsv'))               # sin carpeta_dat configurada
    app.cfg.actualizar({'carpeta_dat': str(dat)})
    assert app._ruta_segura(str(dat / 'x.tsv')) and app._ruta_segura(str(dat))
    with pytest.raises(ValueError): app._ruta_segura(str(fuera / 'x.tsv'))
    with pytest.raises(ValueError): app._ruta_segura(str(dat / '..' / 'otra' / 'x.tsv'))
    with pytest.raises(ValueError): app._ruta_segura(str(tmp_path / 'salida_dat_hermana' / 'x.tsv'))   # prefijo comun no cuenta
