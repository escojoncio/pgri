"""Ajustes locales. El token personal se guarda SOLO aqui (config.json en la carpeta de trabajo del usuario), nunca en el repo ni en logs."""
import json, os, sys, threading

DEFECTO = {'repo': 'escojoncio/gridania', 'rama': 'main', 'token': '', 'ruta_juego': '', 'carpeta_dat': '', 'min_entradas': 757594, 'max_rechazos': 43}
_lock = threading.Lock()


AVISO_CARPETA = ''     # se rellena si la carpeta junto al ejecutable no es escribible (la UI/arranque lo muestran)


def carpeta_base():
    """carpeta junto al ejecutable (frozen) o tools/editor (desarrollo)"""
    if getattr(sys, 'frozen', False): return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def carpeta_antigua():
    """ubicacion de versiones anteriores (solo para migrar)"""
    if sys.platform.startswith('win') and os.environ.get('LOCALAPPDATA'): return os.path.join(os.environ['LOCALAPPDATA'], 'GridaniaEditor')
    return os.path.join(os.path.expanduser('~'), '.gridania-editor')


def _escribible(d):
    try:
        os.makedirs(d, exist_ok=True)
        t = os.path.join(d, '.escritura_%d.tmp' % os.getpid())
        with open(t, 'w') as f: f.write('x')
        os.remove(t); return True
    except OSError:
        return False


def carpeta_trabajo():
    """GRIDANIA_EDITOR_HOME > <carpeta del .exe>/datos (en desarrollo tools/editor/datos) > Documentos/GridaniaEditor (con aviso, si la anterior no es escribible)"""
    global AVISO_CARPETA
    v = os.environ.get('GRIDANIA_EDITOR_HOME')
    if v: return os.path.abspath(v)
    d = os.path.join(carpeta_base(), 'datos')
    if _escribible(d): return d
    docs = os.path.join(os.path.expanduser('~'), 'Documents')
    alt = os.path.join(docs if os.path.isdir(docs) else os.path.expanduser('~'), 'GridaniaEditor')
    AVISO_CARPETA = 'La carpeta junto al programa (%s) no es escribible; los datos se guardan en %s. Mueve el programa a una carpeta con permisos de escritura para usar <programa>/datos.' % (d, alt)
    return alt


_IGNORAR_MIGRA = ('editor.log', 'editor.log.1', 'editor.log.2', 'editor.log.3', 'faulthandler.log', 'instancia.lock', 'instancia.json')
_NO_COPIAR = ('editor.db', 'editor.db-wal', 'editor.db-shm', 'repo', 'juego')   # regenerables (indice, cache del repo, extraccion): se rehacen; copiarlos retrasaria la ventana


def migrar_antigua(nuevo, antigua=None, log=None):
    """copia (sin borrar) los datos de la ubicacion antigua a `nuevo` si este esta vacio. -> lista de elementos copiados (vacia si no procede)"""
    import shutil
    antigua = antigua or carpeta_antigua()
    try:
        if not os.path.isdir(antigua) or os.path.abspath(antigua) == os.path.abspath(nuevo): return []
        if any(n not in _IGNORAR_MIGRA for n in os.listdir(nuevo)): return []
        copiados = []
        for n in sorted(os.listdir(antigua)):
            if n in _IGNORAR_MIGRA or n in _NO_COPIAR or n.endswith('.tmp'): continue
            o, d = os.path.join(antigua, n), os.path.join(nuevo, n)
            if os.path.isdir(o): shutil.copytree(o, d, dirs_exist_ok=True)
            else: shutil.copy2(o, d)
            copiados.append(n)
        if log: log.info('migrados desde %s (sin borrar): %s', antigua, copiados)
        return copiados
    except OSError as x:
        if log: log.warning('no se pudo migrar desde %s: %s', antigua, x)
        return []


class Config(object):
    def __init__(self, home=None, repo_override=None):
        self.repo_override = repo_override or os.environ.get('GRIDANIA_EDITOR_REPO')
        self.home = os.path.abspath(home or carpeta_trabajo())
        os.makedirs(self.home, exist_ok=True)
        self.ruta = os.path.join(self.home, 'config.json')
        self.datos = dict(DEFECTO)
        if os.path.exists(self.ruta):
            try:
                with open(self.ruta, encoding='utf-8') as f: self.datos.update(json.load(f))
            except (OSError, ValueError):
                pass

    # rutas derivadas
    def sub(self, *p):
        d = os.path.join(self.home, *p)
        return d
    @property
    def repo_dir(self): return self.repo_override or self.sub('repo')
    @property
    def juego_dir(self): return self.sub('juego')
    @property
    def ediciones_dir(self): return self.sub('ediciones')
    @property
    def db_ruta(self): return self.sub('editor.db')

    def __getitem__(self, k): return self.datos.get(k, DEFECTO.get(k))

    def actualizar(self, nuevos):
        """token vacio/ausente en `nuevos` = no cambia el guardado (la UI nunca recibe el token)"""
        with _lock:
            for k in DEFECTO:
                if k not in nuevos: continue
                v = nuevos[k]
                if k == 'token' and not v: continue
                if k in ('min_entradas', 'max_rechazos'): v = int(v)
                self.datos[k] = v.strip() if isinstance(v, str) else v
            self.guardar()

    def borrar_token(self):
        with _lock:
            self.datos['token'] = ''; self.guardar()

    def guardar(self):
        tmp = self.ruta + '.tmp'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(self.datos, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.ruta)
        try: os.chmod(self.ruta, 0o600)
        except OSError: pass

    def publico(self):
        d = {k: v for k, v in self.datos.items() if k != 'token'}
        d['token_guardado'] = bool(self.datos.get('token')); d['home'] = self.home
        return d

    def redactar(self, texto):
        t = self.datos.get('token')
        return texto.replace(t, '***') if t and isinstance(texto, str) else texto
