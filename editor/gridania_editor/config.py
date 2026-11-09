"""Ajustes locales. El token personal se guarda SOLO aqui (config.json en la carpeta de trabajo del usuario), nunca en el repo ni en logs."""
import json, os, sys, threading

DEFECTO = {'repo': 'escojoncio/gridania', 'rama': 'main', 'token': '', 'ruta_juego': '', 'carpeta_dat': '', 'min_entradas': 757594, 'max_rechazos': 43}
_lock = threading.Lock()


def carpeta_trabajo():
    """GRIDANIA_EDITOR_HOME > %LOCALAPPDATA%/GridaniaEditor (Windows) > ~/.gridania-editor"""
    v = os.environ.get('GRIDANIA_EDITOR_HOME')
    if v: return os.path.abspath(v)
    if sys.platform.startswith('win') and os.environ.get('LOCALAPPDATA'):
        return os.path.join(os.environ['LOCALAPPDATA'], 'GridaniaEditor')
    return os.path.join(os.path.expanduser('~'), '.gridania-editor')


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
