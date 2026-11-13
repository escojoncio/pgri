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
    assert a.motivo_cierre(_srv(t_get=0, n_latidos=0), 299, True) is None and a.motivo_cierre(_srv(t_get=0, n_latidos=0), 301, True)   # <2 latidos: umbral largo (300 s), no bloqueo eterno
    assert a.motivo_cierre(_srv(t_get=0, n_latidos=1), 299, True) is None and a.motivo_cierre(_srv(t_get=0, n_latidos=2), 181, True)
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
    assert a.motivo_cierre(_srv(t_latido=0, n_latidos=1), 200, True) is None                     # un solo latido: umbral largo
    assert a.motivo_cierre(_srv(t_latido=0, n_latidos=1), 301, True) and a.motivo_cierre(_srv(t_latido=0, n_latidos=0), 301, None)
    assert a.motivo_cierre(_srv(t_latido=0, n_latidos=0), 5000, False) is None                   # perfil ocupado: sigue sin cerrar por esta rama
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


def test_ventana_ausente_sostenida_cierra_sin_mirar_perfil_libre():
    from gridania_editor import app as a
    s = _srv(t_latido=0)
    assert a.motivo_cierre(s, 29, False, ventana_ausente=True) is None                         # < 30 s sin latido
    assert a.motivo_cierre(s, 31, False, ventana_ausente=True)                                 # perfil ocupado (False) pero ventana ausente sostenida: cierra
    assert a.motivo_cierre(s, 31, False, ventana_ausente=False) is None
    assert a.motivo_cierre(_srv(t_latido=0, n_latidos=0), 31, False, ventana_ausente=True)      # tambien con pocos latidos
    assert a.motivo_cierre(_srv(t_latido=0, t_despertar=20.0), 40, False, ventana_ausente=True) is None   # recien despertado: no


def test_seguimiento_ventana_exige_3_comprobaciones_separadas_5_s():
    from gridania_editor import app as a
    vals = iter([False, False, True, False, False, False, None]); llamadas = []
    def f(): llamadas.append(1); return next(vals)
    sg = a.SeguimientoVentana(f)
    assert sg.actualizar(0) == (False, False) and sg.actualizar(1) == (False, False) and len(llamadas) == 1      # entre comprobaciones no consulta
    assert sg.actualizar(5) == (False, False)                                                                   # 2 seguidas
    assert sg.actualizar(10) == (True, False)                                                                   # ventana vista: reinicia
    assert sg.actualizar(15) == (False, False) and sg.actualizar(20) == (False, False)
    assert sg.actualizar(25) == (False, True)                                                                   # 3 consecutivas
    assert sg.actualizar(30) == (None, False)                                                                   # no comprobable: reinicia
    assert a.SeguimientoVentana(None).actualizar(0) == (None, False)


def test_vigilante_cierra_con_ventana_ausente_sostenida_aunque_perfil_ocupado():
    from gridania_editor import app as a
    srv = _srv(t_latido=0.0, cerrado_en=None); t = {'v': 0.0}
    srv.salir = types.SimpleNamespace(is_set=lambda: False, set=lambda: setattr(srv, 'cerrado_en', t['v']))
    pasos = iter([float(i) for i in range(1, 100)])
    def wait(p):
        if srv.cerrado_en is not None: return True
        t['v'] = next(pasos); return False
    srv.salir.wait = wait
    a._vigilar_cierre(srv, {'lock': __import__('threading').Lock(), 'navegador': False}, lambda: False, paso=0.01, reloj=lambda: t['v'], ventana_visible=lambda: False)
    assert srv.cerrado_en == 30.0                                                                              # 30 s sin latido y ya habia 3 comprobaciones (0/5/10 s)
    srv2 = _srv(t_latido=0.0, cerrado_en=None); srv2.salir = types.SimpleNamespace(is_set=lambda: False, set=lambda: setattr(srv2, 'cerrado_en', t['v']))
    t['v'] = 0.0; pasos2 = iter([float(i) for i in range(1, 400)])
    def wait2(p):
        if srv2.cerrado_en is not None: return True
        v = next(pasos2, None)
        if v is None: return True
        t['v'] = v; return False
    srv2.salir.wait = wait2
    a._vigilar_cierre(srv2, {'lock': __import__('threading').Lock(), 'navegador': False}, lambda: False, paso=0.01, reloj=lambda: t['v'], ventana_visible=lambda: True)
    assert srv2.cerrado_en is None                                                  # ventana presente y perfil ocupado: no cierra


def _bor(hoja='Quest', row=3, sub=None, col=1, h='h1', texto='nuevo', base='viejo'):
    return {'hoja': hoja, 'row': row, 'sub': sub, 'col': col, 'h': h, 'texto': texto, 'base': base}


