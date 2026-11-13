"""Punto de entrada: servidor local + ventana propia (Microsoft Edge/Chrome en modo aplicacion) o, si no esta disponible, el navegador por defecto.
La ventana sale al instante con «Cargando...»: la migracion de la BD y la comprobacion del indice se hacen en un hilo y la UI muestra su progreso."""
import argparse, logging, multiprocessing, os, subprocess, sys, threading, time, webbrowser
from . import __version__, config, instancia, registro, ventana
from . import stdlib_para_scripts  # noqa: F401  (declara la stdlib que usan los scripts descargados)
from .aplicacion import Aplicacion
from .servidor import Servidor

LANZADOR = ventana.lanzar    # (url, home) -> Popen | None; las pruebas lo sustituyen por un lanzador falso

ESPERA_UI_S = 30    # si la UI no pide la pagina en este tiempo (arranque en frio), se abre el navegador por defecto (el servidor sigue vivo)


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
    """termina el proceso YA (hilos de fondo y trabajadores no pueden dejarlo vivo) tras vaciar los registros"""
    try:
        if sys.stdout: sys.stdout.flush()
        if sys.stderr: sys.stderr.flush()
    except Exception: pass
    logging.shutdown()
    os._exit(codigo or 0)


def _matar(proc):
    """termina el proceso de la ventana (sin bloquear)"""
    try:
        if proc is not None and proc.poll() is None: proc.terminate()
    except Exception: pass


def _pasar_a_navegador(srv, app, estado, url, abrir, aviso=None, forzar=False):
    """UNICO ganador: si la ventana ya cargo (salvo `forzar`) o el navegador ya se abrio, no hace nada. Si no: abre el navegador predeterminado y termina la ventana Edge (sin dos UIs).
    El servidor NO se cierra. -> True si abrio el navegador."""
    with estado['lock']:
        if estado['navegador'] or (not forzar and srv.ui_cargada.is_set()): return False
        estado['navegador'] = True
    if aviso: app.aviso = aviso; _decir(aviso)
    try: abrir(url)
    except Exception: logging.getLogger('gridania').warning('no se pudo abrir el navegador', exc_info=True)
    instancia.publicar(app.cfg.home, url, 'navegador', getattr(srv, 'clave', None))
    if estado.get('arrancar'): estado['arrancar']()           # la base se prepara aunque la ventana nunca llegue a pedirse (idempotente)
    _matar(estado.get('proc'))
    return True


def _vigilar_ui(srv, app, estado, url, espera=None, paso=0.5, abrir=None):
    """Si la ventana Edge no pide GET / en `espera` s se abre el navegador predeterminado con la URL y se avisa (sin dos UIs: la ventana se termina).
    Si el usuario cerro la ventana antes (estado['cerrada']), no se abre nada."""
    espera = ESPERA_UI_S if espera is None else espera; abrir = abrir or webbrowser.open
    estado.setdefault('lock', threading.Lock())
    t0 = time.time()
    while time.time() < t0 + espera:
        if srv.ui_cargada.wait(paso) or srv.salir.is_set(): return
        if estado.get('cerrada') and estado['cerrada'].is_set(): return
    _pasar_a_navegador(srv, app, estado, url, abrir, 'La ventana propia (Microsoft Edge) no ha cargado en %d s; se ha abierto el navegador predeterminado.' % (time.time() - t0))


def _principal(a, lg, tras_ui=None, aviso=''):
    with registro.fase('aplicacion'):
        app = Aplicacion(a.carpeta, diferir=True)      # solo ajustes y flujo.json: la BD se abre en el hilo de arranque
    if aviso: app.aviso = aviso
    try:
        return _servir(a, lg, app, tras_ui)
    finally:
        cerrar_trabajo(app)


def _esperar_ventana(srv, proc, estado):
    """espera a que termine el proceso de la ventana (usuario la cierra), a que se pida salir o a que el navegador tome el relevo.
    -> 'cerrada' | 'salir' | 'navegador'"""
    while True:
        if srv.salir.is_set(): return 'salir'
        with estado['lock']:
            if estado['navegador']: return 'navegador'
        try: proc.wait(0.3)
        except subprocess.TimeoutExpired: continue
        estado['cerrada'].set()
        with estado['lock']:
            if estado['navegador']: return 'navegador'
        return 'cerrada'


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
    estado = {'navegador': False, 'proc': None, 'etapa': '', 'lock': threading.Lock(), 'arrancar': arrancar, 'abrir': webbrowser.open, 'cerrada': threading.Event()}
    srv.al_pedir_pagina = lambda: (registro.etapa('primera peticion GET / de la UI'), registro.parar_faulthandler())
    srv.url_navegador = lambda: estado['abrir'](url)
    proc = None
    if not a.navegador:
        registro.etapa('busqueda de Edge/Chrome'); estado['etapa'] = 'lanzar ventana'
        with registro.fase('lanzar ventana'):
            proc = LANZADOR(url, app.cfg.home)
        estado['proc'] = proc
        if proc is None:
            app.aviso = 'No se ha encontrado Microsoft Edge ni Chrome; se usa el navegador predeterminado.'; _decir(app.aviso)
    arrancar()
    if proc is not None:
        with estado['lock']: instancia.publicar(app.cfg.home, url, 'ventana', srv.clave)
        with registro.fase('vigilante'):
            threading.Thread(target=_vigilar_ui, args=(srv, app, estado, url), kwargs={'abrir': lambda u: estado['abrir'](u)}, daemon=True, name='vigilante-ui').start()
        registro.etapa('esperando el cierre de la ventana (pid %s)' % getattr(proc, 'pid', '?'))
        try: res = _esperar_ventana(srv, proc, estado)
        except KeyboardInterrupt: res = 'salir'
        lg.info('ventana: resultado %s, codigo de salida %s', res, proc.poll())
        if res == 'cerrada' and not srv.ui_cargada.is_set():
            app.aviso = 'La ventana propia se cerro al abrirse; se usa el navegador.'; _decir(app.aviso)
            proc = None                                  # cae al navegador predeterminado
        elif res == 'cerrada':
            registro.etapa('ventana cerrada por el usuario: cierre limpio')
            srv.parar(); return _salida(srv)
        elif res == 'salir':
            _matar(proc); srv.parar(); return _salida(srv)
    if proc is None:
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
