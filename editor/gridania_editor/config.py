"""Ajustes locales. El token personal se guarda SOLO aqui (config.json en la carpeta de trabajo del usuario), nunca en el repo ni en logs.
En Windows se cifra con DPAPI (ligado al usuario de Windows); si no hay DPAPI se guarda en claro (permisos 0600) y la Ayuda lo avisa."""
import base64, json, os, sys, threading

DEFECTO = {'repo': 'escojoncio/gridania', 'rama': 'main', 'token': '', 'ruta_juego': '', 'carpeta_dat': '', 'min_entradas': 757594, 'max_rechazos': 43}
_lock = threading.Lock()


PREFIJO_DPAPI = 'dpapi:'
CRYPTPROTECT_UI_FORBIDDEN = 1


def dpapi_disponible():
    return sys.platform.startswith('win')


def _dpapi(datos, proteger):
    import ctypes
    from ctypes import wintypes
    class BLOB(ctypes.Structure): _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
    pb = ctypes.POINTER(BLOB)
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    if proteger:
        f = crypt32.CryptProtectData
        f.argtypes = [pb, wintypes.LPCWSTR, pb, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, pb]
    else:
        f = crypt32.CryptUnprotectData
        f.argtypes = [pb, ctypes.POINTER(wintypes.LPWSTR), pb, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, pb]
    f.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]; kernel32.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(datos, len(datos))
    ent = BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))); sal = BLOB()
    if not f(ctypes.byref(ent), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(sal)): raise OSError('DPAPI fallo')
    try: return ctypes.string_at(sal.pbData, sal.cbData)
    finally: kernel32.LocalFree(ctypes.cast(sal.pbData, ctypes.c_void_p))


def dpapi_proteger(texto):
    """-> 'dpapi:<base64>' (cifrado para el usuario de Windows actual)"""
    return PREFIJO_DPAPI + base64.b64encode(_dpapi(texto.encode('utf-8'), True)).decode('ascii')


def dpapi_desproteger(valor):
    return _dpapi(base64.b64decode(valor[len(PREFIJO_DPAPI):]), False).decode('utf-8')


def ruta_sincronizada(ruta):
    """-> 'OneDrive' si la ruta esta en una carpeta con 'OneDrive' en el nombre (sincronizada en la nube), si no ''"""
    for parte in os.path.abspath(ruta).replace('\\', '/').split('/'):
        if 'onedrive' in parte.lower(): return 'OneDrive'
    return ''


AVISO_ONEDRIVE = ('El editor esta en una carpeta sincronizada con OneDrive (%s). editor.db pesa unos 400 MB y OneDrive lo bloquea al sincronizar: el arranque y el guardado pueden quedarse '
                  'colgados. Mueve el programa a una carpeta local (p. ej. C:\\GridaniaEditor) o excluye la carpeta datos de la sincronizacion.')

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
        if any(n not in _IGNORAR_MIGRA and n not in _NO_COPIAR for n in os.listdir(nuevo)): return []      # editor.db(-wal/-shm) ya los crea abrir_base
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
        self.datos = dict(DEFECTO); self.proteccion = 'sin_token'; self.aviso_token = ''
        self.recargar()

    def recargar(self):
        """(re)lee config.json; descifra el token (DPAPI) y, si estaba en claro y hay DPAPI, lo reescribe cifrado"""
        nuevo = dict(DEFECTO)
        if os.path.exists(self.ruta):
            try:
                with open(self.ruta, encoding='utf-8') as f: nuevo.update(json.load(f))
            except (OSError, ValueError):
                pass
        t = nuevo.get('token') or ''; self.aviso_token = ''
        if t.startswith(PREFIJO_DPAPI):
            try: nuevo['token'] = dpapi_desproteger(t); self.proteccion = 'dpapi'
            except Exception:
                nuevo['token'] = ''; self.proteccion = 'sin_token'
                self.aviso_token = 'El token guardado no se pudo descifrar (otro usuario o equipo de Windows): vuelve a introducirlo en Ajustes.'
        elif t:
            self.proteccion = 'claro'
        else:
            self.proteccion = 'sin_token'
        self.datos = nuevo
        if self.proteccion == 'claro' and dpapi_disponible():
            try: self.guardar()
            except Exception: pass

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
        d = dict(self.datos); t = d.get('token') or ''
        self.proteccion = 'sin_token' if not t else 'claro'
        if t and dpapi_disponible():
            try: d['token'] = dpapi_proteger(t); self.proteccion = 'dpapi'
            except Exception: pass                      # sin DPAPI utilizable: en claro (la Ayuda lo avisa)
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.ruta)
        try: os.chmod(self.ruta, 0o600)
        except OSError: pass

    def publico(self):
        d = {k: v for k, v in self.datos.items() if k != 'token'}
        d['token_guardado'] = bool(self.datos.get('token')); d['home'] = self.home; d['token_proteccion'] = self.proteccion; d['aviso_token'] = self.aviso_token
        return d

    def redactar(self, texto):
        t = self.datos.get('token')
        return texto.replace(t, '***') if t and isinstance(texto, str) else texto
