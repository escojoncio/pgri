"""Arranque de la ventana: la ventana se pide lo primero, cada fase queda en el registro, vigilante con navegador de reserva, migracion rapida, carpeta junto al programa."""
import json, os, subprocess, sys, threading, time, types, urllib.request
import pytest
from conftest import EDITOR
from gridania_editor import config, indexer, registro


def _log(home): return open(os.path.join(home, 'editor.log'), encoding='utf-8').read()


def _base_antigua(ruta, n, hojas=60):
    import sqlite3
    con = sqlite3.connect(ruta)
    con.executescript('''CREATE TABLE celdas (id INTEGER PRIMARY KEY, hoja TEXT NOT NULL, row INTEGER NOT NULL, sub INTEGER, col INTEGER NOT NULL,
      estado TEXT NOT NULL, h TEXT, ja TEXT, fr TEXT, es TEXT, es_json TEXT, origen TEXT, h_es TEXT, editada INTEGER DEFAULT 0); CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);''')
    nombres = ['quest/000/Q%d' % i for i in range(hojas // 2)] + ['Item%d' % i for i in range(hojas // 2)]
    con.executemany('INSERT INTO celdas(hoja,row,sub,col,estado,ja,fr,es) VALUES (?,?,?,?,?,?,?,?)', [(nombres[i % len(nombres)], i, None, 0, 'rojo', 'j' * 50, 'f' * 50, '') for i in range(n)])
    con.commit(); con.close()
    return nombres


def test_migracion_clase_por_sql_en_tramos(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, 'TRAMO_MIGRACION', 1000)
    nombres = _base_antigua(str(tmp_path / 'e.db'), 20000)
    b = indexer.Base(str(tmp_path / 'e.db')); assert 'clase' in b.migrados
    avances = []; t0 = time.time()
    b.migrar_datos(lambda f, h=0, t=0: avances.append((f, h, t)))
    assert time.time() - t0 < 10
    assert {r['hoja']: r['clase'] for r in b.q('SELECT DISTINCT hoja, clase FROM celdas')} == {h: ('Misiones' if h.startswith('quest') else 'Objetos') for h in nombres}
    prog = [a for a in avances if a[0] == 'migrando base de datos']
    assert len(prog) >= 10 and prog[-1][1] == prog[-1][2]            # progreso por tramos, no hoja a hoja
    assert not b.q("SELECT name FROM sqlite_temp_master WHERE name='tmp_clases'")


def test_la_base_se_lee_entre_tramos_de_la_migracion(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, 'TRAMO_MIGRACION', 500)
    _base_antigua(str(tmp_path / 'e.db'), 5000)
    b = indexer.Base(str(tmp_path / 'e.db')); lecturas = []
    def av(f, h=0, t=0):
        if f == 'migrando base de datos':
            r = {}; th = threading.Thread(target=lambda: r.update(n=b.q('SELECT COUNT(*) n FROM celdas')[0]['n']), daemon=True); th.start(); th.join(3); lecturas.append(r.get('n'))
    b.migrar_datos(av)
    assert lecturas and all(n == 5000 for n in lecturas)


def test_fases_activas_y_vigilancia_registran(tmp_path):
    lg = registro.iniciar(str(tmp_path), 'test'); import logging
    rutas = []
    h = logging.FileHandler(str(tmp_path / 'v.log'), encoding='utf-8'); lg.addHandler(h)
    try:
        listo = threading.Event()
        with registro.fase('fase larga'):
            assert any(x.startswith('fase larga') for x in registro.fases_activas())
            registro.etapa('esperando algo')
            registro.vigilar_arranque(listo.is_set, paso=0.1); time.sleep(0.45)
        assert not registro.fases_activas()
        listo.set(); time.sleep(0.3); h.flush()
    finally: lg.removeHandler(h); h.close()
    t = open(str(tmp_path / 'v.log'), encoding='utf-8').read()
    assert 'fase fase larga: inicio' in t and 'vigilancia: etapa=' in t and 'esperando algo' in t and 'fase larga (' in t and 'fase fase larga:' in t


def test_faulthandler_a_fichero(tmp_path):
    registro.iniciar(str(tmp_path), 'test')
    f = registro.activar_faulthandler(str(tmp_path), cada=1)
    try:
        assert f is not None; time.sleep(1.5); f.flush()
        assert 'most recent call first' in open(str(tmp_path / 'faulthandler.log'), encoding='utf-8').read()
    finally:
        registro.parar_faulthandler(); import faulthandler; faulthandler.disable()


class ProcFalso(object):
    """Popen falso (el pid es solo una pista): 'ok' = la ventana pide la pagina y vive; 'cuelga' = vive sin pedir nada; 'muere' = termina al instante sin pedir nada;
    'delega' = el lanzador sale al instante pero la ventana (otro proceso) SI pide la pagina"""
    def __init__(self, url, modo):
        self.url = url; self.modo = modo; self.pid = 4242; self._fin = threading.Event(); self.terminado = False; self.cod = None
        if modo == 'muere': self.cod = 1; self._fin.set()
        if modo == 'delega': self.cod = 0; self._fin.set()
        if modo in ('ok', 'delega'): threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=5).read(), daemon=True).start()
    def wait(self, timeout=None):
        if not self._fin.wait(timeout): raise subprocess.TimeoutExpired('x', timeout)
        return self.cod
    def poll(self): return self.cod if self._fin.is_set() else None
    def terminate(self): self.terminado = True; self.cod = 0; self._fin.set()
    def cerrar(self): self.cod = 0; self._fin.set()          # el usuario cierra la ventana


