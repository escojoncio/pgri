"""Extrae ja y fr de una instalacion del juego con el codigo del repo (tools/py/extract_ja.py: Pack, exh, read_rows, write_sheet). Mismo formato que textos/<idioma>/.
SEGURIDAD: se extrae a un directorio temporal (<destino>/_extrayendo) y solo si termina bien se cambia por <destino>/textos (la carpeta anterior se conserva en copias/). Nunca se borra textos/ antes."""
import json, os, re, shutil, time

COPIAS_CONSERVADAS = 3
REINTENTOS = 3          # os.replace: PermissionError transitorio (antivirus, indexador de Windows)
PAUSA_REINTENTO = 0.3


class ExtraccionIncompleta(ValueError):
    """menos de la mitad de las celdas ja que la extraccion anterior: se rechaza salvo forzar=True (la UI pide confirmacion)"""


def _mover(a, b):
    for i in range(REINTENTOS):
        try: return os.replace(a, b)
        except PermissionError:
            if i == REINTENTOS - 1: raise
            time.sleep(PAUSA_REINTENTO)


def contar_celdas(raiz):
    """celdas ja (lineas de <raiz>/textos/ja/**.jsonl) de una extraccion o del repo"""
    n = 0; base = os.path.join(raiz, 'textos', 'ja')
    for d, _, fs in os.walk(base):
        for f in fs:
            if f.endswith('.jsonl'):
                with open(os.path.join(d, f), 'rb') as fh:
                    for blk in iter(lambda: fh.read(1 << 20), b''): n += blk.count(b'\n')
    return n


def _ficheros_hoja(raiz, idioma, hoja):
    base = os.path.join(raiz, 'textos', idioma, *hoja.split('/')); out = []
    if os.path.exists(base + '.jsonl'): out.append(base + '.jsonl')
    n = 1
    while os.path.exists('%s_part%02d.jsonl' % (base, n)): out.append('%s_part%02d.jsonl' % (base, n)); n += 1
    return out


def conservar_hojas(fallidas, respaldo_raiz, nuevo_textos, idiomas):
    """una hoja que falla al leer NO se pierde: se quitan sus restos de la extraccion nueva y se copia la anterior (de respaldo_raiz/textos). -> hojas conservadas"""
    nueva_raiz = os.path.dirname(nuevo_textos); conservadas = []
    for hoja in fallidas:
        for idi in idiomas:
            for f in _ficheros_hoja(nueva_raiz, idi, hoja): os.remove(f)
            if not respaldo_raiz: continue
            for f in _ficheros_hoja(respaldo_raiz, idi, hoja):
                dst = os.path.join(nuevo_textos, idi, os.path.relpath(f, os.path.join(respaldo_raiz, 'textos', idi)))
                os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(f, dst)
                if hoja not in conservadas: conservadas.append(hoja)
    return conservadas
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
    cel = {i: 0 for i in idiomas}; hs = {i: 0 for i in idiomas}; no_leidas = []; fallidas = []
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
            no_leidas.append('%s: %s: %s' % (hoja, type(e).__name__, e)); fallidas.append(hoja)
        if n % 200 == 0: progreso('extrayendo %d/%d (%s)' % (n, len(hojas), hoja))
    return hs, cel, no_leidas, stats, fallidas


def _rotar(copias_dir, conservar):
    try: nombres = sorted(n for n in os.listdir(copias_dir) if os.path.isdir(os.path.join(copias_dir, n)))
    except OSError: return []
    borradas = nombres[:-conservar] if conservar > 0 else nombres
    for n in borradas: shutil.rmtree(os.path.join(copias_dir, n), ignore_errors=True)
    return borradas


def _cambiar(destino, tmp_root, version, copias_dir, progreso):
    """sustituye <destino>/textos y <destino>/info.json por los de <tmp_root>, de forma reversible. Orden: (1) el textos anterior se MUEVE a copias_dir/<fecha>_<version anterior>/textos
    (con una copia de su info.json), (2) textos nuevo -> textos, (3) info.json nuevo -> info.json (os.replace atomico). Si (1), (2) o (3) fallan se deshace todo lo hecho y textos/ e info.json
    quedan como estaban. -> ruta de la copia ('' si no hubo copia)"""
    textos = os.path.join(destino, 'textos'); nuevo = os.path.join(tmp_root, 'textos'); info_v = os.path.join(destino, 'info.json'); info_n = os.path.join(tmp_root, 'info.json')
    copia = ''; viejo = None; basura = None
    if os.path.isdir(textos):
        ver_old = version_de_info(destino)
        if copias_dir and not (ver_old and ver_old == version):     # misma version = mismos datos: no se gasta una de las 3 copias
            sufijo = '_' + version_segura(ver_old)
            copia = os.path.join(copias_dir, time.strftime('%Y%m%d-%H%M%S') + sufijo)
            os.makedirs(copia, exist_ok=True); viejo = os.path.join(copia, 'textos')
        else:
            basura = viejo = os.path.join(destino, 'textos.viejo')
        if basura and os.path.exists(basura): shutil.rmtree(basura, ignore_errors=True)      # resto de un cambio anterior interrumpido (nuestro, no textos/)
        if copia and os.path.exists(info_v):
            try: shutil.copy2(info_v, os.path.join(copia, 'info.json'))
            except OSError: pass
        try: _mover(textos, viejo)
        except BaseException:
            if copia: shutil.rmtree(copia, ignore_errors=True)
            raise
    puesto = False
    try:
        _mover(nuevo, textos); puesto = True
        _mover(info_n, info_v)
    except BaseException:
        if puesto:
            try: _mover(textos, nuevo)                                 # el nuevo vuelve al temporal
            except OSError: pass
        if viejo and os.path.isdir(viejo) and not os.path.exists(textos):
            try: _mover(viejo, textos)
            except OSError: pass
        if copia and os.path.isdir(textos): shutil.rmtree(copia, ignore_errors=True)
        raise
    if basura: shutil.rmtree(basura, ignore_errors=True)
    shutil.rmtree(tmp_root, ignore_errors=True)
    if copias_dir and os.path.isdir(copias_dir): _rotar(copias_dir, COPIAS_CONSERVADAS)
    if copia: progreso('copia de la extraccion anterior: %s' % copia)
    return copia


