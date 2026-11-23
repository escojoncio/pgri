"""Ventana propia SIN pywebview/pythonnet: Microsoft Edge (o Chrome) en modo aplicacion con perfil propio.
El pid del Popen es solo una PISTA (el lanzador puede delegar y salir, o Edge seguir en segundo plano): el cierre de la ventana se detecta por latido de la UI (ver app.py).
Perfil: <datos>/perfil-ventana (junto al programa; nunca en AppData). NO son datos del usuario, solo cache/cookies del navegador; se puede borrar.
Sin Edge/Chrome -> None y el llamador usa el navegador predeterminado."""
import logging, os, subprocess, sys

log = logging.getLogger('gridania')
EJECUTABLES = ('msedge.exe', 'chrome.exe')
CLAVE_RUTAS = r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\%s'


def _registro(winreg, nombre):
    """rutas de `nombre` segun App Paths (HKLM, HKLM 32 bits, HKCU)"""
    for raiz, vista in (('HKEY_LOCAL_MACHINE', 0), ('HKEY_CURRENT_USER', 0), ('HKEY_LOCAL_MACHINE', 0x0100)):
        try:
            with winreg.OpenKey(getattr(winreg, raiz), CLAVE_RUTAS % nombre) as k:
                v = winreg.QueryValueEx(k, '')[0]
            if v: yield os.path.expandvars(str(v).strip('"'))
        except OSError: continue


def candidatos(env=None, winreg=None):
    """rutas candidatas en orden de preferencia: Edge (registro, Program Files) y luego Chrome"""
    env = os.environ if env is None else env
    if winreg is None and sys.platform.startswith('win'):
        try: import winreg
        except ImportError: winreg = None
    sal = []
    pf = [env.get('ProgramFiles(x86)'), env.get('ProgramFiles'), env.get('LOCALAPPDATA')]
    sub = {'msedge.exe': ('Microsoft', 'Edge', 'Application', 'msedge.exe'), 'chrome.exe': ('Google', 'Chrome', 'Application', 'chrome.exe')}
    for nombre in EJECUTABLES:
        if winreg is not None: sal.extend(_registro(winreg, nombre))
        sal.extend(os.path.join(b, *sub[nombre]) for b in pf if b)
    vistos = []
    for r in sal:
        if r and r not in vistos: vistos.append(r)
    return vistos


def buscar_navegador(env=None, winreg=None, existe=os.path.isfile):
    """-> ruta del primer Edge/Chrome que existe, o None. Cada candidato queda en el registro."""
    for r in candidatos(env, winreg):
        ok = existe(r); log.info('busqueda de Edge/Chrome: %s -> %s', r, 'encontrado' if ok else 'no existe')
        if ok: return r
    log.warning('busqueda de Edge/Chrome: ninguno encontrado')
    return None


def dir_perfil(home, env=None):
    """perfil del navegador de la ventana: SIEMPRE dentro de la carpeta de datos del editor (junto al .exe), nunca en %LOCALAPPDATA%. `env` se conserva por compatibilidad y no se usa."""
    return os.path.join(home, 'perfil-ventana')


def perfil_libre(home, env=None, pid_vivo=None, hay_ventana=None):
    """el navegador de la ventana ya no usa el perfil: True libre, False ocupado, None no comprobable (no Windows).
    Chromium mantiene `lockfile` abierto en exclusiva mientras alguno de sus procesos vive con ese perfil."""
    if not sys.platform.startswith('win'): return None
    lock = os.path.join(dir_perfil(home, env), 'lockfile')
    if not os.path.exists(lock):
        # lockfile ausente con el navegador vivo (p. ej. aun no creado o perfil movido) NO es 'libre': el pid de la ventana o una ventana con el titulo lo desmienten
        try:
            if pid_vivo and pid_vivo(): return False
            if hay_ventana and hay_ventana(): return False
        except Exception: return False
        return True
    try:
        with open(lock, 'rb'): pass
        os.rename(lock, lock)
        return True
    except OSError: return False


def linea_comando(exe, url, perfil, ancho=1400, alto=900):
    return [exe, '--app=%s' % url, '--user-data-dir=%s' % perfil, '--no-first-run', '--no-default-browser-check', '--window-size=%d,%d' % (ancho, alto),
            '--disable-features=msEdgeStartupBoost', '--disable-background-mode']


def lanzar(url, home, buscar=None, popen=subprocess.Popen, env=None):
    """abre la ventana. -> Popen o None (sin Edge/Chrome, perfil no creable o fallo al lanzarlo). El Popen es solo una pista."""
    exe = (buscar or buscar_navegador)()
    if not exe: return None
    perfil = dir_perfil(home, env)
    try: os.makedirs(perfil, exist_ok=True)
    except OSError:
        log.warning('no se pudo crear el perfil de la ventana %s: se usa el navegador predeterminado', perfil, exc_info=True); return None
    cmd = linea_comando(exe, url, perfil)
    log.info('linea de comandos de la ventana: %s', cmd)
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if sys.platform.startswith('win'): kw['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    try: p = popen(cmd, **kw)
    except Exception:
        log.warning('no se pudo lanzar la ventana', exc_info=True); return None
    log.info('ventana lanzada: pid %s (solo pista)', getattr(p, 'pid', '?'))
    return p


URL_IA = 'https://gemini.google.com/app'


def lanzar_ia(home, url=URL_IA, buscar=None, popen=subprocess.Popen, env=None, puerto=None):
    """mini ventana de Gemini (Edge/Chrome en modo aplicacion, cerrable, perfil propio `<datos>/perfil-ia` para conservar el inicio de sesion).
    NO usa el navegador predeterminado. -> Popen, o None si no hay Edge/Chrome o no se pudo lanzar. No participa en el latido/cierre del editor."""
    exe = (buscar or buscar_navegador)()
    if not exe: return None
    perfil = os.path.join(home, 'perfil-ia')
    try: os.makedirs(perfil, exist_ok=True)
    except OSError:
        log.warning('no se pudo crear el perfil de la ventana de IA %s', perfil, exc_info=True); return None
    cmd = linea_comando(exe, url, perfil, 540, 860)
    if puerto: cmd += ['--remote-debugging-port=%d' % puerto, '--remote-allow-origins=*']      # solo 127.0.0.1; permite escribir el prompt (ia_cdp)
    log.info('ventana de IA: %s', cmd)
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if sys.platform.startswith('win'): kw['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    try: return popen(cmd, **kw)
    except Exception:
        log.warning('no se pudo lanzar la ventana de IA', exc_info=True); return None
