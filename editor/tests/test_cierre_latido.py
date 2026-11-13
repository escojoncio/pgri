"""Cierre de la ventana por LATIDO (el pid del Popen es solo una pista): lanzador que delega, Edge vivo tras cerrar, F5, minimizada, lockfile ocupado, sendBeacon con clave invalida."""
import time, types, urllib.request
import pytest
from test_arranque import _lanzar, _esperar, _post, _latido, _limpiar_log  # noqa: F401  (fixture autouse)


def _srv(**kw):
    s = types.SimpleNamespace(t_latido=None, t_get=None, t_cierre=None, ui_cargada=types.SimpleNamespace(is_set=lambda: True)); s.__dict__.update(kw); return s


def test_motivo_cierre_reglas_puras():
    from gridania_editor import app as a
    # (b) sin latido >= 180 s con perfil libre; 300 s si no se puede comprobar; nada si el perfil esta ocupado
    assert a.motivo_cierre(_srv(t_latido=0), 179, True) is None and a.motivo_cierre(_srv(t_latido=0), 181, True)
    assert a.motivo_cierre(_srv(t_latido=0), 299, None) is None and a.motivo_cierre(_srv(t_latido=0), 301, None)
    assert a.motivo_cierre(_srv(t_latido=0), 1000, False) is None
    assert a.motivo_cierre(_srv(t_get=0), 1000, True)                          # sin ningun latido pero con GET /
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
