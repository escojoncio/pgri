"""Punto de entrada: servidor local + ventana propia (pywebview/WebView2) o, si no esta disponible, el navegador por defecto.
La ventana sale al instante con «Cargando...»: la migracion de la BD y la comprobacion del indice se hacen en un hilo y la UI muestra su progreso."""
import argparse, logging, multiprocessing, os, sys, threading, time, webbrowser
from . import __version__, config, instancia, registro
from . import stdlib_para_scripts  # noqa: F401  (declara la stdlib que usan los scripts descargados)
from .aplicacion import Aplicacion
from .servidor import Servidor

ESPERA_UI_S = 25    # tras este tiempo sin pedir la pagina se empieza a comprobar si la ventana propia sigue viva (WebView2 puede tardar en cargar)
MAXIMO_UI_S = 120   # si aun asi la pagina no se ha pedido, la ventana propia no funciona: se cierra y se abre el navegador (nunca las dos UIs)


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
    ap.add_argument('--puerto', type=int, default=0); ap.add_argument('--carpeta', help='carpeta de trabajo (por defecto %%LOCALAPPDATA%%/GridaniaEditor)')
    ap.add_argument('--sin-abrir', action='store_true', help='solo arranca el servidor (pruebas)')
    a = ap.parse_args(argv)
    home = os.path.abspath(a.carpeta or config.carpeta_trabajo())
    lg = registro.iniciar(home, __version__)
    cerrojo = instancia.adquirir(home)
    if cerrojo is None:
        cerrojo = _recuperar_obsoleta(home, lg)
    if cerrojo is None:
        return _ya_abierto(home, lg)
    try:
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


def _vigilar_ui(srv, app, win, estado, url, espera=None, maximo=None, paso=0.5, abrir=None):
    """WebView2 ausente/roto: la ventana no carga y el proceso seguiria en segundo plano. Si la pagina no se pide a tiempo se comprueba que la ventana responda
    (sigue abierta): mientras sea asi se espera hasta `maximo`; si no carga, se CIERRA la ventana y se abre el navegador (una sola UI)."""
    espera = ESPERA_UI_S if espera is None else espera; maximo = MAXIMO_UI_S if maximo is None else maximo; abrir = abrir or webbrowser.open
    if srv.ui_cargada.wait(espera) or srv.salir.is_set(): return
    t0 = time.time()
    while time.time() - t0 < max(0, maximo - espera):
        if srv.ui_cargada.wait(paso) or srv.salir.is_set(): return
        try:
            if win.events.closed.is_set(): return          # la cerro el usuario: no se abre nada
        except AttributeError: pass
    estado['navegador'] = True
    app.aviso = 'La ventana propia (WebView2) no ha cargado; se ha abierto el navegador. Instala el WebView2 Runtime de Microsoft para usar la ventana propia.'
    _decir(app.aviso)
    try: win.destroy()
    except Exception: pass
    instancia.publicar(app.cfg.home, url, 'navegador', getattr(srv, 'clave', None))
    abrir(url)


def _principal(a, lg):
    with registro.fase('aplicacion'):
        app = Aplicacion(a.carpeta, diferir=True)
    try:
        return _servir(a, lg, app)
    finally:
        cerrar_trabajo(app)


def _servir(a, lg, app):
    with registro.fase('servidor'):
        srv = Servidor(app, a.puerto); srv.arrancar()
    url = srv.url
    _decir('Editor Gridania en %s' % url, logging.INFO)
    app.arrancar_fondo()
    if a.sin_abrir:
        instancia.publicar(app.cfg.home, url, 'navegador', srv.clave)
        srv.salir.wait(); srv.parar(); return _salida(srv)
    usado = False; estado = {'navegador': False}
    if not a.navegador:
        try:
            import webview
            win = webview.create_window('Editor de traducciones Gridania', url, width=1400, height=900)
            instancia.publicar(app.cfg.home, url, 'ventana', srv.clave)
            threading.Thread(target=lambda: (srv.salir.wait(), win.destroy()), daemon=True, name='cierre').start()
            threading.Thread(target=_vigilar_ui, args=(srv, app, win, estado, url), daemon=True, name='vigilante-ui').start()
            t0 = time.time()
            webview.start()
            usado = (srv.ui_cargada.is_set() or time.time() - t0 > 3) and not estado['navegador']
            if not usado and not estado['navegador']:
                app.aviso = 'La ventana propia se cerro al abrirse; se usa el navegador.'; _decir(app.aviso)
        except Exception as x:
            lg.warning('ventana propia no disponible', exc_info=True)
            app.aviso = 'No se pudo abrir la ventana propia (%s: %s); se usa el navegador. Detalles en el registro.' % (type(x).__name__, x)
            _decir(app.aviso)
    if not usado:
        if not estado['navegador']:
            instancia.publicar(app.cfg.home, url, 'navegador', srv.clave); webbrowser.open(url)
        try: srv.salir.wait()
        except KeyboardInterrupt: pass
    srv.parar(); return _salida(srv)


def _salida(srv):
    if srv.fallo:
        msg = 'El servidor del editor ha fallado y se cierra: %s' % srv.fallo
        _decir(msg); _caja('Editor de traducciones Gridania', msg + '\nVer el registro (Ayuda > Abrir carpeta de registros).')
        return 2
    return 0


if __name__ == '__main__':
    terminar(main())
