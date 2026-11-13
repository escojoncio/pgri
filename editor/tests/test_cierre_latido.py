"""Cierre de la ventana por LATIDO (el pid del Popen es solo una pista): lanzador que delega, Edge vivo tras cerrar, F5, minimizada, lockfile ocupado, sendBeacon con clave invalida."""
import time, types, urllib.request
import pytest
from test_arranque import _lanzar, _esperar, _post, _latido, _limpiar_log  # noqa: F401  (fixture autouse)


def _srv(**kw):
    s = types.SimpleNamespace(t_latido=None, t_get=None, t_cierre=None, n_latidos=5, t_despertar=None, ui_cargada=types.SimpleNamespace(is_set=lambda: True)); s.__dict__.update(kw); return s


def test_motivo_cierre_reglas_puras():
    from gridania_editor import app as a
    # (b) sin latido >= 180 s con perfil libre; 300 s si no se puede comprobar; nada si el perfil esta ocupado
    assert a.motivo_cierre(_srv(t_latido=0), 179, True) is None and a.motivo_cierre(_srv(t_latido=0), 181, True)
    assert a.motivo_cierre(_srv(t_latido=0), 299, None) is None and a.motivo_cierre(_srv(t_latido=0), 301, None)
    assert a.motivo_cierre(_srv(t_latido=0), 1000, False) is None
    assert a.motivo_cierre(_srv(t_get=0, n_latidos=0), 1000, True) is None     # GET / pero ningun latido: no basta (hacen falta >= 2)
    assert a.motivo_cierre(_srv(t_get=0, n_latidos=1), 1000, True) is None and a.motivo_cierre(_srv(t_get=0, n_latidos=2), 1000, True)
    assert a.motivo_cierre(_srv(), 1000, True) is None                         # nunca cargo: lo decide el vigilante de carga
    assert a.motivo_cierre(_srv(t_latido=100), 150, True) is None             # el latido reinicia el contador
    # (a) cierre explicito + 10 s sin actividad
    assert a.motivo_cierre(_srv(t_latido=0, t_cierre=100), 109, True) is None and a.motivo_cierre(_srv(t_latido=0, t_cierre=100), 110, True)
    s = _srv(t_latido=105, t_cierre=100); assert a.motivo_cierre(s, 120, True) is None and s.t_cierre is None      # latido posterior = recarga
    s = _srv(t_get=105, t_cierre=100); assert a.motivo_cierre(s, 120, True) is None and s.t_cierre is None         # GET / posterior = F5


def test_lanzador_que_sale_al_instante_con_ventana_abierta_no_cierra_ni_abre_otro_navegador(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'delega', espera=1.0)
    assert _esperar(lambda: srvs and srvs[0].ui_cargada.is_set()) and lz.proc.poll() == 0         # el Popen ya salio
    for _ in range(14):                                                                              # > plazo del vigilante (1 s) y > gracia
        _latido(srvs[0]); time.sleep(0.1)
    assert th.is_alive() and abiertas == [] and not srvs[0].salir.is_set() and not lz.proc.terminado
    assert _post(srvs[0], '/api/cierre') == 200; th.join(15); assert not th.is_alive() and r['cod'] == 0 and abiertas == []


def test_proceso_vivo_tras_cerrar_la_ventana_cierra_por_cierre_explicito(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'ok')
    assert _esperar(lambda: srvs and srvs[0].ui_cargada.is_set())
    assert _post(srvs[0], '/api/cierre') == 200                                  # Edge sigue en segundo plano (el Popen no sale) pero la pagina se descargo
    th.join(15); assert not th.is_alive() and r['cod'] == 0 and abiertas == [] and lz.proc.poll() is not None


def test_f5_no_cierra(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'ok')
    assert _esperar(lambda: srvs and srvs[0].ui_cargada.is_set())
    assert _post(srvs[0], '/api/cierre') == 200; time.sleep(0.2)
    urllib.request.urlopen(srvs[0].url, timeout=5).read()                         # la pagina se vuelve a pedir dentro de la gracia
    time.sleep(app_mod.GRACIA_CIERRE_S + 0.8)
    assert th.is_alive() and not srvs[0].salir.is_set() and srvs[0].t_cierre is None
    srvs[0].salir.set(); th.join(15)


def test_ventana_minimizada_sin_latido_menos_de_180_s_no_cierra(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'ok')
    assert _esperar(lambda: srvs and srvs[0].ui_cargada.is_set())
    time.sleep(1.5)                                                               # sin latidos, muy por debajo de 180 s
    assert th.is_alive() and not srvs[0].salir.is_set() and abiertas == []
    srvs[0].salir.set(); th.join(15)


