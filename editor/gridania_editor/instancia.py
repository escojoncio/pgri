"""Instancia unica: un cerrojo de fichero en la carpeta de datos. Relanzar el .exe no crea otro proceso: se avisa y se trae al frente la ventana existente
(o se reabre su pagina si corre en el navegador)."""
import json, os, sys, time

CERROJO = 'instancia.lock'
INFO = 'instancia.json'
TITULO = 'Editor de traducciones Gridania'


def _bloquear(f):
    if sys.platform.startswith('win'):
        import msvcrt
        f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def adquirir(home):
    """-> manejador (mantenerlo vivo mientras corra el proceso) o None si ya hay otra instancia"""
    os.makedirs(home, exist_ok=True)
    f = open(os.path.join(home, CERROJO), 'a+')
    try: _bloquear(f)
    except OSError:
        f.close(); return None
    return f


def publicar(home, url, modo, clave=None):
    try:
        with open(os.path.join(home, INFO), 'w', encoding='utf-8') as f: json.dump({'pid': os.getpid(), 'url': url, 'modo': modo, 'clave': clave, 'fecha': time.time()}, f)
    except OSError: pass


def existente(home):
    try:
        with open(os.path.join(home, INFO), encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError): return {}


def liberar(home, f):
    try:
        if existente(home).get('pid') == os.getpid(): os.remove(os.path.join(home, INFO))
    except OSError: pass
    try: f and f.close()
    except OSError: pass


def _user32():
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL('user32', use_last_error=True)
    return u


def _tipar(u, CB):
    """tipos explicitos (sin ellos ctypes trunca HWND a 32 bits en 64 bits)"""
    from ctypes import wintypes
    import ctypes
    for nombre, args, res in (('EnumWindows', [CB, wintypes.LPARAM], wintypes.BOOL), ('IsWindowVisible', [wintypes.HWND], wintypes.BOOL),
                              ('GetWindowTextLengthW', [wintypes.HWND], ctypes.c_int), ('GetWindowTextW', [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
                              ('ShowWindow', [wintypes.HWND, ctypes.c_int], wintypes.BOOL), ('SetForegroundWindow', [wintypes.HWND], wintypes.BOOL)):
        f = getattr(u, nombre)
        try: f.argtypes = args; f.restype = res
        except AttributeError: pass            # solo un user32 falso de pruebas puede no admitir atributos


def _ventanas(titulo, u):
    import ctypes
    from ctypes import wintypes
    hallada = []; clave = titulo.lower()
    CB = getattr(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE)(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _tipar(u, CB)
    def cb(h, _):
        if not u.IsWindowVisible(h): return True
        n = u.GetWindowTextLengthW(h)
        if n <= 0: return True
        buf = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, buf, n + 1)
        if clave in buf.value.lower(): hallada.append(h)
        return True
    u.EnumWindows(CB(cb), 0)
    return hallada


def hay_ventana(titulo=TITULO, user32=None):
    """Windows: hay alguna ventana visible cuyo titulo CONTIENE `titulo` -> True/False; None si no se puede comprobar"""
    if user32 is None and not sys.platform.startswith('win'): return None
    try: return bool(_ventanas(titulo, user32 or _user32()))
    except Exception: return None


def traer_al_frente(titulo=TITULO, user32=None):
    """Windows: restaura y enfoca la ventana del editor ya abierta (EnumWindows: titulo que CONTIENE `titulo`; Edge puede anadir texto al titulo) -> bool"""
    if user32 is None and not sys.platform.startswith('win'): return False
    try:
        u = user32 or _user32(); hallada = _ventanas(titulo, u)
        if not hallada: return False
        h = hallada[0]; u.ShowWindow(h, 9); u.SetForegroundWindow(h); return True
    except Exception: return False


def responde(info, timeout=2.0):
    """la instancia anotada en instancia.json sigue viva: su servidor contesta GET /api/estado con la clave publicada -> bool"""
    import urllib.request
    url = (info or {}).get('url'); clave = (info or {}).get('clave')
    if not url or not clave: return False
    try:
        rq = urllib.request.Request(url.rstrip('/') + '/api/estado', headers={'X-K': clave})
        with urllib.request.urlopen(rq, timeout=timeout) as r: return r.status == 200
    except Exception: return False