class LanzadorFalso(object):
    def __init__(self, modo): self.modo = modo; self.llamadas = []; self.proc = None
    def __call__(self, url, home):
        self.llamadas.append((url, home, time.time()))
        if self.modo == 'sin_edge': return None
        self.proc = ProcFalso(url, self.modo); return self.proc


def _lanzar(tmp_path, monkeypatch, modo, espera=15):
    from gridania_editor import app as app_mod
    monkeypatch.setattr(app_mod, 'GRACIA_CIERRE_S', 0.6); monkeypatch.setattr(app_mod, 'PASO_VIGILANTE_S', 0.05); monkeypatch.setattr(app_mod.ventana, 'perfil_libre', lambda *a, **k: True)
    lz = LanzadorFalso(modo); monkeypatch.setattr(app_mod, 'LANZADOR', lz)
    abiertas = []; monkeypatch.setattr(app_mod.webbrowser, 'open', abiertas.append); monkeypatch.setattr(app_mod, 'ESPERA_UI_S', espera)
    srvs = []
    orig = app_mod.Servidor
    monkeypatch.setattr(app_mod, 'Servidor', lambda *a, **k: srvs.append(orig(*a, **k)) or srvs[-1])
    home = str(tmp_path / 'datos'); r = {}
    t0 = time.time()
    th = threading.Thread(target=lambda: r.update(cod=app_mod.main(['--carpeta', home, '--puerto', '0'])), daemon=True, name='principal'); th.start()
    return app_mod, lz, lz.llamadas, abiertas, srvs, home, th, r, t0


@pytest.fixture(autouse=True)
def _limpiar_log():
    import logging
    yield
    lg = logging.getLogger('gridania')
    for h in list(lg.handlers): lg.removeHandler(h); h.close()
    lg._ge_listo = False


def _esperar(cond, n=200):
    for _ in range(n):
        if cond(): return True
        time.sleep(0.05)
    return False


def _post(srv, ruta, clave='ok'):
    """POST como la UI: sendBeacon con la clave en ?k= (clave='ok' = la buena). -> codigo HTTP"""
    k = srv.clave if clave == 'ok' else clave
    rq = urllib.request.Request(srv.url + ruta.lstrip('/') + ('?k=' + k if k else ''), data=b'', method='POST')
    try: return urllib.request.urlopen(rq, timeout=5).status
    except urllib.error.HTTPError as x: return x.code


def _latido(srv):
    rq = urllib.request.Request(srv.url + 'api/latido', headers={'X-K': srv.clave}); return urllib.request.urlopen(rq, timeout=5).status


