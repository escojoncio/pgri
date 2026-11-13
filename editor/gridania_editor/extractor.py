"""Extrae ja y fr de una instalacion del juego con el codigo del repo (tools/py/extract_ja.py: Pack, exh, read_rows, write_sheet). Mismo formato que textos/<idioma>/.
SEGURIDAD: se extrae a un directorio temporal (<destino>/_extrayendo) y solo si termina bien se cambia por <destino>/textos (la carpeta anterior se conserva en copias/). Nunca se borra textos/ antes."""
import json, os, re, shutil, time

COPIAS_CONSERVADAS = 3
RATIO_MINIMO = 0.5      # una extraccion con menos de la mitad de celdas ja que la anterior se rechaza (pack roto/incompleto)


def raiz_version(ruta_sqpack):
    """ruta .../game/sqpack/ffxiv -> contenido de .../game/ffxivgame.ver ('' si no esta)"""
    d = os.path.abspath(ruta_sqpack)
    for _ in range(3):
        f = os.path.join(d, 'ffxivgame.ver')
        if os.path.exists(f):
            try: return open(f, encoding='utf-8').read().strip()
            except OSError: return ''
        d = os.path.dirname(d)
    return ''


def comprobar_ruta(ruta):
    if not ruta or not os.path.isfile(os.path.join(ruta, '0a0000.win32.index')):
        raise ValueError('La carpeta debe ser sqpack/ffxiv (con 0a0000.win32.index): %r' % ruta)


def version_segura(v):
    """version -> nombre de fichero/carpeta seguro (sin separadores ni '..')"""
    s = re.sub(r'[^0-9A-Za-z._-]+', '_', str(v or '')).strip('._')
    return s or 'sin-version'


def version_de_info(destino):
    try:
        with open(os.path.join(destino, 'info.json'), encoding='utf-8') as f: return str(json.load(f).get('version') or '')
    except (OSError, ValueError, AttributeError): return ''


def _extraer_a(R, ruta_sqpack, out, idiomas, progreso):
    X = R.X
    os.makedirs(out)
    pk = X.Pack(ruta_sqpack)
    exl = pk.read('exd/root.exl')
    if exl is None: raise ValueError('No se pudo leer exd/root.exl del pack')
    hojas = [l.split(',')[0] for l in exl.decode().splitlines()[1:] if l.strip()]
    stats = dict(pages_missing=[], raw_fallback=0)
    cel = {i: 0 for i in idiomas}; hs = {i: 0 for i in idiomas}; no_leidas = []
    for n, hoja in enumerate(hojas):
        try:
            h = X.exh(pk, hoja)
            if h is None: continue
            strcols = [i for i, (t, _) in enumerate(h['cols']) if t == 0]
            if not strcols: continue
            for idi in idiomas:
                lang = idi if idi in h['langs'] else ('' if h['langs'] == [''] else None)
                if lang is None: continue
                rows = X.read_rows(pk, hoja, h, lang, stats)
                if any(rows.values()):
                    _, nstr = X.write_sheet(out, hoja, rows, lang_dir=idi); cel[idi] += nstr; hs[idi] += 1
        except Exception as e:   # una hoja rota no aborta la extraccion
            no_leidas.append('%s: %s: %s' % (hoja, type(e).__name__, e))
        if n % 200 == 0: progreso('extrayendo %d/%d (%s)' % (n, len(hojas), hoja))
    return hs, cel, no_leidas, stats


def _rotar(copias_dir, conservar):
    try: nombres = sorted(n for n in os.listdir(copias_dir) if os.path.isdir(os.path.join(copias_dir, n)))
    except OSError: return []
    borradas = nombres[:-conservar] if conservar > 0 else nombres
    for n in borradas: shutil.rmtree(os.path.join(copias_dir, n), ignore_errors=True)
    return borradas


