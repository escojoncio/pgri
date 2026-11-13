"""Segunda ronda de arranque: carrera ventana/navegador con un unico ganador, destroy bloqueable, sin WebView2, plazo ampliable, migracion tras la UI, token DPAPI, OneDrive, faulthandler acotado."""
import json, os, subprocess, sys, textwrap, threading, time, urllib.request
import pytest
from gridania_editor import config, registro
from test_arranque import _lanzar, _log, _limpiar_log  # noqa: F401  (fixture autouse)


def test_ventana_creada_tarde_se_cancela_y_no_hay_segunda_ui(tmp_path, monkeypatch):
    app_mod, wv, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'cuelga', espera=0.5)
    for _ in range(100):
        if abiertas: break
        time.sleep(0.05)
    assert len(abiertas) == 1
    wv.liberar.set()                                          # create_window vuelve DESPUES de abrirse el navegador
    for _ in range(100):
        if getattr(wv, 'win', None) is not None and wv.win.cerrada.is_set(): break
        time.sleep(0.05)
    assert wv.win.cerrada.is_set()                            # la ventana tardia se destruye
    time.sleep(0.3)
    assert [x[0] for x in llamadas] == ['create_window']      # start NO se llama: una sola UI
    assert len(abiertas) == 1
    srvs[0].salir.set(); th.join(20); assert not th.is_alive()


def test_sin_runtime_webview2_abre_el_navegador_al_instante(tmp_path, monkeypatch):
    from gridania_editor import app as app_mod
    monkeypatch.setattr(app_mod, '_sin_runtime', lambda: True)
    app_mod, wv, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'ok', espera=30)
    for _ in range(100):
        if abiertas: break
        time.sleep(0.05)
    assert len(abiertas) == 1 and time.time() - t0 < 5 and llamadas == []          # sin esperar el plazo y sin crear ventana
    srvs[0].salir.set(); th.join(20)
    assert 'WebView2 Runtime' in _log(home)


def _stubs():
    class Ev(object):
        def __init__(self): self.e = threading.Event()
        def is_set(self): return self.e.is_set()
    class Srv(object):
        def __init__(self): self.ui_cargada = threading.Event(); self.salir = threading.Event()
    return Ev, Srv


def test_destroy_bloqueado_no_impide_abrir_el_navegador_primero(tmp_path):
    from gridania_editor import app as app_mod
    Ev, Srv = _stubs(); libre = threading.Event(); orden = []
    class Win(object):
        events = type('E', (), {'closed': Ev()})()
        def destroy(self): orden.append('destroy'); libre.wait(30)          # el hilo de la GUI esta colgado
    class Ap(object):
        aviso = ''; cfg = type('C', (), {'home': str(tmp_path)})()
    srv, est = Srv(), {'navegador': False, 'win': Win()}
    t0 = time.time()
    app_mod._vigilar_ui(srv, Ap(), est, 'u', espera=0.1, paso=0.02, abrir=lambda u: orden.append('abrir'))
    assert orden[:2] == ['abrir', 'destroy'] and time.time() - t0 < 8 and est['navegador']      # vuelve aunque destroy siga bloqueado
    libre.set()


def test_plazo_se_amplia_con_senal_de_vida(tmp_path):
    from gridania_editor import app as app_mod
    Ev, Srv = _stubs()
    class Ap(object):
        aviso = ''; cfg = type('C', (), {'home': str(tmp_path)})()
    # con senal de vida y la UI carga dentro de la ampliacion: no se abre nada
    srv, est, ab = Srv(), {'navegador': False, 'vida': time.time()}, []
    threading.Timer(0.4, srv.ui_cargada.set).start()
    app_mod._vigilar_ui(srv, Ap(), est, 'u', espera=0.1, paso=0.02, abrir=ab.append, ampliacion=1.0, tope=2.0)
    assert ab == []
    # con senal de vida pero nunca carga: se abre al agotar la ampliacion (no antes)
    srv, est, ab = Srv(), {'navegador': False, 'vida': time.time()}, []; t0 = time.time()
    app_mod._vigilar_ui(srv, Ap(), est, 'u', espera=0.1, paso=0.02, abrir=ab.append, ampliacion=0.5, tope=2.0)
    assert ab == ['u'] and time.time() - t0 >= 0.45
    # el tope manda
    srv, est, ab = Srv(), {'navegador': False, 'vida': time.time()}, []; t0 = time.time()
    app_mod._vigilar_ui(srv, Ap(), est, 'u', espera=0.1, paso=0.02, abrir=ab.append, ampliacion=60, tope=0.5)
    assert ab == ['u'] and time.time() - t0 < 2


def test_aplicacion_diferida_no_abre_la_base_y_estado_responde(tmp_path):
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'd'), repo_override=str(tmp_path / 'r'), diferir=True)
    assert a._base is None and not os.path.exists(a.cfg.db_ruta)
    e = a.estado(); assert e['arranque']['listo'] is False and e['indice'] is None
    a.arrancar_fondo(threading.Event())
    for _ in range(100):
        if a.arranque['listo']: break
        time.sleep(0.05)
    assert a._base is not None and a.base is a._base


def test_migracion_antigua_corre_tras_ui_cargada_y_recarga_ajustes(tmp_path):
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'd'), repo_override=str(tmp_path / 'r'), diferir=True)
    ui = threading.Event(); hechos = []
    def tras():
        hechos.append(time.time()); json.dump({'repo': 'x/y'}, open(os.path.join(a.cfg.home, 'config.json'), 'w')); return ['config.json']
    a.arrancar_fondo(ui, tras); time.sleep(0.5)
    assert hechos == []                                       # no compite con la inicializacion de la ventana
    ui.set()
    for _ in range(100):
        if hechos: break
        time.sleep(0.05)
    time.sleep(0.3)
    assert hechos and a.cfg['repo'] == 'x/y'


