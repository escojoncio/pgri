"""Punto de entrada: servidor local + ventana propia (pywebview/WebView2) o, si no esta disponible, el navegador por defecto.
La ventana sale al instante con «Cargando...»: la migracion de la BD y la comprobacion del indice se hacen en un hilo y la UI muestra su progreso."""
import argparse, logging, multiprocessing, os, sys, threading, time, webbrowser
from . import __version__, config, instancia, registro
from . import stdlib_para_scripts  # noqa: F401  (declara la stdlib que usan los scripts descargados)
from .aplicacion import Aplicacion
from .servidor import Servidor

ESPERA_UI_S = 30    # si la UI no pide la pagina en este tiempo (arranque en frio), se abre el navegador por defecto (el servidor sigue vivo)
AMPLIACION_S = 30   # con senal de vida (create_window ya devolvio la ventana) el plazo se amplia a «momento de la senal + AMPLIACION_S»...
TOPE_UI_S = 90      # ...sin pasar nunca de este total


def _decir(texto, nivel=logging.WARNING):
    """a consola si existe (con --windowed no hay) y siempre al registro"""
    logging.getLogger('gridania').log(nivel, texto)
    try:
        if sys.stdout is not None: print(texto, flush=True)
    except Exception:
        pass


def _caja(titulo, texto):
    """mensaje visible si no hay consola (Windows con --windowed)"""
    if sys.platform.startswith('win'):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, texto, titulo, 0x10)
        except Exception:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description='Editor de traducciones Gridania')
    ap.add_argument('--navegador', action='store_true', help='usar el navegador por defecto en vez de la ventana propia')
    ap.add_argument('--puerto', type=int, default=0); ap.add_argument('--carpeta', help='carpeta de trabajo (por defecto <carpeta del programa>/datos)')
    ap.add_argument('--sin-abrir', action='store_true', help='solo arranca el servidor (pruebas)')
    a = ap.parse_args(argv)
    por_defecto = not a.carpeta and not os.environ.get('GRIDANIA_EDITOR_HOME')
    home = os.path.abspath(a.carpeta or config.carpeta_trabajo())
    lg = registro.iniciar(home, __version__)
    registro.activar_faulthandler(home)
    if config.AVISO_CARPETA: _decir(config.AVISO_CARPETA); _caja('Editor de traducciones Gridania', config.AVISO_CARPETA)
    avisos = [config.AVISO_CARPETA] if config.AVISO_CARPETA else []
    nube = config.ruta_sincronizada(home)
    if nube:
        av = config.AVISO_ONEDRIVE % home; avisos.append(av); _decir(av)
        threading.Thread(target=_caja, args=('Editor de traducciones Gridania', av), daemon=True, name='aviso-onedrive').start()    # sin bloquear el arranque
    cerrojo = instancia.adquirir(home)
    if cerrojo is None:
        cerrojo = _recuperar_obsoleta(home, lg)
    if cerrojo is None:
        return _ya_abierto(home, lg)
    try:
        tras_ui = (lambda: config.migrar_antigua(home, log=lg)) if por_defecto else None     # copytree: en un hilo, DESPUES de que la UI cargue
        return _principal(a, lg, tras_ui, ' '.join(avisos))
    except BaseException as x:
        if isinstance(x, (KeyboardInterrupt, SystemExit)): raise
        lg.critical('fallo fatal en el arranque', exc_info=True)
        msg = 'El editor no ha podido arrancar: %s: %s\nRegistro: %s' % (type(x).__name__, x, registro.ruta_log(home))
        _decir(msg); _caja('Editor de traducciones Gridania', msg)
        return 1
    finally:
        instancia.liberar(home, cerrojo)


def _recuperar_obsoleta(home, lg, intentos=5, paso=0.2):
    """instancia.json de una instancia que ya no responde: se ignora y se reintenta el cerrojo (arranque normal). -> manejador o None"""
    info = instancia.existente(home)
    if info and instancia.responde(info): return None
    lg.warning('instancia.json obsoleto o sin respuesta (%s): se ignora', info)
    for _ in range(intentos):
        c = instancia.adquirir(home)
        if c is not None: return c
        time.sleep(paso)
    return None


def _ya_abierto(home, lg):
    """otra instancia tiene el cerrojo: no se crea otro proceso; se enfoca su ventana o se reabre su pagina"""
    info = instancia.existente(home)
    lg.warning('ya hay una instancia del editor en marcha (%s)', info)
    if info.get('modo') == 'navegador' and info.get('url') and instancia.responde(info): webbrowser.open(info['url'])
    elif not instancia.traer_al_frente():
        _decir('El editor ya esta abierto (ventana propia). Busca su ventana en la barra de tareas.')
        _caja('Editor de traducciones Gridania', 'El editor ya esta abierto. Busca su ventana en la barra de tareas.')
    return 0


def cerrar_trabajo(app, espera=3.0):
    """al salir: cancela el indexado y mata los procesos trabajadores (si no, el proceso queda oculto consumiendo CPU)"""
    app.tarea.cancelar_ev.set()
    t0 = time.time()
    while app.tarea.estado == 'ejecutando' and time.time() - t0 < espera: time.sleep(0.05)
    for p in multiprocessing.active_children():
        try: p.terminate()
        except Exception: pass


