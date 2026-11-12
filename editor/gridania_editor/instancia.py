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


def traer_al_frente():
    """Windows: restaura y enfoca la ventana del editor ya abierta -> bool"""
    if not sys.platform.startswith('win'): return False
    try:
        import ctypes
        u = ctypes.windll.user32; h = u.FindWindowW(None, TITULO)
        if not h: return False
        u.ShowWindow(h, 9); u.SetForegroundWindow(h); return True
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