def test_reabrir_y_borradores_por_celda_en_el_servidor(tmp_path):
    from gridania_editor.servidor import Servidor
    app = types.SimpleNamespace(cfg=types.SimpleNamespace(home=str(tmp_path), redactar=str))
    s = Servidor(app, 0)
    try:
        s.pedir_cierre(); assert s.t_cierre is not None
        assert s.post('/api/reabrir', {}) == {'ok': True} and s.t_cierre is None and s.n_latidos == 1
        s.salir.set(); assert s.post('/api/reabrir', {})['ok'] is False                    # ya cerro: la UI muestra el mensaje
        assert s.get('/api/borradores', {}) == {'borradores': []}
        s.post('/api/borrador', _bor(texto='A')); s.post('/api/borrador', _bor(row=4, sub=2, texto='B'))
        s.post('/api/borrador', _bor(texto='A2'))                                          # misma celda: se sobrescribe, no se duplica
        d = {(b['row'], b['sub']): b for b in s.get('/api/borradores', {})['borradores']}
        assert len(d) == 2 and d[(3, None)]['texto'] == 'A2' and d[(3, None)]['h'] == 'h1' and d[(3, None)]['base'] == 'viejo' and d[(4, 2)]['texto'] == 'B' and (tmp_path / 'borradores.json').exists()
        s.post('/api/borrador_borrar', {'hoja': 'Quest', 'row': 3, 'sub': None, 'col': 1})   # borrar una no toca la otra
        assert [b['texto'] for b in s.get('/api/borradores', {})['borradores']] == ['B']
        s.post('/api/borrador_borrar', {'hoja': 'Quest', 'row': 4, 'sub': 2, 'col': 1}); assert s.get('/api/borradores', {}) == {'borradores': []} and not (tmp_path / 'borradores.json').exists()
        s.post('/api/borrador_borrar', _bor())                                              # borrar inexistente: ok
    finally: s.httpd.server_close()


def test_borradores_versionados_y_servicio_de_borradores_js(tmp_path):
    import urllib.request
    from gridania_editor.servidor import Servidor
    app = types.SimpleNamespace(cfg=types.SimpleNamespace(home=str(tmp_path), redactar=str))
    s = Servidor(app, 0)
    try:
        s.post('/api/borrador', _bor(texto='P')); s.post('/api/borrador', dict(_bor(texto='ANT'), ver='a1'))
        d = {b['ver']: b['texto'] for b in s.get('/api/borradores', {})['borradores']}
        assert d == {'': 'P', 'a1': 'ANT'}
        s.post('/api/borrador_borrar', dict(_bor(), ver='a1'))                             # borra solo la version antigua
        assert [b['texto'] for b in s.get('/api/borradores', {})['borradores']] == ['P']
        s.post('/api/borrador_borrar', _bor()); assert s.get('/api/borradores', {}) == {'borradores': []}
        import threading; threading.Thread(target=s.httpd.serve_forever, daemon=True).start()
        r = urllib.request.urlopen('http://127.0.0.1:%d/borradores.js' % s.puerto)
        assert r.status == 200 and 'javascript' in r.headers['Content-Type'] and b'crearGestor' in r.read()
    finally: s.httpd.shutdown(); s.httpd.server_close()


def test_borradores_tope_no_borra_principales_y_rechaza(tmp_path):
    from gridania_editor.servidor import Servidor
    app = types.SimpleNamespace(cfg=types.SimpleNamespace(home=str(tmp_path), redactar=str))
    s = Servidor(app, 0)
    try:
        s.MAX_BORRADORES = 4
        s._h_actual = lambda v: 'h1'                                                        # indice responde: h coincide
        s.post('/api/borrador', dict(_bor(row=1, texto='a'), luego=True))
        s.post('/api/borrador', dict(_bor(row=1, texto='v1'), ver='a1')); s.post('/api/borrador', dict(_bor(row=1, texto='v2'), ver='a2'))
        s.post('/api/borrador', _bor(row=2, texto='b'))
        s.post('/api/borrador', _bor(row=3, texto='c'))                                     # lleno: purga la version archivada mas antigua
        t = lambda: {(b['row'], b['ver']): b['texto'] for b in s.get('/api/borradores', {})['borradores']}
        assert len(t()) == 4 and (1, 'a1') not in t() and t()[(1, '')] == 'a'
        s.post('/api/borrador', _bor(row=3, texto='c2'))                                    # sobrescribir no purga
        s.post('/api/borrador', _bor(row=4, texto='d'))                                     # quita la ultima version (h coincide: no hay conflicto)
        assert (1, 'a2') not in t() and len(t()) == 4
        with pytest.raises(ValueError, match='demasiados'): s.post('/api/borrador', _bor(row=5, texto='e'))   # solo principales: se rechaza, no se borra
        assert {v for (r, ver), v in t().items()} == {'a', 'b', 'c2', 'd'} and (5, '') not in t()
        # principal en conflicto: conserva su version archivada mas reciente
        s.MAX_BORRADORES = 5
        s.post('/api/borrador', dict(_bor(row=1, texto='v3'), ver='a3')); s.post('/api/borrador', dict(_bor(row=1, texto='v4'), ver='a4'))
        s._h_actual = lambda v: 'nuevo'
        with pytest.raises(ValueError): s.post('/api/borrador', _bor(row=6, texto='f'))
        assert (1, 'a4') in t()
        assert all(t()[k] for k in [(1, ''), (2, ''), (3, ''), (4, '')])
    finally: s.httpd.server_close()


def test_borradores_indice_caido_no_purga_por_h(tmp_path):
    from gridania_editor.servidor import Servidor
    app = types.SimpleNamespace(cfg=types.SimpleNamespace(home=str(tmp_path), redactar=str))
    s = Servidor(app, 0)
    try:
        s.MAX_BORRADORES = 3
        s._h_actual = lambda v: None                                                        # indice sin respuesta
        s.post('/api/borrador', _bor(row=1, texto='a')); s.post('/api/borrador', dict(_bor(row=1, texto='v1'), ver='a1')); s.post('/api/borrador', _bor(row=2, texto='b'))
        with pytest.raises(ValueError): s.post('/api/borrador', _bor(row=3, texto='c'))     # la unica version esta protegida y nada mas se borra
        assert {b['texto'] for b in s.get('/api/borradores', {})['borradores']} == {'a', 'v1', 'b'}
    finally: s.httpd.server_close()