def terminar(codigo):
    """termina el proceso YA (hilos de fondo, trabajadores y WebView2 no pueden dejarlo vivo) tras vaciar los registros"""
    try:
        if sys.stdout: sys.stdout.flush()
        if sys.stderr: sys.stderr.flush()
    except Exception: pass
    logging.shutdown()
    os._exit(codigo or 0)


class _Cancelada(Exception):
    """la ventana propia pierde la carrera contra el navegador (o no hay runtime): no es un fallo"""


def _sin_runtime():
    """Windows sin WebView2 Runtime segun el registro (no se espera 30 s para saberlo)"""
    return sys.platform.startswith('win') and webview2_instalado() is None


def _destruir_en_hilo(win, espera=3.0):
    """win.destroy() puede bloquearse si el hilo de la GUI esta colgado: hilo aparte con timeout; nunca bloquea al llamador mas de `espera` s"""
    t = threading.Thread(target=lambda: _intentar(win.destroy), daemon=True, name='destruir-ventana'); t.start(); t.join(espera)
    if t.is_alive(): logging.getLogger('gridania').warning('win.destroy() no ha vuelto en %.0f s (hilo de la GUI colgado); se sigue sin esperar', espera)


def _intentar(f):
    try: f()
    except Exception: pass


def _pasar_a_navegador(srv, app, estado, url, abrir, aviso=None, forzar=False):
    """UNICO ganador: si la ventana ya cargo (salvo `forzar`) o el navegador ya se abrio, no hace nada. Si no: ABRE EL NAVEGADOR PRIMERO, luego destruye la ventana (en un hilo con timeout).
    El servidor NO se cierra. -> True si abrio el navegador."""
    with estado['lock']:
        if estado['navegador'] or (not forzar and srv.ui_cargada.is_set()): return False
        estado['navegador'] = True
    if aviso: app.aviso = aviso; _decir(aviso)
    try: abrir(url)
    except Exception: logging.getLogger('gridania').warning('no se pudo abrir el navegador', exc_info=True)
    instancia.publicar(app.cfg.home, url, 'navegador', getattr(srv, 'clave', None))
    if estado.get('arrancar'): estado['arrancar']()           # la base se prepara aunque la ventana nunca llegue a pedirse (idempotente)
    win = estado.get('win')
    if win is not None: _destruir_en_hilo(win)
    return True


def _vigilar_ui(srv, app, estado, url, espera=None, paso=0.5, abrir=None, ampliacion=None, tope=None):
    """Si la UI no pide la pagina en `espera` s (WebView2 ausente/roto/colgado, import de webview bloqueado...) se abre el navegador por defecto con la URL y se avisa.
    Senal de vida (estado['vida'] = instante en que create_window devolvio la ventana): el plazo pasa a max(plazo, vida + ampliacion) sin superar `tope` desde el inicio.
    Si el usuario cerro la ventana antes, no se abre nada."""
    espera = ESPERA_UI_S if espera is None else espera; abrir = abrir or webbrowser.open
    ampliacion = AMPLIACION_S if ampliacion is None else ampliacion; tope = max(TOPE_UI_S, espera) if tope is None else tope
    estado.setdefault('lock', threading.Lock())
    t0 = time.time()
    while True:
        plazo = t0 + espera
        if estado.get('vida'): plazo = min(t0 + tope, max(plazo, estado['vida'] + ampliacion))
        if time.time() >= plazo: break
        if srv.ui_cargada.wait(paso) or srv.salir.is_set(): return
        win = estado.get('win')
        try:
            if win is not None and win.events.closed.is_set(): return          # la cerro el usuario: no se abre nada
        except AttributeError: pass
    _pasar_a_navegador(srv, app, estado, url, abrir, 'La ventana propia no ha cargado en %d s (etapa: %s); se ha abierto el navegador. Instala/repara el WebView2 Runtime de Microsoft para usar la ventana propia.' % (time.time() - t0, estado.get('etapa') or '?'))


def _principal(a, lg, tras_ui=None, aviso=''):
    with registro.fase('aplicacion'):
        app = Aplicacion(a.carpeta, diferir=True)      # solo ajustes y flujo.json: la BD se abre en el hilo de arranque
    if aviso: app.aviso = aviso
    try:
        return _servir(a, lg, app, tras_ui)
    finally:
        cerrar_trabajo(app)