def test_token_cifrado_con_dpapi_simulado(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'dpapi_disponible', lambda: True)
    monkeypatch.setattr(config, 'dpapi_proteger', lambda t: 'dpapi:' + t[::-1])
    monkeypatch.setattr(config, 'dpapi_desproteger', lambda v: v[len('dpapi:'):][::-1])
    c = config.Config(str(tmp_path)); c.actualizar({'token': 'ghp_secreto'})
    en_disco = open(c.ruta, encoding='utf-8').read()
    assert 'ghp_secreto' not in en_disco and 'dpapi:' in en_disco and c['token'] == 'ghp_secreto' and c.publico()['token_proteccion'] == 'dpapi'
    c2 = config.Config(str(tmp_path)); assert c2['token'] == 'ghp_secreto'
    # token en claro de una version anterior: se reescribe cifrado al cargar
    json.dump({'token': 'ghp_viejo'}, open(c.ruta, 'w'))
    c3 = config.Config(str(tmp_path)); assert c3['token'] == 'ghp_viejo' and 'ghp_viejo' not in open(c.ruta, encoding='utf-8').read()


def test_token_en_claro_sin_dpapi_lo_avisa(tmp_path):
    if config.dpapi_disponible(): pytest.skip('Windows')
    c = config.Config(str(tmp_path)); c.actualizar({'token': 'ghp_x'})
    assert c.publico()['token_proteccion'] == 'claro' and 'token' not in c.publico()


def test_deteccion_onedrive():
    assert config.ruta_sincronizada(r'C:\Users\a\OneDrive - Empresa\Gridania\datos') == 'OneDrive'
    assert config.ruta_sincronizada('/home/a/onedrive/x') == 'OneDrive'
    assert config.ruta_sincronizada('/home/a/gridania') == ''


def test_aviso_onedrive_visible_al_arrancar(tmp_path, monkeypatch):
    from gridania_editor import app as app_mod
    home = tmp_path / 'OneDrive' / 'datos'
    monkeypatch.setattr(app_mod, '_caja', lambda *a: None)
    srvs = []; orig = app_mod.Servidor
    monkeypatch.setattr(app_mod, 'Servidor', lambda *a, **k: srvs.append(orig(*a, **k)) or srvs[-1])
    th = threading.Thread(target=lambda: app_mod.main(['--carpeta', str(home), '--sin-abrir']), daemon=True); th.start()
    for _ in range(100):
        if srvs: break
        time.sleep(0.05)
    assert 'OneDrive' in srvs[0].app.aviso and 'OneDrive' in _log(str(home))
    srvs[0].salir.set(); th.join(15)


def test_faulthandler_trunca_si_grande_y_se_para_solo(tmp_path):
    import faulthandler
    registro.iniciar(str(tmp_path), 'test')
    ruta = tmp_path / 'faulthandler.log'; ruta.write_text('x' * 2000)
    f = registro.activar_faulthandler(str(tmp_path), cada=1, max_minutos=0.02, max_bytes=1000)
    try:
        assert f is not None and ruta.stat().st_size < 200                 # truncado al arrancar
        time.sleep(2.0)
        assert registro._fh['f'] is None                                   # tope de minutos: volcado periodico parado
        assert registro._fh['abierto'] is not None                         # el volcado ante fallo fatal sigue con el fichero abierto
    finally:
        registro.parar_faulthandler(); faulthandler.disable()


def test_arranque_con_backend_de_ventana_falso_sin_sin_abrir(tmp_path):
    """proceso real (run_editor.py) SIN --sin-abrir con un modulo `webview` falso en PYTHONPATH: la ventana pide la pagina, el proceso termina solo y no abre navegador"""
    from conftest import EDITOR
    fake = tmp_path / 'fake'; fake.mkdir()
    (fake / 'webview.py').write_text(textwrap.dedent('''
        import time, urllib.request
        class _E(object):
            def __iadd__(self, f): return self
            def is_set(self): return False
        class _Ev(object): loaded = shown = closed = _E()
        class _W(object):
            def __init__(self, url): self.url = url; self.events = _Ev()
            def destroy(self): pass
        _w = []
        def create_window(t, url, **k): _w.append(_W(url)); return _w[0]
        def start(func=None, *a, **k):
            urllib.request.urlopen(_w[0].url, timeout=10).read(); time.sleep(4)
    '''))
    nav = tmp_path / 'nav.txt'
    sh = tmp_path / 'navegador.sh'; sh.write_text('#!/bin/sh\necho "$@" >> %s\n' % nav); sh.chmod(0o755)
    env = dict(os.environ, PYTHONPATH=str(fake), BROWSER=str(sh), GRIDANIA_EDITOR_HOME='')
    env.pop('GRIDANIA_EDITOR_HOME')
    home = str(tmp_path / 'd')
    p = subprocess.run([sys.executable, os.path.join(EDITOR, 'run_editor.py'), '--carpeta', home], env=env, capture_output=True, timeout=60)
    t = _log(home)
    assert p.returncode == 0, p.stderr.decode()[-500:]
    assert 'primera peticion GET / de la UI' in t and 'webview.start ha vuelto' in t and not nav.exists()
