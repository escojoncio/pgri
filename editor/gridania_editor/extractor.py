"""Extrae ja y fr de una instalacion del juego con el codigo del repo (tools/py/extract_ja.py: Pack, exh, read_rows, write_sheet). Mismo formato que textos/<idioma>/."""
import json, os, shutil, time


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


def extraer(R, ruta_sqpack, destino, idiomas=('ja', 'fr'), progreso=print):
    """Escribe destino/textos/<idioma>/<hoja>.jsonl. -> info dict (version, hojas, celdas). Borra una extraccion anterior."""
    comprobar_ruta(ruta_sqpack)
    X = R.X
    out = os.path.join(destino, 'textos')
    if os.path.isdir(out): shutil.rmtree(out)
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
    info = {'version': raiz_version(ruta_sqpack), 'ruta': ruta_sqpack, 'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'hojas': hs, 'celdas': cel,
            'no_leidas': no_leidas[:50], 'n_no_leidas': len(no_leidas), 'paginas_ausentes': len(stats['pages_missing'])}
    with open(os.path.join(destino, 'info.json'), 'w', encoding='utf-8') as f: json.dump(info, f, indent=1, ensure_ascii=False)
    progreso('extraccion lista: %s' % json.dumps({'hojas': hs, 'celdas': cel}))
    return info