def _abrir_ventana(srv, app, url, estado):
    """import webview + create_window (cada paso registrado). Antes de cada paso lento y al volver se comprueba estado['navegador'] (con el cerrojo): si el navegador ya gano, la
    ventana se cancela (_Cancelada) y la creada tarde se destruye. No arranca el bucle de la GUI: eso lo hace _servir justo tras comprobar de nuevo."""
    def perdida():
        with estado['lock']: return estado['navegador']
    registro.etapa('import webview'); estado['etapa'] = 'import webview'
    with registro.fase('import webview'):
        import webview
    if perdida(): raise _Cancelada('el navegador ya se abrio (import tardio)')
    registro.etapa('deteccion WebView2'); estado['etapa'] = 'deteccion WebView2'
    with registro.fase('deteccion WebView2'):
        logging.getLogger('gridania').info('WebView2 en el registro: %s', webview2_instalado())
    if _sin_runtime():
        _pasar_a_navegador(srv, app, estado, url, estado['abrir'], 'No se ha encontrado el WebView2 Runtime de Microsoft; se ha abierto el navegador. Instalalo para usar la ventana propia.', forzar=True)
        raise _Cancelada('sin WebView2 Runtime')
    if perdida(): raise _Cancelada('el navegador ya se abrio')
    registro.etapa('create_window'); estado['etapa'] = 'create_window'
    with registro.fase('create_window'):
        win = webview.create_window('Editor de traducciones Gridania', url, width=1400, height=900)
    estado['win'] = win; estado['vida'] = time.time()
    if perdida():
        _destruir_en_hilo(win); raise _Cancelada('ventana creada tarde: el navegador ya se abrio')
    for nombre in ('loaded', 'shown', 'closed'):
        try: getattr(win.events, nombre).__iadd__(lambda *x, n=nombre: registro.etapa('evento de ventana: ' + n))
        except Exception: pass
    threading.Thread(target=lambda: (srv.salir.wait(), _intentar(win.destroy)), daemon=True, name='cierre').start()
    return webview


def webview2_instalado():
    """Windows: version del runtime WebView2 segun el registro (None si no se encuentra o no es Windows)"""
    if not sys.platform.startswith('win'): return None
    try:
        import winreg
        for raiz, ruta in ((winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'),
                           (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'),
                           (winreg.HKEY_CURRENT_USER, r'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')):
            try:
                with winreg.OpenKey(raiz, ruta) as k: pv = winreg.QueryValueEx(k, 'pv')[0]
                if pv and pv != '0.0.0.0': return pv       # '0.0.0.0' = desinstalado
            except OSError: continue
    except Exception as x:
        return 'error: %s' % x
    return None


def _servir(a, lg, app, tras_ui=None):
    with registro.fase('servidor'):
        srv = Servidor(app, a.puerto); srv.arrancar()
    url = srv.url
    _decir('Editor Gridania en %s' % url, logging.INFO)
    registro.vigilar_arranque(srv.ui_cargada.is_set)
    arrancar = lambda: app.arrancar_fondo(srv.ui_cargada, tras_ui)       # idempotente: BD + migracion + vigencia, siempre en hilos
    if a.sin_abrir:
        arrancar()
        instancia.publicar(app.cfg.home, url, 'navegador', srv.clave)
        srv.salir.wait(); srv.parar(); return _salida(srv)
    usado = False; estado = {'navegador': False, 'win': None, 'etapa': '', 'lock': threading.Lock(), 'vida': 0, 'arrancar': arrancar, 'abrir': webbrowser.open}
    srv.al_pedir_pagina = lambda: (registro.etapa('primera peticion GET / de la UI'), registro.parar_faulthandler())
    if not a.navegador:
        with registro.fase('vigilante'):
            threading.Thread(target=_vigilar_ui, args=(srv, app, estado, url), kwargs={'abrir': lambda u: estado['abrir'](u)}, daemon=True, name='vigilante-ui').start()
        try:
            webview = _abrir_ventana(srv, app, url, estado)
            arrancar()                                  # tras pedir la ventana; en hilos, nunca la retrasa
            t0 = time.time()
            with estado['lock']:
                if estado['navegador']: raise _Cancelada('el navegador gano justo antes de start')
                instancia.publicar(app.cfg.home, url, 'ventana', srv.clave)
            registro.etapa('webview.start (bucle de la GUI)'); estado['etapa'] = 'webview.start'
            webview.start(lambda: registro.etapa('GUI iniciada (func de start)'))
            registro.etapa('webview.start ha vuelto')
            usado = (srv.ui_cargada.is_set() or time.time() - t0 > 3) and not estado['navegador']
            if not usado and not estado['navegador']:
                app.aviso = 'La ventana propia se cerro al abrirse; se usa el navegador.'; _decir(app.aviso)
        except _Cancelada as x:
            lg.info('ventana propia cancelada: %s', x)
        except Exception as x:
            lg.warning('ventana propia no disponible', exc_info=True)
            app.aviso = 'No se pudo abrir la ventana propia (%s: %s); se usa el navegador. Detalles en el registro.' % (type(x).__name__, x)
            _decir(app.aviso)
    arrancar()
    if not usado:
        _pasar_a_navegador(srv, app, estado, url, estado['abrir'], forzar=True)          # no hace nada si el navegador ya se abrio
        try: srv.salir.wait()
        except KeyboardInterrupt: pass
    srv.parar(); return _salida(srv)


def _salida(srv):
    if srv.fallo:
        msg = 'El servidor del editor ha fallado y se cierra: %s' % srv.fallo
        _decir(msg); _caja('Editor de traducciones Gridania', msg + '\nVer el registro (Ayuda > Abrir carpeta de datos y registros).')
        return 2
    return 0


if __name__ == '__main__':
    terminar(main())