def _cambiar(destino, tmp_root, version, copias_dir, progreso):
    """sustituye <destino>/textos por <tmp_root>/textos. El textos anterior se MUEVE (rename) a copias_dir/<fecha>_<version anterior>/textos (con su info.json); si falla algo
    se deshace y textos/ queda como estaba. -> ruta de la copia ('' si no hubo copia)"""
    textos = os.path.join(destino, 'textos'); nuevo = os.path.join(tmp_root, 'textos'); info_v = os.path.join(destino, 'info.json')
    copia = ''; viejo = None; basura = None
    if os.path.isdir(textos):
        ver_old = version_de_info(destino)
        if copias_dir and not (ver_old and ver_old == version):     # misma version = mismos datos: no se gasta una de las 3 copias
            sufijo = '_' + version_segura(ver_old)
            copia = os.path.join(copias_dir, time.strftime('%Y%m%d-%H%M%S') + sufijo)
            os.makedirs(copia, exist_ok=True); viejo = os.path.join(copia, 'textos')
        else:
            basura = viejo = os.path.join(destino, 'textos.viejo')
        if basura and os.path.exists(basura): shutil.rmtree(basura)      # resto de un cambio anterior interrumpido (nuestro, no textos/)
        try: os.replace(textos, viejo)
        except BaseException:
            if copia: shutil.rmtree(copia, ignore_errors=True)
            raise
    try:
        os.replace(nuevo, textos)
    except BaseException:
        if viejo and os.path.isdir(viejo) and not os.path.exists(textos): os.replace(viejo, textos)
        if copia: shutil.rmtree(copia, ignore_errors=True)
        raise
    if copia and os.path.exists(info_v):
        try: shutil.copy2(info_v, os.path.join(copia, 'info.json'))
        except OSError: pass
    os.replace(os.path.join(tmp_root, 'info.json'), info_v)
    if basura: shutil.rmtree(basura, ignore_errors=True)
    shutil.rmtree(tmp_root, ignore_errors=True)
    if copias_dir and os.path.isdir(copias_dir): _rotar(copias_dir, COPIAS_CONSERVADAS)
    if copia: progreso('copia de la extraccion anterior: %s' % copia)
    return copia


def extraer(R, ruta_sqpack, destino, idiomas=('ja', 'fr'), progreso=print, antes_de_cambiar=None, copias_dir=None):
    """Escribe destino/textos/<idioma>/<hoja>.jsonl (+ destino/info.json con la version del juego). -> info dict (version, hojas, celdas).
    Extrae a destino/_extrayendo; `antes_de_cambiar(ruta_textos_nuevos, info)` (opcional) se llama con la extraccion terminada y ANTES del cambio: si lanza, textos/ queda intacto.
    Cualquier fallo (tambien KeyboardInterrupt) deja destino/textos y destino/info.json exactamente como estaban."""
    comprobar_ruta(ruta_sqpack)
    tmp_root = os.path.join(destino, '_extrayendo')
    if os.path.isdir(tmp_root): shutil.rmtree(tmp_root)      # restos de una extraccion interrumpida
    os.makedirs(destino, exist_ok=True)
    try:
        hs, cel, no_leidas, stats = _extraer_a(R, ruta_sqpack, os.path.join(tmp_root, 'textos'), idiomas, progreso)
        if not any(cel.values()): raise ValueError('La extraccion no produjo ninguna celda: se conserva la anterior. ¿Es la carpeta correcta (sqpack/ffxiv)?')
        previo = 0
        try:
            with open(os.path.join(destino, 'info.json'), encoding='utf-8') as f: previo = int((json.load(f).get('celdas') or {}).get('ja') or 0)
        except (OSError, ValueError, AttributeError, TypeError): pass
        if previo and cel.get('ja', 0) < previo * RATIO_MINIMO:
            raise ValueError('La extraccion tiene %d celdas ja y la anterior %d (menos de la mitad): parece incompleta; se conserva la anterior.' % (cel.get('ja', 0), previo))
        info = {'version': raiz_version(ruta_sqpack), 'ruta': ruta_sqpack, 'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'hojas': hs, 'celdas': cel,
                'no_leidas': no_leidas[:50], 'n_no_leidas': len(no_leidas), 'paginas_ausentes': len(stats['pages_missing'])}
        with open(os.path.join(tmp_root, 'info.json'), 'w', encoding='utf-8') as f: json.dump(info, f, indent=1, ensure_ascii=False)
        if antes_de_cambiar: antes_de_cambiar(os.path.join(tmp_root, 'textos'), info)
        info['copia_anterior'] = _cambiar(destino, tmp_root, info['version'], copias_dir, progreso)
    except BaseException:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise
    progreso('extraccion lista: %s' % json.dumps({'hojas': hs, 'celdas': cel}))
    return info