def extraer(R, ruta_sqpack, destino, idiomas=('ja', 'fr'), progreso=print, antes_de_cambiar=None, copias_dir=None, respaldo_raiz=None, previo_celdas=None, forzar=False):
    """Escribe destino/textos/<idioma>/<hoja>.jsonl (+ destino/info.json con la version del juego). -> info dict (version, hojas, celdas, hojas_conservadas).
    Extrae a destino/_extrayendo; `antes_de_cambiar(ruta_textos_nuevos, info)` (opcional, solo lectura) se llama con la extraccion terminada y ANTES del cambio: si lanza, textos/ queda intacto.
    Una hoja que falla al leer se CONSERVA tal como estaba (de respaldo_raiz o, si no se da, de destino) y se lista en info['hojas_conservadas'].
    previo_celdas = celdas ja de la referencia (por defecto las de info.json anterior): menos de la mitad -> ExtraccionIncompleta salvo forzar=True.
    Cualquier fallo (tambien KeyboardInterrupt) deja destino/textos y destino/info.json exactamente como estaban."""
    comprobar_ruta(ruta_sqpack)
    tmp_root = os.path.join(destino, '_extrayendo')
    if os.path.isdir(tmp_root): shutil.rmtree(tmp_root, ignore_errors=True)      # restos de una extraccion interrumpida
    os.makedirs(destino, exist_ok=True)
    try:
        hs, cel, no_leidas, stats, fallidas = _extraer_a(R, ruta_sqpack, os.path.join(tmp_root, 'textos'), idiomas, progreso)
        if fallidas:
            resp = respaldo_raiz if respaldo_raiz is not None else (destino if os.path.isdir(os.path.join(destino, 'textos')) else None)
            conservadas = conservar_hojas(fallidas, resp, os.path.join(tmp_root, 'textos'), idiomas)
            cel = {i: 0 for i in idiomas}; hs = {i: 0 for i in idiomas}          # recuento real tras conservar las hojas
            for idi in idiomas:
                for d, _, fs in os.walk(os.path.join(tmp_root, 'textos', idi)):
                    for f in fs:
                        if f.endswith('.jsonl') and not re.search(r'_part\d\d\.jsonl$', f):
                            hs[idi] += 1
                        if f.endswith('.jsonl'):
                            with open(os.path.join(d, f), 'rb') as fh: cel[idi] += sum(b.count(b'\n') for b in iter(lambda: fh.read(1 << 20), b''))
        else: conservadas = []
        if not any(cel.values()): raise ValueError('La extraccion no produjo ninguna celda: se conserva la anterior. ¿Es la carpeta correcta (sqpack/ffxiv)?')
        previo = previo_celdas
        if previo is None:
            try:
                with open(os.path.join(destino, 'info.json'), encoding='utf-8') as f: previo = int((json.load(f).get('celdas') or {}).get('ja') or 0)
            except (OSError, ValueError, AttributeError, TypeError): previo = 0
        if previo and cel.get('ja', 0) < previo * RATIO_MINIMO and not forzar:
            raise ExtraccionIncompleta('La extraccion tiene %d celdas ja y la anterior %d (menos de la mitad): parece incompleta; se conserva la anterior. Si es correcta, repite la importacion con «forzar».' % (cel.get('ja', 0), previo))
        info = {'version': raiz_version(ruta_sqpack), 'ruta': ruta_sqpack, 'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'hojas': hs, 'celdas': cel,
                'no_leidas': no_leidas[:50], 'n_no_leidas': len(no_leidas), 'hojas_conservadas': conservadas, 'paginas_ausentes': len(stats['pages_missing'])}
        with open(os.path.join(tmp_root, 'info.json'), 'w', encoding='utf-8') as f: json.dump(info, f, indent=1, ensure_ascii=False)
        if antes_de_cambiar: antes_de_cambiar(os.path.join(tmp_root, 'textos'), dict(info, fallidas=fallidas))
        info['copia_anterior'] = _cambiar(destino, tmp_root, info['version'], copias_dir, progreso)
    except BaseException:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise
    progreso('extraccion lista: %s' % json.dumps({'hojas': hs, 'celdas': cel}))
    if fallidas: progreso('AVISO: %d hojas no se pudieron leer y se conservan como estaban: %s' % (len(fallidas), ', '.join(fallidas[:10])))
    return info