def test_la_ventana_se_lanza_y_al_cerrarla_se_cierra_limpio(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'ok')
    assert _esperar(lambda: llamadas) and llamadas[0][2] - t0 < 1.5 and llamadas[0][1] == home
    assert _esperar(lambda: srvs and srvs[0].ui_cargada.is_set() and srvs[0].app.arranque['listo'])
    assert th.is_alive() and abiertas == []                      # mientras la ventana vive, el proceso sigue
    assert _post(srvs[0], '/api/cierre') == 200                  # el usuario cierra la ventana: sendBeacon
    th.join(15); assert not th.is_alive() and r['cod'] == 0 and abiertas == []
    t = _log(home)
    assert 'fase lanzar ventana: inicio' in t and 'primera peticion GET / de la UI' in t and 'ventana cerrada por el usuario: cierre limpio' in t
    assert 'ventana: resultado salir' in t and 'faulthandler activo' in t and 'faulthandler: volcados periodicos cancelados' in t
    with pytest.raises(Exception): urllib.request.urlopen(srvs[0].url, timeout=2)      # servidor parado


def test_si_la_ventana_no_carga_se_abre_el_navegador_una_vez_y_se_termina_la_ventana(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'cuelga', espera=0.5)
    assert _esperar(lambda: abiertas)
    assert abiertas == [srvs[0].url] and not srvs[0].salir.is_set() and _esperar(lambda: lz.proc.terminado)      # sin dos UIs
    rq = urllib.request.Request(srvs[0].url + 'api/estado', headers={'X-K': srvs[0].clave})
    assert urllib.request.urlopen(rq, timeout=5).status == 200                                   # el servidor sigue vivo
    time.sleep(0.5); assert th.is_alive() and len(abiertas) == 1                                  # cerrar la ventana Edge muerta no cierra el editor
    srvs[0].salir.set(); th.join(20)
    assert 'no ha cargado' in _log(home)


def test_sin_edge_ni_chrome_abre_el_navegador_y_mantiene_el_servidor(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'sin_edge')
    assert _esperar(lambda: abiertas) and abiertas == [srvs[0].url] and 'No se ha encontrado Microsoft Edge' in srvs[0].app.aviso
    assert th.is_alive(); srvs[0].salir.set(); th.join(15); assert not th.is_alive() and r['cod'] == 0


def test_lanzador_que_muere_sin_ventana_cae_al_navegador_tras_el_plazo(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'muere', espera=0.6)
    assert time.time() - t0 < 0.5 or not abiertas             # NO abre otro navegador de inmediato: espera el plazo del vigilante
    assert _esperar(lambda: abiertas) and len(abiertas) == 1 and 'no ha cargado' in srvs[0].app.aviso and 'Salir' in srvs[0].app.aviso
    srvs[0].salir.set(); th.join(15)


def test_boton_salir_termina_la_ventana_y_el_proceso(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'ok')
    assert _esperar(lambda: srvs and srvs[0].ui_cargada.is_set())
    srvs[0].salir.set(); th.join(15); assert not th.is_alive() and r['cod'] == 0 and lz.proc.terminado


