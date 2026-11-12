"""Ediciones locales del usuario: ediciones/traducciones/<hoja>.jsonl con filas {row,sub,col,es,estado:'traducida',h,origen:'sesion'} (mismo formato que traducciones/)."""
import collections, json, os, shutil, time
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


def guardar(base, ediciones_dir, R, c, es, comprobar=True):
    """Guarda la edicion (lista de trozos o cadena tokenizada) de la celda con contexto `c`. Lanza ValueError si la fila no cumpliria la lista blanca/hash.
    La ocupacion se comprueba UNA vez, al inicio (comprobar=False si el llamador ya la comprobo antes de un bucle): no entre escribir el fichero y el UPDATE."""
    if comprobar: base.exigir_libre()
    e = {'row': c.row, 'sub': c.sub, 'col': c.col, 'es': es, 'estado': 'traducida', 'h': c.h, 'origen': ORIGEN}
    if e['origen'] not in R.C.ORIGENES_VALIDOS: raise ValueError('origen fuera de la lista blanca')
    try: R.C.evaluar_cadena(c.text, c.raw, e)   # ultima puerta: lo que se guarda entra en el .dat
    except R.C.Rechazo as r: raise ValueError('rechazada por construir_dat: %s %s' % (r.motivo, r.detalle))
    previa = indexer.firma_actual(base, c.hoja)   # firma ANTES de tocar el fichero
    p = ruta(ediciones_dir, c.hoja)
    filas = indexer.leer_trad(p)
    filas[c.k] = e
    _escribir(p, filas)
    base.x('UPDATE celdas SET estado=?, es=?, es_json=?, origen=?, h_es=?, editada=1 WHERE hoja=? AND row=? AND sub IS ? AND col=?',
           ('verde', indexer.plano(es), json.dumps(es, ensure_ascii=False), ORIGEN, c.h, c.hoja, c.row, c.sub, c.col), comprobar=False)
    indexer.refirmar(base, c.hoja, previa)   # la BD ya coincide con el fichero de ediciones: la hoja sigue vigente en el indice persistente
    return e


def _fila_db(base, hoja, row, sub, col):
    r = base.q('SELECT id,estado,es,es_json,origen,h_es,editada FROM celdas WHERE hoja=? AND row=? AND sub IS ? AND col=?', (hoja, row, sub, col))
    return dict(r[0]) if r else None


def guardar_lote(base, ediciones_dir, R, items):
    """items = [(c, es)]. Una lectura/escritura del jsonl por hoja. -> (hechos, fallos): hechos = [{'c', 'previa' (fila de ediciones previa o None), 'db' (valores de la celda antes)}]"""
    base.exigir_libre()
    por_hoja = collections.OrderedDict()
    for c, es in items: por_hoja.setdefault(c.hoja, []).append((c, es))
    hechos = []; fallos = []
    for hoja, lst in por_hoja.items():
        p = ruta(ediciones_dir, hoja); filas = indexer.leer_trad(p); cambios = []
        for c, es in lst:
            e = {'row': c.row, 'sub': c.sub, 'col': c.col, 'es': es, 'estado': 'traducida', 'h': c.h, 'origen': ORIGEN}
            try:
                if e['origen'] not in R.C.ORIGENES_VALIDOS: raise ValueError('origen fuera de la lista blanca')
                try: R.C.evaluar_cadena(c.text, c.raw, e)
                except R.C.Rechazo as r: raise ValueError('rechazada por construir_dat: %s %s' % (r.motivo, r.detalle))
            except ValueError as x: fallos.append((c, str(x))); continue
            hechos.append({'c': c, 'previa': filas.get(c.k), 'db': _fila_db(base, c.hoja, c.row, c.sub, c.col)})
            filas[c.k] = e; cambios.append((c, es))
        if cambios:
            previa = indexer.firma_actual(base, hoja)
            _escribir(p, filas)
            with base.lock:
                base.con.executemany('UPDATE celdas SET estado=?, es=?, es_json=?, origen=?, h_es=?, editada=1 WHERE hoja=? AND row=? AND sub IS ? AND col=?',
                                     [('verde', indexer.plano(es), json.dumps(es, ensure_ascii=False), ORIGEN, c.h, c.hoja, c.row, c.sub, c.col) for c, es in cambios])
                base.con.commit()
            indexer.refirmar(base, hoja, previa)
    return hechos, fallos


def restaurar_lote(base, ediciones_dir, celdas):
    """celdas = [{'hoja','row','sub','col','previa','db'}]: devuelve cada celda a su estado anterior (fila de ediciones previa o ninguna; valores de db originales, origen incluido). Una escritura por hoja."""
    base.exigir_libre()
    por_hoja = collections.OrderedDict()
    for x in celdas: por_hoja.setdefault(x['hoja'], []).append(x)
    for hoja, lst in por_hoja.items():
        p = ruta(ediciones_dir, hoja); filas = indexer.leer_trad(p); previa = indexer.firma_actual(base, hoja)
        for x in lst:
            k = (x['row'], x['sub'], x['col'])
            if x.get('previa'): filas[k] = x['previa']
            else: filas.pop(k, None)
        if filas: _escribir(p, filas)
        elif os.path.exists(p): os.remove(p)
        d = [(x['db']['estado'], x['db']['es'], x['db']['es_json'], x['db']['origen'], x['db']['h_es'], 1 if x.get('previa') else 0, hoja, x['row'], x['sub'], x['col']) for x in lst if x.get('db')]
        with base.lock:
            base.con.executemany('UPDATE celdas SET estado=?, es=?, es_json=?, origen=?, h_es=?, editada=? WHERE hoja=? AND row=? AND sub IS ? AND col=?', d)
            base.con.commit()
        indexer.refirmar(base, hoja, previa)


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
