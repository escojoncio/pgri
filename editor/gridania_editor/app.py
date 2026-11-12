"""Punto de entrada: servidor local + ventana propia (pywebview/WebView2) o, si no esta disponible, el navegador por defecto.
La ventana sale al instante con «Cargando...»: la migracion de la BD y la comprobacion del indice se hacen en un hilo y la UI muestra su progreso."""
import argparse, logging, multiprocessing, os, sys, threading, time, webbrowser
from . import __version__, config, instancia, registro
from . import stdlib_para_scripts  # noqa: F401  (declara la stdlib que usan los scripts descargados)
from .aplicacion import Aplicacion
from .servidor import Servidor

ESPERA_UI_S = 15    # si la UI no pide la pagina en este tiempo tras empezar a crear la ventana, se abre el navegador por defecto (el servidor sigue vivo)


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
    cerrojo = instancia.adquirir(home)
    if cerrojo is None:
        cerrojo = _recuperar_obsoleta(home, lg)
    if cerrojo is None:
        return _ya_abierto(home, lg)
    try:
        if por_defecto and cerrojo is not None: config.migrar_antigua(home, log=lg)
        return _principal(a, lg)
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


def _vigilar_ui(srv, app, estado, url, espera=None, paso=0.5, abrir=None):
    """Si la UI no pide la pagina en `espera` s (WebView2 ausente/roto/colgado, import de webview bloqueado...) se abre el navegador por defecto con la URL y se avisa.
    El servidor NO se cierra. Si hay ventana propia se intenta cerrar (una sola UI); si el usuario la cerro antes, no se abre nada."""
    espera = ESPERA_UI_S if espera is None else espera; abrir = abrir or webbrowser.open
    t0 = time.time()
    while time.time() - t0 < espera:
        if srv.ui_cargada.wait(paso) or srv.salir.is_set(): return
        win = estado.get('win')
        try:
            if win is not None and win.events.closed.is_set(): return          # la cerro el usuario: no se abre nada
        except AttributeError: pass
    estado['navegador'] = True
    app.aviso = 'La ventana propia no ha cargado en %d s (etapa: %s); se ha abierto el navegador. Instala/repara el WebView2 Runtime de Microsoft para usar la ventana propia.' % (espera, estado.get('etapa') or '?')
    _decir(app.aviso)
    win = estado.get('win')
    if win is not None:
        try: win.destroy()
        except Exception: pass
    instancia.publicar(app.cfg.home, url, 'navegador', getattr(srv, 'clave', None))
    abrir(url)


def _principal(a, lg):
    with registro.fase('aplicacion'):
        app = Aplicacion(a.carpeta, diferir=True)
    if config.AVISO_CARPETA: app.aviso = config.AVISO_CARPETA
    try:
        return _servir(a, lg, app)
    finally:
        cerrar_trabajo(app)


def _abrir_ventana(srv, app, url, estado):
    """import webview + create_window + start en el hilo principal, cada paso registrado. Lo primero tras arrancar el servidor; la preparacion de la base va aparte (hilos)."""
    registro.etapa('import webview'); estado['etapa'] = 'import webview'
    with registro.fase('import webview'):
        import webview
    registro.etapa('deteccion WebView2'); estado['etapa'] = 'deteccion WebView2'
    with registro.fase('deteccion WebView2'):
        lg = logging.getLogger('gridania'); lg.info('WebView2 en el registro: %s', webview2_instalado())
    registro.etapa('create_window'); estado['etapa'] = 'create_window'
    with registro.fase('create_window'):
        win = webview.create_window('Editor de traducciones Gridania', url, width=1400, height=900)
    estado['win'] = win
    lg = logging.getLogger('gridania')
    for nombre in ('loaded', 'shown', 'closed'):
        try: getattr(win.events, nombre).__iadd__(lambda *x, n=nombre: registro.etapa('evento de ventana: ' + n))
        except Exception: pass
    instancia.publicar(app.cfg.home, url, 'ventana', srv.clave)
    threading.Thread(target=lambda: (srv.salir.wait(), win.destroy()), daemon=True, name='cierre').start()
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
                with winreg.OpenKey(raiz, ruta) as k: return winreg.QueryValueEx(k, 'pv')[0]
            except OSError: continue
    except Exception as x:
        return 'error: %s' % x
    return None


def _servir(a, lg, app):
    with registro.fase('servidor'):
        srv = Servidor(app, a.puerto); srv.arrancar()
    url = srv.url
    _decir('Editor Gridania en %s' % url, logging.INFO)
    registro.vigilar_arranque(srv.ui_cargada.is_set)
    if a.sin_abrir:
        app.arrancar_fondo(srv.ui_cargada)
        instancia.publicar(app.cfg.home, url, 'navegador', srv.clave)
        srv.salir.wait(); srv.parar(); return _salida(srv)
    usado = False; estado = {'navegador': False, 'win': None, 'etapa': ''}
    srv.al_pedir_pagina = lambda: (registro.etapa('primera peticion GET / de la UI'), registro.parar_faulthandler())
    if not a.navegador:
        threading.Thread(target=_vigilar_ui, args=(srv, app, estado, url), daemon=True, name='vigilante-ui').start()
        try:
            webview = _abrir_ventana(srv, app, url, estado)
            app.arrancar_fondo(srv.ui_cargada)      # DESPUES de pedir la ventana: la base se prepara en hilos y nunca retrasa su aparicion
            t0 = time.time()
            registro.etapa('webview.start (bucle de la GUI)'); estado['etapa'] = 'webview.start'
            webview.start(lambda: registro.etapa('GUI iniciada (func de start)'))
            registro.etapa('webview.start ha vuelto')
            usado = (srv.ui_cargada.is_set() or time.time() - t0 > 3) and not estado['navegador']
            if not usado and not estado['navegador']:
                app.aviso = 'La ventana propia se cerro al abrirse; se usa el navegador.'; _decir(app.aviso)
        except Exception as x:
            lg.warning('ventana propia no disponible', exc_info=True)
            app.aviso = 'No se pudo abrir la ventana propia (%s: %s); se usa el navegador. Detalles en el registro.' % (type(x).__name__, x)
            _decir(app.aviso)
    app.arrancar_fondo(srv.ui_cargada)              # idempotente (navegador / fallo de la ventana)
    if not usado:
        if not estado['navegador']:
            instancia.publicar(app.cfg.home, url, 'navegador', srv.clave); webbrowser.open(url)
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
