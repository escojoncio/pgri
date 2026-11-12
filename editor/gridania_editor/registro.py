"""Registro a fichero rotativo (editor.log en la carpeta de datos: %LOCALAPPDATA%/GridaniaEditor en Windows, ~/.gridania-editor en el resto).
Con --windowed no hay consola: aqui quedan arranque, version, tiempos de cada fase, excepciones no capturadas y fallbacks."""
import contextlib, logging, logging.handlers, os, platform, subprocess, sys, threading, time

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


@contextlib.contextmanager
def fase(nombre):
    """mide y registra el tiempo de una fase"""
    t = time.time(); lg = logging.getLogger('gridania')
    lg.info('fase %s: inicio', nombre)
    try: yield
    except BaseException as x:
        lg.error('fase %s: FALLO tras %.2f s (%s: %s)', nombre, time.time() - t, type(x).__name__, x); raise
    lg.info('fase %s: %.2f s', nombre, time.time() - t)


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
