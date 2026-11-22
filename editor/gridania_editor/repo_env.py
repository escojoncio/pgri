"""Carga los modulos de tools/py: de una copia descargada de GitHub (OPCIONAL: datos/repo, o el propio repo en las pruebas) o, si no la hay, de la copia EMBEBIDA
(gridania_editor/embebido/tools/py, empaquetada con el .exe: solo codigo y tablas de caja, sin textos). GitHub nunca es requisito."""
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


def raiz_embebida():
    """carpeta con tools/py empaquetada junto al editor (en el .exe: <_MEIPASS>/gridania_editor/embebido; en desarrollo: junto a este modulo); None si falta"""
    base = getattr(sys, '_MEIPASS', None)
    cand = [os.path.join(base, 'gridania_editor', 'embebido')] if base else []
    cand.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'embebido'))
    for c in cand:
        if hay_repo(c): return c
    return None


def raiz_codigo(raiz):
    """raiz de la que se cargan los modulos: la copia descargada si existe (`raiz`), si no la embebida; None si no hay ninguna"""
    if raiz and hay_repo(raiz): return os.path.abspath(raiz)
    return raiz_embebida()


def cargar(raiz, forzar=False):
    """-> objeto con atributos G, S, C, ... (modulos del repo). Recarga si cambia la raiz o forzar (tras actualizar desde GitHub)."""
    dato = os.path.abspath(raiz)
    raiz = raiz_codigo(dato)
    if raiz is None: raise FaltaRepo('No hay tools/py en %s ni embebido en el programa.' % dato)
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