def test_navegador_forzado_no_lanza_ventana(tmp_path, monkeypatch):
    from gridania_editor import app as app_mod
    lz = LanzadorFalso('ok'); monkeypatch.setattr(app_mod, 'LANZADOR', lz)
    abiertas = []; monkeypatch.setattr(app_mod.webbrowser, 'open', abiertas.append)
    srvs = []; orig = app_mod.Servidor
    monkeypatch.setattr(app_mod, 'Servidor', lambda *a, **k: srvs.append(orig(*a, **k)) or srvs[-1])
    th = threading.Thread(target=lambda: app_mod.main(['--navegador', '--carpeta', str(tmp_path / 'd')]), daemon=True); th.start()
    assert _esperar(lambda: abiertas) and lz.llamadas == []; srvs[0].salir.set(); th.join(15)


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='usa /proc')
def test_arranque_real_sin_procesos_hijos_ni_segundo_log(tmp_path):
    """simula el exe: run_editor.py como __main__ con freeze_support primero; ningun proceso hijo ni segundo 'arranque' en el registro"""
    home = str(tmp_path / 'd')
    p = subprocess.Popen([sys.executable, os.path.join(EDITOR, 'run_editor.py'), '--sin-abrir', '--carpeta', home], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if os.path.exists(os.path.join(home, 'editor.log')) and 'Editor Gridania en' in _log(home): break
            time.sleep(0.1)
        time.sleep(2)
        hijos = [d for d in os.listdir('/proc') if d.isdigit() and open('/proc/%s/stat' % d).read().rsplit(')', 1)[1].split()[1] == str(p.pid)]
        assert hijos == []
        assert _log(home).count('arranque: editor') == 1
    finally:
        p.terminate(); p.wait(10)
    assert open(os.path.join(EDITOR, 'run_editor.py')).read().index('freeze_support') < open(os.path.join(EDITOR, 'run_editor.py')).read().index('from gridania_editor')


def test_carpeta_junto_al_programa(tmp_path, monkeypatch):
    monkeypatch.delenv('GRIDANIA_EDITOR_HOME', raising=False); monkeypatch.setattr(config, 'AVISO_CARPETA', '')
    exe = tmp_path / 'prog'; exe.mkdir()
    monkeypatch.setattr(sys, 'frozen', True, raising=False); monkeypatch.setattr(sys, 'executable', str(exe / 'GridaniaEditor.exe'))
    assert config.carpeta_trabajo() == str(exe / 'datos') and os.path.isdir(exe / 'datos') and config.AVISO_CARPETA == ''
    monkeypatch.setenv('GRIDANIA_EDITOR_HOME', str(tmp_path / 'otra')); assert config.carpeta_trabajo() == str(tmp_path / 'otra')
    monkeypatch.delenv('GRIDANIA_EDITOR_HOME')
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    assert config.carpeta_trabajo() == os.path.join(EDITOR, 'datos')


def test_carpeta_no_escribible_cae_a_documentos_con_aviso(tmp_path, monkeypatch):
    monkeypatch.delenv('GRIDANIA_EDITOR_HOME', raising=False); monkeypatch.setattr(config, 'AVISO_CARPETA', '')
    monkeypatch.setattr(config, '_escribible', lambda d: False)
    monkeypatch.setenv('HOME', str(tmp_path / 'home')); monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home')); (tmp_path / 'home' / 'Documents').mkdir(parents=True)
    r = config.carpeta_trabajo()
    assert r == str(tmp_path / 'home' / 'Documents' / 'GridaniaEditor') and 'no es escribible' in config.AVISO_CARPETA


def test_migracion_desde_la_ubicacion_antigua(tmp_path):
    ant, nue = tmp_path / 'ant', tmp_path / 'datos'
    (ant / 'ediciones' / 'x').mkdir(parents=True); (ant / 'ediciones' / 'x' / 'a.jsonl').write_text('1')
    for n in ('config.json', 'flujo.json', 'suavizado_deshacer.json', 'editor.db', 'instancia.lock'): (ant / n).write_text('z')
    (ant / 'repo').mkdir(); (ant / 'repo' / 'r').write_text('r')
    nue.mkdir(); (nue / 'editor.log').write_text('log')
    c = config.migrar_antigua(str(nue), str(ant))
    assert sorted(c) == ['config.json', 'ediciones', 'flujo.json', 'suavizado_deshacer.json']
    assert (nue / 'ediciones' / 'x' / 'a.jsonl').read_text() == '1' and (ant / 'ediciones' / 'x' / 'a.jsonl').exists() and (ant / 'config.json').exists()   # sin borrar
    (nue / 'extra').write_text('x'); assert config.migrar_antigua(str(nue), str(ant)) == []                  # destino con datos: no se toca
    assert config.migrar_antigua(str(nue), str(tmp_path / 'noexiste')) == []


def test_ruta_segura_apunta_a_la_nueva_raiz(tmp_path):
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'datos'), repo_override=str(tmp_path / 'r'), diferir=True)
    assert a._ruta_segura(str(tmp_path / 'datos' / 'exportado' / 'x.tsv'))
    with pytest.raises(ValueError): a._ruta_segura(str(tmp_path / 'fuera' / 'x.tsv'))


def test_vigencia_espera_a_la_ui_y_arranque_idempotente(tmp_path):
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'datos'), repo_override=str(tmp_path / 'r'), diferir=True)
    ui = threading.Event(); a.arrancar_fondo(ui); a.arrancar_fondo(ui)
    for _ in range(100):
        if a.arranque['listo']: break
        time.sleep(0.05)
    assert a.arranque['listo'] and a.vigencia is None          # la vigencia espera a la UI: no esta en el camino de la ventana
    ui.set()
    for _ in range(100):
        if a.vigencia is not None: break
        time.sleep(0.05)
    assert a.vigencia['motivo'] == 'sin_repo'
