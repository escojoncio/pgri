"""Segunda ronda de arranque: carrera ventana/navegador con un unico ganador, ventana Edge que no carga, migracion tras la UI, token DPAPI, OneDrive, faulthandler acotado."""
import json, os, subprocess, sys, textwrap, threading, time, urllib.request
import pytest
from gridania_editor import config, registro
from test_arranque import _lanzar, _log, _limpiar_log  # noqa: F401  (fixture autouse)


def _stubs():
    class Ev(object):
        def __init__(self): self.e = threading.Event()
        def is_set(self): return self.e.is_set()
    class Srv(object):
        def __init__(self): self.ui_cargada = threading.Event(); self.salir = threading.Event()
    return Ev, Srv


def test_vigilante_abre_navegador_y_termina_la_ventana_sin_doble_ui(tmp_path):
    from gridania_editor import app as app_mod
    Ev, Srv = _stubs(); orden = []
    class Proc(object):
        def poll(self): return None
        def terminate(self): orden.append('terminate')
    class Ap(object):
        aviso = ''; cfg = type('C', (), {'home': str(tmp_path)})()
    srv, est = Srv(), {'navegador': False, 'proc': Proc(), 'cerrada': threading.Event()}
    app_mod._vigilar_ui(srv, Ap(), est, 'u', espera=0.1, paso=0.02, abrir=lambda u: orden.append('abrir'))
    assert orden == ['abrir', 'terminate'] and est['navegador']
    # segunda llamada: ya hay navegador, no se abre otro
    app_mod._pasar_a_navegador(srv, Ap(), est, 'u', lambda u: orden.append('abrir2'), forzar=True)
    assert 'abrir2' not in orden


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


def test_arranque_real_con_edge_falso_sin_sin_abrir(tmp_path):
    """proceso real (run_editor.py) con un `msedge.exe` falso (script) encontrado por ProgramFiles: pide la pagina, termina y el editor se cierra solo sin abrir navegador"""
    if not sys.platform.startswith('linux'): pytest.skip('script falso solo en Linux')
    from conftest import EDITOR
    pf = tmp_path / 'pf'; app = pf / 'Microsoft' / 'Edge' / 'Application'; app.mkdir(parents=True)
    nav = tmp_path / 'nav.txt'; args = tmp_path / 'args.txt'
    (app / 'msedge.exe').write_text('#!%s\nimport sys, time, urllib.request\nopen(%r, "w").write(" ".join(sys.argv[1:]))\nurl = [a for a in sys.argv if a.startswith("--app=")][0][6:]\n'
                                    'urllib.request.urlopen(url, timeout=10).read(); time.sleep(2)\n' % (sys.executable, str(args)))
    (app / 'msedge.exe').chmod(0o755)
    sh = tmp_path / 'navegador.sh'; sh.write_text('#!/bin/sh\necho "$@" >> %s\n' % nav); sh.chmod(0o755)
    env = dict(os.environ, BROWSER=str(sh)); env['ProgramFiles'] = str(pf); env.pop('GRIDANIA_EDITOR_HOME', None)
    home = str(tmp_path / 'd')
    p = subprocess.run([sys.executable, os.path.join(EDITOR, 'run_editor.py'), '--carpeta', home], env=env, capture_output=True, timeout=60)
    t = _log(home)
    assert p.returncode == 0, p.stderr.decode()[-500:]
    assert 'primera peticion GET / de la UI' in t and 'ventana cerrada por el usuario' in t and not nav.exists()
    assert '--app=http://127.0.0.1:' in args.read_text() and '--user-data-dir=' in args.read_text()


def test_migracion_real_con_base_ya_abierta(tmp_path):
    from gridania_editor.aplicacion import Aplicacion
    ant, nue = tmp_path / 'ant', tmp_path / 'datos'
    (ant / 'ediciones' / 'x').mkdir(parents=True); (ant / 'ediciones' / 'x' / 'a.jsonl').write_text('1')
    (ant / 'config.json').write_text('{"rama": "otra"}'); (ant / 'flujo.json').write_text('{}')
    ap = Aplicacion(str(nue), diferir=True)
    ap.abrir_base()                                           # crea editor.db(-wal/-shm) en el destino ANTES de migrar
    assert (nue / 'editor.db').exists()
    c = config.migrar_antigua(str(nue), str(ant))
    assert 'config.json' in c and 'flujo.json' in c and 'ediciones' in c
    assert (nue / 'ediciones' / 'x' / 'a.jsonl').read_text() == '1'
    assert json.loads((nue / 'config.json').read_text())['rama'] == 'otra'


