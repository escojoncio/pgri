"""Carga los modulos de tools/py de una copia del repo (la descargada en la carpeta de trabajo, o el propio repo en las pruebas). El .exe no los contiene."""
import importlib, os, sys
from . import zstshim

NOMBRES = {'G': 'segmentar', 'S': 'sestring', 'C': 'construir_dat', 'NSJ': 'normalizar_signos_japoneses', 'NPS': 'normalizar_puntos_suspensivos',
           'RL': 'reflujar_lineas', 'SS': 'suavizar_saltos', 'NC': 'nucleo', 'LAT': 'latinismos', 'AG': 'auditar_global', 'SIMB': 'auditar_simbologia',
           'AS': 'auditar_say', 'X': 'extract_ja', 'BB': 'build_blob', 'NJ': 'netjson'}
_actual = {'raiz': None, 'mods': None}


class FaltaRepo(Exception):
    pass


def _rutas(raiz):
    py = os.path.join(raiz, 'tools', 'py')
    return [py, os.path.join(py, 'lotes'), os.path.join(py, 'lotes', 'cajas')]


def hay_repo(raiz):
    return os.path.exists(os.path.join(raiz, 'tools', 'py', 'construir_dat.py'))


def cargar(raiz, forzar=False):
    """-> objeto con atributos G, S, C, ... (modulos del repo). Recarga si cambia la raiz o forzar (tras actualizar desde GitHub)."""
    raiz = os.path.abspath(raiz)
    if not hay_repo(raiz): raise FaltaRepo('No hay tools/py en %s: pulsa «Actualizar desde GitHub» primero.' % raiz)
    if _actual['raiz'] == raiz and not forzar and _actual['mods'] is not None: return _actual['mods']
    # purga de modulos del repo anterior
    rutas = [os.path.normcase(p) for p in _rutas(raiz)]
    if _actual['raiz'] is not None or forzar:
        for nombre, m in list(sys.modules.items()):
            f = getattr(m, '__file__', None) or ''
            if f and any(os.path.normcase(os.path.abspath(f)).startswith(os.path.normcase(os.path.join(r0, 'tools', 'py'))) for r0 in [_actual['raiz'] or raiz, raiz]):
                del sys.modules[nombre]
    for p in reversed(_rutas(raiz)):
        if p in sys.path: sys.path.remove(p)
        sys.path.insert(0, p)
    if 'zst' in sys.modules and getattr(sys.modules['zst'], '__file__', None): del sys.modules['zst']
    zstshim.instalar()
    mods = type('Repo', (), {})()
    mods.raiz = raiz
    for attr, nombre in NOMBRES.items():
        setattr(mods, attr, importlib.import_module(nombre))
    mods.PF = mods.NC.Perfiles(os.path.join(raiz, 'tools', 'py', 'lotes', 'cajas', 'perfiles_caja.tsv'))
    mods.SS.iniciar(raiz)
    _actual['raiz'] = raiz; _actual['mods'] = mods
    return mods
