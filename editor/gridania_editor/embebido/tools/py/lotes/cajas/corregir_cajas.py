#!/usr/bin/env -S python3 -I
"""CORRECTOR DETERMINISTA de cajas de texto (dry-run por defecto; --escribir escribe traducciones/ con backup en trabajo/lotes/bak/<hoja>.<fecha>.cajas.jsonl).
Para cada celda con problema GRAVE (auditar_cajas: PALABRA_SUELTA, MACRO_NO_CONTADA, SUBTITULO_EXCEDE, ALTO_EXCEDE) o LINEA_EXCEDE, prueba candidatos del motor existente segun el
perfil de caja y se queda con el mejor SOLO si baja la puntuacion del auditor (nunca empeora) y pasa construir_dat.evaluar_cadena:
  * dialogo/sistema/descripcion/guia: reflujar_lineas.procesar_celda (+ reflujar_v2 con ventana final y reflujar_ventana_final.lf_final), con W = ancho seguro y seguro-2;
  * subtitulo: reflujar_subtitulos.reflujar_lista (DP por trozos) o procesar_celda con tope.
Mismo h/origen/estado; misma estructura de trozos (un trozo es por trozo ja); no se recorta ni se toca el texto (solo espacios y saltos entre trozos vecinos).
Lo que no se puede arreglar con saltos (hay que reescribir/acortar) se lista en trabajo/informes/cajas_no_arreglables.tsv (para reescritura Haiku).
CAJA_DESCONOCIDA y FR_EXCEDE no se corrigen (no hay medida): solo se listan en el auditor.

Uso: python3 -I tools/py/lotes/cajas/corregir_cajas.py [--hojas H1,H2|subcadenas] [--claves hoja:row:col ...] [--escribir] [--jobs N] [--no-arreglables F.tsv] [--root R]
API: corregir_hoja(root, hoja, claves=None, escribir=False) -> dict(stats, cambios, no_arreglables)."""
import sys, os, re, json, argparse, collections, datetime, shutil
AQUI = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, AQUI)
import nucleo as N
R = N.R; G = N.G; C = N.C
import reflujar_v2 as V
import reflujar_ventana_final as VF; VF.instalar()
import reflujar_subtitulos as SUB

NO_ARR = os.path.join(N.RAIZ, 'trabajo', 'informes', 'cajas_no_arreglables.tsv')
OBJETIVO = ('PALABRA_SUELTA', 'MACRO_NO_CONTADA', 'SUBTITULO_EXCEDE', 'ALTO_EXCEDE', 'LINEA_EXCEDE')
_PF = None


def objetivo(c, pf):
    """en dialogo/guia el juego envuelve las lineas largas solas: LINEA_EXCEDE no es un fallo por si mismo (solo cuenta si crea PALABRA_SUELTA/ALTO_EXCEDE)"""
    if c == 'LINEA_EXCEDE': return pf.tipo in ('sistema', 'descripcion', 'hud_fijo')
    return c in OBJETIVO


def _estado(pf, W):
    R.CFG.macros = True; R.CFG.paginar = pf.tipo == 'dialogo'; R.CFG.ancho_max = pf.duro; R.TOL = pf.duro
    V.VF['on'] = pf.tipo == 'dialogo' and pf.lineas >= 3; VF.LF['on'] = pf.tipo == 'dialogo'
    VF.FILAS[:] = []; VF.CUR['fam'] = 'cajas'; VF.CUR['hoja'] = ''
    V.REGISTRO[:] = []


def _candidatos(pf, text, raw, e, clave, listas=False):
    """-> lista de es candidatos (str o lista) segun el perfil"""
    out = []
    if pf.tipo == 'subtitulo':
        for W in (pf.seguro, pf.seguro - 2):
            _estado(pf, W); R.CFG.paginar = False; V.VF['on'] = False; SUB.W_ACT[0] = W; R.TOL = W; R.CFG.ancho_max = W
            es = e['es']
            if isinstance(es, list) and not any('<' in x for x in es) and len(es) >= 2:
                nes = SUB.reflujar_lista(es)
                if nes is not None and ' '.join(' '.join(nes).split()) == ' '.join(' '.join(es).split()): out.append(nes)
            try: res = R.procesar_celda(text, raw, e, W, False, clave, {})
            except Exception: continue
            if res[0] == 'cambiada': out.append(res[1])
        return out
    creador = pf.tipo in ('sistema', 'descripcion', 'guia')
    if pf.envuelve:
        c = _cand_lf(e['es'], pf, listas)
        if c is not None: out.append(c)
    for W in (pf.seguro, pf.seguro - 2):
        _estado(pf, W)
        try: res = R.procesar_celda(text, raw, e, W, creador, clave, {})
        except Exception: continue
        if res[0] == 'cambiada': out.append(res[1])
    return out


