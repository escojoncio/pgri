"""Punto de entrada: servidor local + ventana propia (Microsoft Edge/Chrome en modo aplicacion) o, si no esta disponible, el navegador por defecto.
La ventana sale al instante con «Cargando...»: la migracion de la BD y la comprobacion del indice se hacen en un hilo y la UI muestra su progreso."""
import argparse, logging, multiprocessing, os, subprocess, sys, threading, time, webbrowser
from . import __version__, config, instancia, registro, ventana
from . import stdlib_para_scripts  # noqa: F401  (declara la stdlib que usan los scripts descargados)
from .aplicacion import Aplicacion
from .servidor import Servidor

LANZADOR = ventana.lanzar    # (url, home) -> Popen | None; las pruebas lo sustituyen por un lanzador falso

ESPERA_UI_S = 30    # si la UI no pide la pagina en este tiempo (arranque en frio, o lanzador que no abrio nada), se abre el navegador por defecto (el servidor sigue vivo)
GRACIA_CIERRE_S = 10        # tras /api/cierre (sendBeacon) sin latido ni GET / en este tiempo -> cierre (si hay F5 la pagina vuelve a pedirse antes)
UMBRAL_LATIDO_S = 180       # sin latido tanto tiempo desde la primera carga Y perfil de la ventana libre -> cierre (180 s por el throttling de pestañas ocultas/minimizadas)
UMBRAL_SIN_LOCK_S = 300     # igual sin poder comprobar el perfil (no Windows)
PASO_VIGILANTE_S = 0.5
MIN_LATIDOS = 2            # latidos recibidos en la sesion antes de poder cerrar por la rama de 180 s
HUECO_SUSPENSION_S = 5     # hueco entre iteraciones del vigilante que delata suspension/hibernacion del equipo
MARGEN_DESPERTAR_S = 30    # tras despertar: nada se cierra hasta un latido nuevo o este margen
UMBRAL_ZOMBI_S = 900       # perfil bloqueado pero SIN ventana visible con el titulo y sin latido: se cierra (Edge zombi)
UMBRAL_POCOS_LATIDOS_S = 300   # con menos de MIN_LATIDOS latidos (pagina que apenas llego a latir) la rama de latido espera este tiempo en vez de bloquear el cierre para siempre
UMBRAL_SIN_VENTANA_S = 30      # ventana ausente de forma sostenida: cierre SIN mirar perfil_libre si ademas hay este tiempo sin latido
INTERVALO_VENTANA_S = 5        # separacion entre comprobaciones de hay_ventana (EnumWindows)
COMPROBACIONES_SIN_VENTANA = 3 # comprobaciones consecutivas sin ventana para darla por ausente
AVISO_NAVEGADOR = ' En el navegador el editor NO se cierra solo al cerrar la pestaña: usa el boton Salir.'


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
    El pid del Popen es solo una pista: aunque el lanzador haya salido al instante, se espera el plazo completo por si la ventana es de un proceso delegado."""
    espera = ESPERA_UI_S if espera is None else espera; abrir = abrir or webbrowser.open
    estado.setdefault('lock', threading.Lock())
    t0 = time.time()
    while time.time() < t0 + espera:
        if srv.ui_cargada.wait(paso) or srv.salir.is_set(): return
    _pasar_a_navegador(srv, app, estado, url, abrir, 'La ventana propia (Microsoft Edge) no ha cargado en %d s; se ha abierto el navegador predeterminado.' % (time.time() - t0) + AVISO_NAVEGADOR)


def _principal(a, lg, tras_ui=None, aviso=''):
    with registro.fase('aplicacion'):
        app = Aplicacion(a.carpeta, diferir=True)      # solo ajustes y flujo.json: la BD se abre en el hilo de arranque
    if aviso: app.aviso = aviso
    try:
        return _servir(a, lg, app, tras_ui)
    finally:
        cerrar_trabajo(app)


def motivo_cierre(srv, ahora, libre, gracia=None, umbral=None, umbral_sin_lock=None, ventana_visible=None, umbral_zombi=None, min_latidos=None, ventana_ausente=False, umbral_sin_ventana=None):
    """decide si hay que cerrar (funcion pura sobre las marcas de tiempo de `srv`, en time.monotonic()). -> texto del motivo o None.
    libre: perfil de la ventana libre (True/False/None=no comprobable). ventana_visible: hay ventana con el titulo (True/False/None).
    Un latido o un GET / posterior a /api/cierre lo anula (era una recarga). Tras suspender (t_despertar) no se cierra nada hasta un latido nuevo o MARGEN_DESPERTAR_S."""
    gracia = GRACIA_CIERRE_S if gracia is None else gracia
    umbral = UMBRAL_LATIDO_S if umbral is None else umbral; umbral_sin_lock = UMBRAL_SIN_LOCK_S if umbral_sin_lock is None else umbral_sin_lock
    umbral_zombi = UMBRAL_ZOMBI_S if umbral_zombi is None else umbral_zombi; min_latidos = MIN_LATIDOS if min_latidos is None else min_latidos
    actividad = max([t for t in (srv.t_latido, srv.t_get) if t is not None] or [None], key=lambda t: -1 if t is None else t)
    desp = getattr(srv, 't_despertar', None)
    if desp is not None and (actividad is None or actividad <= desp) and ahora - desp < MARGEN_DESPERTAR_S: return None
    if srv.t_cierre is not None:
        if actividad is not None and actividad > srv.t_cierre: srv.t_cierre = None           # recarga (F5): la pagina volvio
        else:
            t = srv.t_cierre if desp is None else max(srv.t_cierre, desp)                    # la gracia se reinicia al despertar
            if ahora - t >= gracia: return 'cierre explicito de la ventana y %s s sin latido ni GET /' % gracia
    if srv.ui_cargada.is_set() and actividad is not None:
        sin = ahora - actividad
        if libre is False and ventana_visible is False and sin >= umbral_zombi: return '%s s sin latido, perfil bloqueado y sin ventana visible (Edge zombi)' % umbral_zombi
        umbral_sin_ventana = UMBRAL_SIN_VENTANA_S if umbral_sin_ventana is None else umbral_sin_ventana
        if ventana_ausente and sin >= umbral_sin_ventana: return '%s s sin latido y ventana ausente de forma sostenida (perfil %s)' % (umbral_sin_ventana, {True: 'libre', False: 'ocupado', None: 'no comprobable'}[libre])
        limite = umbral_sin_lock if libre is None else umbral
        if getattr(srv, 'n_latidos', 0) < min_latidos: limite = max(limite, UMBRAL_POCOS_LATIDOS_S)       # pocos latidos: umbral largo, no bloqueo eterno
        if libre is not False and sin >= limite: return '%s s sin latido y perfil de la ventana %s' % (limite, 'libre' if libre else 'no comprobable')
    return None


class SeguimientoVentana:
    """hay_ventana() como mucho cada `intervalo` s; `ausente` = `minimo` comprobaciones consecutivas con False (None/True reinician la cuenta)."""
    def __init__(self, f, intervalo=None, minimo=None):
        self.f = f; self.intervalo = INTERVALO_VENTANA_S if intervalo is None else intervalo; self.minimo = COMPROBACIONES_SIN_VENTANA if minimo is None else minimo
        self.t = None; self.visible = None; self.n = 0

    def reiniciar(self): self.t = None; self.visible = None; self.n = 0

    def actualizar(self, ahora):
        if self.f is None: return None, False
        if self.t is None or ahora - self.t >= self.intervalo:
            self.t = ahora; self.visible = self.f(); self.n = self.n + 1 if self.visible is False else 0
        return self.visible, self.n >= self.minimo


def _vigilar_cierre(srv, estado, libre, paso=None, reloj=None, ventana_visible=None):
    """hilo de la ventana propia: cierra el editor por latido (NUNCA porque el Popen terminase). Se detiene al salir o si el navegador toma el relevo (sin cierre por latido, solo Salir)."""
    paso = PASO_VIGILANTE_S if paso is None else paso; reloj = reloj or time.monotonic; ultimo = reloj(); seg = SeguimientoVentana(ventana_visible)
    while not srv.salir.wait(paso):
        ahora = reloj(); hueco = ahora - ultimo; ultimo = ahora
        if hueco > HUECO_SUSPENSION_S:           # el equipo estuvo suspendido/hibernado: los relojes saltaron, no hubo latidos reales
            srv.t_despertar = ahora; seg.reiniciar(); logging.getLogger('gridania').info('hueco de %.0f s en el vigilante (suspension): se reinicia la gracia', hueco); continue
        with estado['lock']:
            if estado['navegador']: return
        try:
            visible, ausente = seg.actualizar(ahora); motivo = motivo_cierre(srv, ahora, libre(), ventana_visible=visible, ventana_ausente=ausente)
        except Exception:
            logging.getLogger('gridania').warning('vigilante de cierre', exc_info=True); continue
        if motivo:
            logging.getLogger('gridania').info('cierre por latido: %s', motivo); registro.etapa('ventana cerrada por el usuario: cierre limpio')
            srv.salir.set(); return


def _esperar_ventana(srv, estado):
    """espera a que se pida salir (boton, o el vigilante de latido) o a que el navegador tome el relevo. El Popen no interviene. -> 'salir' | 'navegador'"""
    while True:
        if srv.salir.is_set(): return 'salir'
        with estado['lock']:
            if estado['navegador']: return 'navegador'
        time.sleep(0.2)


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
    estado = {'navegador': False, 'proc': None, 'etapa': '', 'lock': threading.Lock(), 'arrancar': arrancar, 'abrir': webbrowser.open}
    srv.al_pedir_pagina = lambda: (registro.etapa('primera peticion GET / de la UI'), registro.parar_faulthandler())
    srv.url_navegador = lambda: estado['abrir'](url)
    proc = None
    if not a.navegador:
        registro.etapa('busqueda de Edge/Chrome'); estado['etapa'] = 'lanzar ventana'
        with registro.fase('lanzar ventana'):
            proc = LANZADOR(url, app.cfg.home)
        estado['proc'] = proc
        if proc is None:
            app.aviso = 'No se ha encontrado Microsoft Edge ni Chrome; se usa el navegador predeterminado.' + AVISO_NAVEGADOR; _decir(app.aviso)
    arrancar()
    if proc is not None:
        with estado['lock']: instancia.publicar(app.cfg.home, url, 'ventana', srv.clave)
        with registro.fase('vigilante'):
            threading.Thread(target=_vigilar_ui, args=(srv, app, estado, url), kwargs={'abrir': lambda u: estado['abrir'](u)}, daemon=True, name='vigilante-ui').start()
            threading.Thread(target=_vigilar_cierre, args=(srv, estado, lambda: ventana.perfil_libre(app.cfg.home, pid_vivo=lambda: proc.poll() is None, hay_ventana=instancia.hay_ventana)), kwargs={'ventana_visible': instancia.hay_ventana}, daemon=True, name='vigilante-cierre').start()
        registro.etapa('esperando el cierre de la ventana por latido (pid %s, solo pista)' % getattr(proc, 'pid', '?'))
        try: res = _esperar_ventana(srv, estado)
        except KeyboardInterrupt: res = 'salir'
        lg.info('ventana: resultado %s, codigo de salida del pid %s', res, proc.poll() if hasattr(proc, 'poll') else '?')
        if res == 'salir':
            _matar(proc); srv.parar(); return _salida(srv)
    else:
        if a.navegador and not app.aviso.strip().endswith(AVISO_NAVEGADOR.strip()): app.aviso = (app.aviso + AVISO_NAVEGADOR).strip()
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
