"""Ventana propia SIN pywebview/pythonnet: Microsoft Edge (o Chrome) en modo aplicacion, con perfil propio para que el proceso viva mientras la ventana este abierta
(Popen.wait detecta el cierre). Sin Edge/Chrome -> None y el llamador usa el navegador predeterminado."""
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


def linea_comando(exe, url, perfil, ancho=1400, alto=900):
    return [exe, '--app=%s' % url, '--user-data-dir=%s' % perfil, '--no-first-run', '--no-default-browser-check', '--window-size=%d,%d' % (ancho, alto)]


def lanzar(url, home, buscar=None, popen=subprocess.Popen):
    """abre la ventana. -> Popen o None (sin Edge/Chrome o fallo al lanzarlo)"""
    exe = (buscar or buscar_navegador)()
    if not exe: return None
    perfil = os.path.join(home, 'perfil-ventana')
    try: os.makedirs(perfil, exist_ok=True)
    except OSError: pass
    cmd = linea_comando(exe, url, perfil)
    log.info('linea de comandos de la ventana: %s', cmd)
    try: p = popen(cmd)
    except Exception:
        log.warning('no se pudo lanzar la ventana', exc_info=True); return None
    log.info('ventana lanzada: pid %s', getattr(p, 'pid', '?'))
    return p