def _windll_falso(monkeypatch):
    import ctypes
    from types import SimpleNamespace
    class F(object):
        def __init__(self): self.argtypes = None; self.restype = None
        def __call__(self, *a): return 0
    w = SimpleNamespace(crypt32=SimpleNamespace(CryptProtectData=F(), CryptUnprotectData=F()), kernel32=SimpleNamespace(LocalFree=F()))
    monkeypatch.setattr(ctypes, 'windll', w, raising=False)
    return w


def test_dpapi_firmas_explicitas(monkeypatch):
    w = _windll_falso(monkeypatch)
    with pytest.raises(OSError): config._dpapi(b'x', True)
    with pytest.raises(OSError): config._dpapi(b'x', False)
    for f in (w.crypt32.CryptProtectData, w.crypt32.CryptUnprotectData):
        assert len(f.argtypes) == 7 and f.restype is not None
    assert config.CRYPTPROTECT_UI_FORBIDDEN == 1


@pytest.mark.skipif(not sys.platform.startswith('win'), reason='DPAPI solo en Windows')
def test_dpapi_cifra_y_descifra_de_verdad():
    v = config.dpapi_proteger('ghp_secreto')
    assert v.startswith('dpapi:') and 'secreto' not in v
    assert config.dpapi_desproteger(v) == 'ghp_secreto'


def _winreg_falso(claves):
    """claves: {(raiz, nombre): ruta}"""
    import types
    m = types.ModuleType('winreg'); m.HKEY_LOCAL_MACHINE = 'HKLM'; m.HKEY_CURRENT_USER = 'HKCU'
    class K(object):
        def __init__(self, v): self.v = v
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def OpenKey(raiz, ruta):
        k = (raiz, ruta.rsplit('\\', 1)[1])
        if k not in claves: raise OSError('no')
        return K(claves[k])
    m.OpenKey = OpenKey; m.QueryValueEx = lambda k, n: (k.v, 1)
    return m


def test_buscar_edge_por_registro_antes_que_rutas_y_chrome():
    from gridania_editor import ventana
    reg = _winreg_falso({('HKLM', 'msedge.exe'): r'C:\Edge\msedge.exe', ('HKCU', 'chrome.exe'): r'C:\Chrome\chrome.exe'})
    ok = {r'C:\Edge\msedge.exe', r'C:\Chrome\chrome.exe'}
    assert ventana.buscar_navegador(env={}, winreg=reg, existe=ok.__contains__) == r'C:\Edge\msedge.exe'
    assert ventana.buscar_navegador(env={}, winreg=reg, existe={r'C:\Chrome\chrome.exe'}.__contains__) == r'C:\Chrome\chrome.exe'


def test_buscar_edge_en_program_files_y_sin_nada():
    from gridania_editor import ventana
    env = {'ProgramFiles(x86)': r'C:\PF86', 'ProgramFiles': r'C:\PF'}
    reg = _winreg_falso({})
    esperado = os.path.join(r'C:\PF86', 'Microsoft', 'Edge', 'Application', 'msedge.exe')
    assert ventana.buscar_navegador(env=env, winreg=reg, existe={esperado}.__contains__) == esperado
    assert ventana.buscar_navegador(env=env, winreg=reg, existe=lambda r: False) is None


def test_linea_de_comandos_exacta_y_lanzar(tmp_path):
    from gridania_editor import ventana
    cmd = ventana.linea_comando('E', 'http://127.0.0.1:5/', 'P')
    assert cmd == ['E', '--app=http://127.0.0.1:5/', '--user-data-dir=P', '--no-first-run', '--no-default-browser-check', '--window-size=1400,900']
    vistos = []
    class P(object): pid = 7
    p = ventana.lanzar('http://127.0.0.1:5/', str(tmp_path), buscar=lambda: 'E', popen=lambda c: vistos.append(c) or P())
    assert p.pid == 7 and vistos[0] == ventana.linea_comando('E', 'http://127.0.0.1:5/', os.path.join(str(tmp_path), 'perfil-ventana')) and (tmp_path / 'perfil-ventana').is_dir()
    assert ventana.lanzar('u', str(tmp_path), buscar=lambda: None) is None                    # sin Edge/Chrome
    def malo(c): raise OSError('no arranca')
    assert ventana.lanzar('u', str(tmp_path), buscar=lambda: 'E', popen=malo) is None         # fallo al lanzar