def balancear(txt, W):
    """texto plano (sin macros ni saltos) -> el mismo texto con LF reales repartiendo las palabras en k lineas equilibradas (k = lineas que daria la envoltura), o None"""
    ws = txt.split(' ')
    if len(ws) < 4 or any(w == '' for w in ws): return None
    k = len(N.envolver(txt, N.Perfil(seguro=W, duro=W, tipo='dialogo')))
    if k < 2: return None
    meta = len(txt) / float(k); lineas = []; cur = []
    for i, w in enumerate(ws):
        l = len(' '.join(cur + [w])); restantes = len(ws) - i - 1; faltan = k - len(lineas) - 1
        if cur and faltan > 0 and (l > W or (l > meta and abs(len(' '.join(cur)) - meta) <= abs(l - meta)) or restantes < faltan): lineas.append(' '.join(cur)); cur = [w]
        else: cur.append(w)
    lineas.append(' '.join(cur))
    return '\n'.join(lineas) if len(lineas) == k and all(len(x) <= W for x in lineas) else None


def _cand_lf(es, pf, listas):
    """candidato: inserta LF reales dentro de las lineas duras sin macros cuya envoltura deja una palabra suelta. str siempre; listas solo con --lf-en-listas (el exe real no lo ha validado)"""
    W = pf.seguro
    def fix(seg):
        pre = R.prefijo_len(seg); body = seg[pre:]
        if not body or '<' in body or '\n' in body: return seg
        ls = N.envolver(body, pf)
        if len(ls) < 2 or N._pal(ls[-1]) > 2: return seg
        b = balancear(body, W - 1)
        return seg[:pre] + b if b else seg
    if isinstance(es, list):
        if not listas: return None
        nes = [fix(x) for x in es]
    else:
        partes = re.split(r'(<NewLine(?:#\d+)?>)', es)
        nes = ''.join(x if x.startswith('<NewLine') else fix(x) for x in partes)
    return None if nes == es else nes


def _cadena(es, ja_t):
    return N.cadena_tokenizada(es, ja_t[0], ja_t[1])


def corregir_hoja(root, hoja, claves=None, escribir=False, perfiles=None, listas=False):
    """claves: conjunto de (row, sub, col) a considerar (None = todas las de la hoja)."""
    global _PF
    pf_all = perfiles or _PF or N.Perfiles(); _PF = pf_all
    out = dict(stats=collections.Counter(), cambios=[], no_arreglables=[])
    path = os.path.join(root, 'traducciones', hoja + '.jsonl')
    if not os.path.exists(path): return out
    ja = G.leer_ja(root, hoja)
    if ja is None: return out
    fr = None
    with open(path, encoding='utf-8') as f: lineas = f.read().split('\n')
    fin_nl = bool(lineas) and lineas[-1] == ''
    if fin_nl: lineas.pop()
    ult = {}
    for n, l in enumerate(lineas):
        if l.strip(): j = json.loads(l); ult[(j['row'], j.get('sub'), j['col'])] = n
    st = out['stats']; nuevas = {}
    for k, n in ult.items():
        if claves is not None and k not in claves: continue
        e = json.loads(lineas[n])
        if e.get('estado') != 'traducida' or e.get('origen') not in C.ORIGENES_VALIDOS or k not in ja: continue
        es = e['es']
        if not (isinstance(es, str) or (isinstance(es, list) and all(isinstance(x, str) for x in es))): continue
        clave = ja.get((k[0], k[1], 0), ('', None))[0]
        pf = pf_all.de(hoja, k[2], k[0], clave)
        if not pf.conocido: continue
        ja_t = ja[k]
        s0 = _cadena(es, ja_t)
        if s0 is None: continue
        frm = None
        if pf.fr_ref:
            if fr is None: fr = N.leer_fr(root, hoja)
            if k in fr: frm = N.medida_fr(fr[k], pf)
        c0, _ = N.problemas(s0, pf, frm); obj0 = [c for c in c0 if objetivo(c, pf)]
        if not obj0: continue
        st['con_problema'] += 1
        p0 = N.puntuacion(c0); mejor = None
        for cand in _candidatos(pf, ja_t[0], ja_t[1], e, clave, listas):
            if cand == es: continue
            e2 = dict(e); e2['es'] = cand
            try: C.evaluar_cadena(ja_t[0], ja_t[1], e2)
            except C.Rechazo: st['rechazo_validacion'] += 1; continue
            s1 = _cadena(cand, ja_t)
            if s1 is None: continue
            c1, _ = N.problemas(s1, pf, frm); p1 = N.puntuacion(c1)
            sc = (p1, len(c1))
            if (p1, len(c1)) < (p0, len(c0)) and (mejor is None or sc < mejor[0]): mejor = (sc, cand, c1)
        if mejor is None:
            st['sin_mejora'] += 1
            out['no_arreglables'].append((hoja, k, pf.tipo, sorted(set(obj0)), es, ja_t[0], (fr or {}).get(k, '') if fr else ''))
            continue
        _, cand, c1 = mejor
        resto = [c for c in c1 if objetivo(c, pf)]
        st['arregladas' if not resto else 'mejoradas'] += 1
        if resto: out['no_arreglables'].append((hoja, k, pf.tipo, sorted(set(resto)), cand, ja_t[0], (fr or {}).get(k, '') if fr else ''))
        e['es'] = cand; nuevas[n] = json.dumps(e, ensure_ascii=False, separators=(',', ':'))
        out['cambios'].append((hoja, k, es, cand))
    if nuevas and escribir:
        bak = os.path.join(root, 'trabajo', 'lotes', 'bak'); os.makedirs(bak, exist_ok=True)
        shutil.copy2(path, os.path.join(bak, '%s.%s.cajas.jsonl' % (hoja.replace('/', '__'), datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))))
        for n, l in nuevas.items(): lineas[n] = l
        tmp = path + '.tmp.%d' % os.getpid()
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f: f.write('\n'.join(lineas) + ('\n' if fin_nl else ''))
        os.replace(tmp, path)
    return out


