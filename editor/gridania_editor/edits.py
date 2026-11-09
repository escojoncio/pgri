"""Ediciones locales del usuario: ediciones/traducciones/<hoja>.jsonl con filas {row,sub,col,es,estado:'traducida',h,origen:'sesion'} (mismo formato que traducciones/)."""
import json, os, shutil, time
from . import indexer

ORIGEN = 'sesion'


def ruta(ediciones_dir, hoja):
    return os.path.join(ediciones_dir, 'traducciones', *hoja.split('/')) + '.jsonl'


def linea(e):
    return json.dumps(e, ensure_ascii=False, separators=(',', ':'))


def _escribir(path, filas):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    claves = sorted(filas, key=lambda k: (k[0], -1 if k[1] is None else k[1], k[2]))
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        for k in claves: f.write(linea(filas[k]) + '\n')
    os.replace(tmp, path)


def guardar(base, ediciones_dir, R, c, es):
    """Guarda la edicion (lista de trozos o cadena tokenizada) de la celda con contexto `c`. Lanza ValueError si la fila no cumpliria la lista blanca/hash."""
    e = {'row': c.row, 'sub': c.sub, 'col': c.col, 'es': es, 'estado': 'traducida', 'h': c.h, 'origen': ORIGEN}
    if e['origen'] not in R.C.ORIGENES_VALIDOS: raise ValueError('origen fuera de la lista blanca')
    try: R.C.evaluar_cadena(c.text, c.raw, e)   # ultima puerta: lo que se guarda entra en el .dat
    except R.C.Rechazo as r: raise ValueError('rechazada por construir_dat: %s %s' % (r.motivo, r.detalle))
    p = ruta(ediciones_dir, c.hoja)
    filas = indexer.leer_trad(p)
    filas[c.k] = e
    _escribir(p, filas)
    base.x('UPDATE celdas SET estado=?, es=?, es_json=?, origen=?, h_es=?, editada=1 WHERE hoja=? AND row=? AND sub IS ? AND col=?',
           ('verde', indexer.plano(es), json.dumps(es, ensure_ascii=False), ORIGEN, c.h, c.hoja, c.row, c.sub, c.col))
    return e


def contar(ediciones_dir):
    n = h = 0
    for hoja in indexer.listar_jsonl(os.path.join(ediciones_dir, 'traducciones')):
        h += 1; n += len(indexer.leer_trad(ruta(ediciones_dir, hoja)))
    return {'filas': n, 'hojas': h}


def exportar(ediciones_dir, destino):
    """Copia las ediciones (jsonl por hoja, rutas iguales a las de traducciones/) a destino/cambios_<fecha>/traducciones/. -> dict(carpeta, filas, hojas)"""
    base = os.path.join(ediciones_dir, 'traducciones')
    c = contar(ediciones_dir)
    if not c['filas']: raise ValueError('no hay ediciones que exportar')
    carpeta = os.path.join(destino, 'cambios_' + time.strftime('%Y%m%d-%H%M%S'))
    shutil.copytree(base, os.path.join(carpeta, 'traducciones'))
    c['carpeta'] = carpeta
    return c


def fusionar_en(stage_traducciones, ediciones_dir):
    """aplica las ediciones sobre un arbol traducciones/ ya copiado (reemplaza la fila de la misma clave o la anade al final). -> filas aplicadas"""
    n = 0
    for hoja in indexer.listar_jsonl(os.path.join(ediciones_dir, 'traducciones')):
        ed = indexer.leer_trad(ruta(ediciones_dir, hoja))
        p = os.path.join(stage_traducciones, *hoja.split('/')) + '.jsonl'
        lineas = []; pos = {}
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                for l in f:
                    if not l.strip(): continue
                    lineas.append(l.rstrip('\n'))
                    try: j = json.loads(l); pos[(j['row'], j.get('sub'), j['col'])] = len(lineas) - 1
                    except ValueError: pass
        for k, e in ed.items():
            if k in pos: lineas[pos[k]] = linea(e)
            else: lineas.append(linea(e))
            n += 1
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f: f.write('\n'.join(lineas) + '\n')
        os.replace(tmp, p)
    return n