def test_sin_latido_pasado_el_umbral_cierra_solo_si_el_perfil_esta_libre(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'ok')
    monkeypatch.setattr(app_mod, 'UMBRAL_LATIDO_S', 0.5); monkeypatch.setattr(app_mod, 'UMBRAL_SIN_LOCK_S', 0.5)
    libre = {'v': False}; monkeypatch.setattr(app_mod.ventana, 'perfil_libre', lambda *a, **k: libre['v'])
    assert _esperar(lambda: srvs and srvs[0].ui_cargada.is_set())
    _latido(srvs[0]); _latido(srvs[0])
    time.sleep(1.5)                                                               # lockfile ocupado: la ventana sigue ahi
    assert th.is_alive() and not srvs[0].salir.is_set()
    libre['v'] = True; th.join(15); assert not th.is_alive() and r['cod'] == 0


def test_sendbeacon_con_clave_invalida_se_ignora(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'ok')
    assert _esperar(lambda: srvs and srvs[0].ui_cargada.is_set())
    assert _post(srvs[0], '/api/cierre', clave='mala') == 401 and _post(srvs[0], '/api/cierre', clave='') == 401
    assert _post(srvs[0], '/api/latido', clave='ok') == 401                       # la clave en ?k= solo vale para /api/cierre
    time.sleep(app_mod.GRACIA_CIERRE_S + 0.8)
    assert th.is_alive() and srvs[0].t_cierre is None and not srvs[0].salir.is_set()
    srvs[0].salir.set(); th.join(15)


# ---------------------------------------------------------------- relojes inyectables (sin sleeps)
def test_suspension_reanudacion_no_cierra_al_despertar():
    from gridania_editor import app as a
    srv = _srv(t_latido=0.0, cerrado_en=None); t = {'v': 0.0}
    srv.salir = types.SimpleNamespace(is_set=lambda: False, set=lambda: setattr(srv, 'cerrado_en', t['v']))
    pasos = iter([1.0, 2.0, 5000.0] + [5000.0 + 4 * i for i in range(1, 12)])          # duerme entre 2 y 5000 s; luego pasos de 4 s
    def wait(p):
        if srv.cerrado_en is not None: return True
        try: t['v'] = next(pasos); return False
        except StopIteration: return True
    srv.salir.wait = wait
    a._vigilar_cierre(srv, {'lock': __import__('threading').Lock(), 'navegador': False}, lambda: True, paso=0.01, reloj=lambda: t['v'])
    assert srv.t_despertar == 5000.0
    assert srv.cerrado_en is not None and srv.cerrado_en >= 5030.0                      # NO cierra nada mas despertar; solo pasado el margen de 30 s sin latido nuevo


def test_despertar_margen_y_latido_nuevo():
    from gridania_editor import app as a
    s = _srv(t_latido=0.0, t_despertar=5000.0)
    assert a.motivo_cierre(s, 5010, True) is None and a.motivo_cierre(s, 5029, True) is None   # margen de 30 s
    assert a.motivo_cierre(s, 5031, True)                                                       # sin latido nuevo, pasado el margen
    s.t_latido = 5020.0; assert a.motivo_cierre(s, 5030, True) is None                          # latido nuevo: contador fresco
    # el cierre explicito tambien reinicia su gracia al despertar y sigue cerrando despues
    s = _srv(t_latido=0.0, t_cierre=100.0, t_despertar=5000.0)
    assert a.motivo_cierre(s, 5005, True) is None
    s = _srv(t_latido=0.0, t_cierre=100.0, t_despertar=5000.0); assert a.motivo_cierre(s, 5031, True)


def test_contador_de_latidos_y_zombi():
    from gridania_editor import app as a
    assert a.motivo_cierre(_srv(t_latido=0, n_latidos=1), 1000, True) is None                    # un solo latido no basta
    assert a.motivo_cierre(_srv(t_latido=0, n_latidos=2), 1000, True)
    # cierre explicito siempre cierra, incluso con 0 latidos
    assert a.motivo_cierre(_srv(t_cierre=0, n_latidos=0), 11, False)
    # zombi: perfil bloqueado, sin ventana visible, 15 min sin latido
    assert a.motivo_cierre(_srv(t_latido=0), 899, False, ventana_visible=False) is None
    assert a.motivo_cierre(_srv(t_latido=0), 901, False, ventana_visible=False)
    assert a.motivo_cierre(_srv(t_latido=0), 5000, False, ventana_visible=True) is None          # hay ventana: no es zombi
    assert a.motivo_cierre(_srv(t_latido=0), 5000, False, ventana_visible=None) is None          # no comprobable: no cierra