def corregir_celdas(root, claves_por_hoja, escribir=True):
    """claves_por_hoja: {hoja: iterable de (row, sub, col)}. Para los aplicadores. -> (arregladas, mejoradas, no_arreglables)"""
    arr = mej = 0; noarr = []
    for h, ks in claves_por_hoja.items():
        r = corregir_hoja(root, h, set(ks), escribir)
        arr += r['stats']['arregladas']; mej += r['stats']['mejoradas']; noarr += r['no_arreglables']
    return arr, mej, noarr


def _job(args):
    root, hoja, claves, escribir, listas = args
    try:
        r = corregir_hoja(root, hoja, claves, escribir, listas=listas)
        return hoja, r['stats'], r['no_arreglables'], r['cambios'][:3]
    except Exception as x:
        return hoja, collections.Counter({'error': 1}), [], [('ERROR', type(x).__name__ + ': ' + str(x))]


def escribir_no_arreglables(ruta, filas):
    nuevo = not os.path.exists(ruta) or os.path.getsize(ruta) == 0
    with open(ruta, 'a', encoding='utf-8', newline='\n') as f:
        if nuevo: f.write('hoja\trow\tsub\tcol\ttipo\tproblemas\tes\tja\tfr\n')
        for hoja, k, tipo, probs, es, ja, fr in filas:
            t = es if isinstance(es, str) else ' || '.join(es)
            f.write('\t'.join(str(x).replace('\t', ' ').replace('\n', '\\n') for x in (hoja, k[0], '' if k[1] is None else k[1], k[2], tipo, ','.join(probs), t, ja, fr)) + '\n')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--hojas', default=''); ap.add_argument('--claves', action='append', default=[]); ap.add_argument('--root', default=N.RAIZ)
    ap.add_argument('--escribir', action='store_true'); ap.add_argument('--jobs', type=int, default=min(8, os.cpu_count() or 1)); ap.add_argument('--no-arreglables', default=None, help='por defecto %s (solo con --escribir)' % NO_ARR)
    ap.add_argument('--ejemplos', type=int, default=0); ap.add_argument('--lf-en-listas', action='store_true', help='permite insertar LF dentro de un trozo de una lista (valido en la emulacion; sin probar en el exe de pgri)')
    a = ap.parse_args(argv)
    porh = collections.defaultdict(set)
    for c in a.claves:
        h, r, col = c.rsplit(':', 2); porh[h].add((int(r), None, int(col)))
    if porh: hojas = sorted(porh)
    else:
        filtro = [x for x in a.hojas.split(',') if x]
        hojas = [h for h in N.listar_hojas(a.root) if not filtro or any(h == f or h.startswith(f) or f in h for f in filtro)]
    tareas = [(a.root, h, (porh.get(h) if porh else None), a.escribir, a.lf_en_listas) for h in hojas]
    tot = collections.Counter(); noarr = []; ej = []
    if a.jobs > 1 and len(tareas) > 1:
        import multiprocessing as mp
        with mp.get_context('fork').Pool(a.jobs) as p: res = list(p.imap_unordered(_job, tareas, chunksize=4))
    else: res = [_job(t) for t in tareas]
    for h, st, na, cs in res:
        tot.update(st); noarr += na; ej += cs
    print('CORREGIR CAJAS%s: %d hojas | con problema %d | arregladas %d | mejoradas %d | sin mejora %d | rechazo_validacion %d | errores %d' % (
        '' if a.escribir else ' [DRY-RUN]', len(hojas), tot['con_problema'], tot['arregladas'], tot['mejoradas'], tot['sin_mejora'], tot['rechazo_validacion'], tot['error']))
    for c in ej[:a.ejemplos]: print(c)
    destino = a.no_arreglables or (NO_ARR if a.escribir else None)
    if destino:
        if os.path.exists(destino): os.remove(destino)
        escribir_no_arreglables(destino, sorted(noarr, key=lambda x: (x[0], x[1][0], x[1][2])))
        print('no arreglables: %d -> %s' % (len(noarr), destino))
    elif noarr: print('no arreglables (dry-run, no se escribe fichero salvo --no-arreglables explicito): %d' % len(noarr))
    return 0

if __name__ == '__main__': sys.exit(main())
