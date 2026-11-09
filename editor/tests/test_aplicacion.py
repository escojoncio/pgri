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
