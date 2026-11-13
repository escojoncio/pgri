"""Registro a fichero rotativo (editor.log en la carpeta de datos: <carpeta del programa>/datos, ver config.carpeta_trabajo).
Con --windowed no hay consola: aqui quedan arranque, version, tiempos de cada fase, excepciones no capturadas y fallbacks."""
import contextlib, faulthandler, logging, logging.handlers, os, platform, subprocess, sys, threading, time

NOMBRE = 'editor.log'
_estado = {'home': None}


class RotativoTolerante(logging.handlers.RotatingFileHandler):
    """en Windows la rotacion falla (PermissionError) si otro proceso tiene abierto el log: se sigue escribiendo sin rotar en vez de perder el registro"""
    def doRollover(self):
        try: super().doRollover()
        except OSError as x:
            try:
                if self.stream is None: self.stream = self._open()
            except OSError: pass
            sys.stderr and sys.stderr.write('registro: no se pudo rotar (%s)\n' % x)


def ruta_log(home): return os.path.join(home, NOMBRE)


def iniciar(home, version='?', consola=True):
    """configura el logger 'gridania' (idempotente) y engancha las excepciones no capturadas de hilos y del principal"""
    _estado['home'] = home
    lg = logging.getLogger('gridania'); lg.setLevel(logging.INFO)
    if getattr(lg, '_ge_listo', False): return lg
    try:
        os.makedirs(home, exist_ok=True)
        h = RotativoTolerante(ruta_log(home), maxBytes=1000000, backupCount=3, encoding='utf-8')
        h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s'))
        lg.addHandler(h)
    except OSError as x:
        sys.stderr and sys.stderr.write('no se pudo abrir el registro: %s\n' % x)
    if consola and sys.stderr is not None:
        c = logging.StreamHandler(sys.stderr); c.setLevel(logging.WARNING); c.setFormatter(logging.Formatter('%(levelname)s %(message)s')); lg.addHandler(c)
    def hook(tipo, valor, tb):
        lg.critical('excepcion no capturada', exc_info=(tipo, valor, tb))
    def hook_hilo(a):
        lg.critical('excepcion no capturada en el hilo %s', a.thread.name if a.thread else '?', exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    sys.excepthook = hook; threading.excepthook = hook_hilo
    lg._ge_listo = True
    lg.info('arranque: editor %s, python %s, %s, frozen=%s, pid=%d, home=%s', version, platform.python_version(), platform.platform(), bool(getattr(sys, 'frozen', False)), os.getpid(), home)
    return lg


_activas = {}          # fases en curso: id -> (nombre, t0, hilo)
_activas_lock = threading.Lock()
_etapa = {'texto': '', 't': 0.0}


def etapa(texto):
    """marca la etapa del hilo principal (ventana) y la registra; el vigilante la incluye en su volcado"""
    _etapa['texto'] = texto; _etapa['t'] = time.time()
    logging.getLogger('gridania').info('etapa: %s', texto)


def fases_activas():
    """-> lista de textos 'nombre (N s, hilo)' de lo que esta en curso ahora"""
    ahora = time.time()
    with _activas_lock: v = list(_activas.values())
    return ['%s (%.0f s, %s)' % (n, ahora - t, h) for n, t, h in v]


@contextlib.contextmanager
def fase(nombre):
    """mide y registra el tiempo de una fase (inicio y fin; mientras dura figura en fases_activas)"""
    t = time.time(); lg = logging.getLogger('gridania'); k = object()
    with _activas_lock: _activas[id(k)] = (nombre, t, threading.current_thread().name)
    lg.info('fase %s: inicio', nombre)
    try: yield
    except BaseException as x:
        lg.error('fase %s: FALLO tras %.2f s (%s: %s)', nombre, time.time() - t, type(x).__name__, x); raise
    finally:
        with _activas_lock: _activas.pop(id(k), None)
    lg.info('fase %s: %.2f s', nombre, time.time() - t)


_fh = {'f': None, 'abierto': None, 'timer': None}
FAULTHANDLER_MAX_BYTES = 1000000


def activar_faulthandler(home, cada=30, max_minutos=5, max_bytes=None):
    """faulthandler a faulthandler.log: ante un cuelgue duro vuelca las pilas de TODOS los hilos cada `cada` s, SOLO mientras la UI no cargue (parar_faulthandler lo cancela)
    y, si nunca carga, se para solo a los `max_minutos` min. El fichero se trunca al arrancar si supera `max_bytes` (1 MB). Con el volcado periodico parado queda activo el
    volcado ante fallo fatal (segfault)."""
    max_bytes = FAULTHANDLER_MAX_BYTES if max_bytes is None else max_bytes
    try:
        ruta = os.path.join(home, 'faulthandler.log')
        try: grande = os.path.getsize(ruta) > max_bytes
        except OSError: grande = False
        f = open(ruta, 'w' if grande else 'a', encoding='utf-8'); f.write('--- %s pid=%d\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), os.getpid())); f.flush()
        faulthandler.enable(file=f, all_threads=True); faulthandler.dump_traceback_later(cada, repeat=True, file=f)
        _fh['f'] = f; _fh['abierto'] = f      # 'abierto' mantiene el fichero vivo para el volcado ante fallo fatal
        if max_minutos:
            t = threading.Timer(max_minutos * 60, lambda: parar_faulthandler('tope de %s min' % max_minutos)); t.daemon = True; t.start(); _fh['timer'] = t
        logging.getLogger('gridania').info('faulthandler activo (volcado cada %d s hasta que cargue la UI o %s min, en faulthandler.log)', cada, max_minutos)
        return f
    except Exception as x:
        logging.getLogger('gridania').warning('faulthandler no disponible: %s', x); return None


def parar_faulthandler(motivo='arranque completo'):
    f = _fh['f']
    t = _fh.get('timer'); _fh['timer'] = None
    if t is not None: t.cancel()
    if f is None: return
    try: faulthandler.cancel_dump_traceback_later()
    except Exception: pass
    _fh['f'] = None
    logging.getLogger('gridania').info('faulthandler: volcados periodicos cancelados (%s)', motivo)


def vigilar_arranque(listo, paso=10.0):
    """hilo que, mientras `listo()` sea falso o haya fases en curso, registra cada `paso` s la etapa de la ventana y las fases activas. Devuelve el hilo."""
    lg = logging.getLogger('gridania')
    def correr():
        while True:
            time.sleep(paso)
            act = fases_activas(); ok = listo()
            if ok and not act: return
            lg.warning('vigilancia: etapa=%r (%.0f s) fases=%s ui_cargada=%s', _etapa['texto'], time.time() - _etapa['t'] if _etapa['t'] else 0, act or '-', ok)
    h = threading.Thread(target=correr, daemon=True, name='vigilancia'); h.start(); return h


def abrir_carpeta(home=None):
    """abre la carpeta de registros en el explorador del sistema -> ruta"""
    d = home or _estado['home']
    if not d: raise RuntimeError('registro no iniciado')
    os.makedirs(d, exist_ok=True)
    try:
        if sys.platform.startswith('win'): os.startfile(d)   # noqa
        elif sys.platform == 'darwin': subprocess.Popen(['open', d])
        else: subprocess.Popen(['xdg-open', d], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as x:
        logging.getLogger('gridania').warning('no se pudo abrir la carpeta de registros: %s', x)
    return d