def test_lockfile_ausente_con_pid_vivo_o_ventana_no_es_perfil_libre(tmp_path, monkeypatch):
    from gridania_editor import ventana
    monkeypatch.setattr(ventana.sys, 'platform', 'win32'); monkeypatch.setattr(ventana, 'dir_perfil', lambda home, env=None: str(tmp_path))   # sin lockfile
    assert ventana.perfil_libre('h') is True
    assert ventana.perfil_libre('h', pid_vivo=lambda: True) is False
    assert ventana.perfil_libre('h', pid_vivo=lambda: False, hay_ventana=lambda: True) is False
    assert ventana.perfil_libre('h', pid_vivo=lambda: False, hay_ventana=lambda: False) is True
    assert ventana.perfil_libre('h', pid_vivo=lambda: False, hay_ventana=lambda: None) is True


def test_reabrir_y_borrador_en_el_servidor(tmp_path):
    from gridania_editor.servidor import Servidor
    app = types.SimpleNamespace(cfg=types.SimpleNamespace(home=str(tmp_path), redactar=str))
    s = Servidor(app, 0)
    try:
        s.pedir_cierre(); assert s.t_cierre is not None
        assert s.post('/api/reabrir', {}) == {'ok': True} and s.t_cierre is None and s.n_latidos == 1
        s.salir.set(); assert s.post('/api/reabrir', {})['ok'] is False                    # ya cerro: la UI muestra el mensaje
        assert s.get('/api/borrador', {}) == {}
        s.post('/api/borrador', {'id': 7, 'texto': 'hola', 'base': 'x'}); assert s.get('/api/borrador', {})['texto'] == 'hola' and (tmp_path / 'borrador.json').exists()
        s.post('/api/borrador_borrar', {}); assert s.get('/api/borrador', {}) == {}
    finally: s.httpd.server_close()


def test_host_invalido_y_clave_invalida(tmp_path, monkeypatch):
    app_mod, lz, llamadas, abiertas, srvs, home, th, r, t0 = _lanzar(tmp_path, monkeypatch, 'ok')
    assert _esperar(lambda: srvs and srvs[0].ui_cargada.is_set())
    srv = srvs[0]
    def pet(host=None, k=None, ruta='api/estado'):
        h = {}
        if k is not None: h['X-K'] = k
        rq = urllib.request.Request(srv.url + ruta, headers=h)
        if host: rq.add_unredirected_header('Host', host)
        try: return urllib.request.urlopen(rq, timeout=5).status
        except urllib.error.HTTPError as x: return x.code
    assert pet(k=srv.clave) == 200 and pet(k='mala') == 401 and pet() == 401 and pet(k='\xe9\xe9') in (401, 400)
    assert pet(host='evil.com', k=srv.clave) == 403 and pet(host='evil.com:80', ruta='') == 403
    srv.salir.set(); th.join(15)


def _U32(v):
    """user32 falso (funciones planas que admiten argtypes): ventanas = {hwnd: (titulo, visible)}"""
    u = types.SimpleNamespace(llamadas=[])
    def EnumWindows(cb, lp):
        for h in v:
            if not cb(h, 0): break
        return True
    def GetWindowTextW(h, buf, n): buf.value = v[h][0]; return len(v[h][0])
    def ShowWindow(h, c): u.llamadas.append(('show', h, c)); return 1
    def SetForegroundWindow(h): u.llamadas.append(('fg', h)); return 1
    u.EnumWindows = EnumWindows; u.IsWindowVisible = lambda h: v[h][1]; u.GetWindowTextLengthW = lambda h: len(v[h][0])
    u.GetWindowTextW = GetWindowTextW; u.ShowWindow = ShowWindow; u.SetForegroundWindow = SetForegroundWindow
    return u


def test_traer_al_frente_y_hay_ventana_con_user32_falso():
    from gridania_editor import instancia
    u = _U32({1: ('Otra', True), 2: ('Editor de traducciones Gridania - Edge', True), 3: ('Editor de traducciones Gridania', False)})
    assert instancia.traer_al_frente(user32=u) is True and u.llamadas == [('show', 2, 9), ('fg', 2)]
    assert instancia.hay_ventana(user32=u) is True
    u2 = _U32({1: ('Otra', True), 3: ('Editor de traducciones Gridania', False)})
    assert instancia.traer_al_frente(user32=u2) is False and u2.llamadas == [] and instancia.hay_ventana(user32=u2) is False
    from ctypes import wintypes
    assert u.EnumWindows.argtypes[1] is wintypes.LPARAM and u.ShowWindow.argtypes[0] is wintypes.HWND          # tipos explicitos
