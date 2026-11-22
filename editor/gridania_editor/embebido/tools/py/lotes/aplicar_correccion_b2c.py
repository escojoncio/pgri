#!/usr/bin/env -S python3 -I
"""Aplica a traducciones/ las correcciones del bloque 2 (tandas b2c): trabajo/lotes/b2c/resc_corr_pNN.jsonl contra lote_correccion_b2_pNN.jsonl (+ _est).
Uso: python3 -I tools/py/lotes/aplicar_correccion_b2c.py [--partes p01,p02] [--dir trabajo/lotes/b2c] [--rechazos F] [--dry-run]
Entrada resc_corr: una linea por (hoja,row,sub,col[,parte]) = {"hoja","row","sub","col","es":[trozos],"estado","h"[,"parte"]}. En filas complejas `es` lleva SOLO los trozos
traducibles (como el compacto); se reinsertan los fijos y se unen las partes en orden (B.expandir_fijos / B.fusionar_partes, igual que expandir_resultados.py).
Una parte (pNN) con registros esperados sin escribir (o lineas ilegibles/duplicadas sin cubrir) se SALTA entera y se informa (--partes limita las procesadas; por defecto, las que tengan resc_corr).
Validaciones = aplicar_resultados (trozos, vacios, CJK/U+3000/anchura, INTOCABLES, h, estado, ALIN_DIGITOS/PROPORCION, fijos de complejas) + construir_dat.evaluar_cadena (simulacion).
Origen escrito: fr-ja-retrad (resultado y copias del lote). Sustituye la linea de esa clave (pista `linea`) sin duplicar: pisa corpus/dudosa, o cualquier linea cuyo origen siga siendo `origen_actual`; `anadir` crea
la linea. Copias = campo `copias` del lote (mismo japones). Backup por hoja en trabajo/lotes/bak/. Idempotente.
Lo que siga rechazado -> --rechazos (por defecto trabajo/informes/b2c_rechazos_final.tsv; hoja,row,sub,col,motivo; se fusiona con lo ya escrito: las claves de las partes procesadas se reemplazan)."""
import argparse, collections, csv, datetime, glob, json, os, re, sys
AQUI = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, AQUI); sys.path.insert(0, os.path.join(AQUI, '..'))
import aplicar_resultados as A
import _bloque as B
import segmentar as G
import construir_dat as C
import reponer_intocables as RI
RAIZ = A.RAIZ

def cargar_resc(ruta):
    """-> ({(hoja,row,sub,col,parte): registro}, [lineas ilegibles])"""
    res = {}; malas = []
    with open(ruta, encoding='utf-8') as f:
        for n, l in enumerate(f, 1):
            if not l.strip(): continue
            try:
                v = json.loads(l)
                if not (isinstance(v, dict) and all(x in v for x in ('hoja', 'row', 'sub', 'col', 'es', 'estado', 'h'))): raise ValueError('campos')
            except ValueError: malas.append(n); continue
            res[(v['hoja'], v['row'], v['sub'], v['col'], v.get('parte', 1))] = v
    return res, malas

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--partes'); ap.add_argument('--dir'); ap.add_argument('--rechazos'); ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--reponer', action='store_true', help='antes de validar, repone de forma determinista los intocables (glifos PUA/controles/marcadores) que faltan en es (reponer_intocables.py)')
    a = ap.parse_args()
    d = os.path.abspath(a.dir) if a.dir else os.path.join(RAIZ, 'trabajo', 'lotes', 'b2c')
    f_rech = a.rechazos or os.path.join(RAIZ, 'trabajo', 'informes', 'b2c_rechazos_final.tsv')
    quiero = [x if x.startswith('p') else 'p' + x for x in a.partes.split(',')] if a.partes else None
    todas = sorted(re.search(r'_(p\d+)\.jsonl$', f).group(1) for f in glob.glob(os.path.join(d, 'resc_corr_p*.jsonl')))
    partes = [p for p in todas if quiero is None or p in quiero]
    for p in (quiero or []):
        if p not in todas: print('SALTADA %s: no existe resc_corr_%s.jsonl' % (p, p))
    glos = A.cargar_glosario_alin(); longs = sorted({len(x) for x in glos})
    ja_cache = {}
    fallos = {}        # (hoja,row,sub,col) -> motivo
    claves_proc = set(); cambios = collections.defaultdict(dict); ok_res = {}; lotes_fila = {}
    excl10 = set()
    p10 = os.path.join(d, 'lote_correccion_b2_p10.jsonl')
    if os.path.exists(p10):
        for L in B.cargar_lote(p10): excl10.add((L['hoja'], L['row'], L['sub'], L['col']))
    resumen = []; repuestas = {}; avprop = set()
    for p in partes:
        pl = os.path.join(d, 'lote_correccion_b2_%s.jsonl' % p); pr = os.path.join(d, 'resc_corr_%s.jsonl' % p)
        if not os.path.exists(pl): print('SALTADA %s: no existe %s' % (p, os.path.basename(pl))); continue
        lineas = B.cargar_lote(pl); res, malas = cargar_resc(pr)
        esperadas = {(L['hoja'], L['row'], L['sub'], L['col'], L.get('parte', 1)) for L in lineas}
        faltan = esperadas - set(res)
        if faltan or malas:
            print('SALTADA %s: incompleta (esperados %d, escritos validos %d, sin resultado %d, lineas ilegibles %d)' % (p, len(esperadas), len(esperadas & set(res)), len(faltan), len(malas)))
            continue
        porparte = collections.defaultdict(dict)
        for L in lineas: porparte[(L['hoja'], L['row'], L['sub'], L['col'])][L.get('parte', 1)] = L
        filas = B.fusionar_partes(lineas)
        if int(p[1:]) < 10 and excl10: filas = [L for L in filas if (L['hoja'], L['row'], L['sub'], L['col']) not in excl10]   # celdas con relleno: van a p10 (y, desde el cierre, a p11+: la exclusion solo vale para p01..p09)
        ntot = len(filas); nok = 0
        for L in filas:
            k = (L['row'], L['sub'], L['col']); h = L['hoja']; kk = (h,) + k; claves_proc.add(kk); lotes_fila[kk] = L
            mal = []; es_full = []; ests = set(); hs = set(); ok_len = True
            for pt in sorted(porparte[kk]):
                Lp = porparte[kk][pt]; r = res[kk + (pt,)]
                ests.add(r['estado']); hs.add(r['h'])
                if not isinstance(r['es'], list) or not all(isinstance(t, str) for t in r['es']): mal.append('ES_NO_LISTA_DE_STR'); ok_len = False; break
                f = B.expandir_fijos(Lp, r['es'])
                if f is None: mal.append('N_TROZOS es=%d esperados=%d (parte %d)' % (len(r['es']), B.esperados(Lp), pt)); ok_len = False; break
                es_full += f
            if not ok_len: fallos[kk] = 'RESULTADO ' + '; '.join(mal); continue
            if L.get('_incompleta'): fallos[kk] = 'RESULTADO partes incompletas en el lote'; continue
            cplx = L.get('tipo') == 'complejo'
            m_es = B.mal_complejo(L, es_full) if cplx else A.mal_es(es_full, L['ja'])
            m_es = [m for m in m_es if not (m.split()[0] == 'TROZO_VACIO' and A.exento(h, k, 'TROZO_VACIO'))]; mal += m_es
            if not m_es and a.reponer and A.dif_intocables(L['ja'], es_full):
                es_full, rep, _ = RI.reponer(L['ja'], es_full)
                if rep: repuestas[kk] = rep
            if not m_es: mal += A.dif_intocables(L['ja'], es_full)
            if hs != {L['h']}: mal.append('H_LOTE %s != %s' % (sorted(hs), L['h']))
            if ests != {'traducida'}: mal.append('ESTADO %s' % sorted(ests))
            if mal: fallos[kk] = 'RESULTADO ' + '; '.join(mal); continue
            ff, av = A.alineacion(L['ja'], es_full, glos, longs); ff = [x for x in ff if not A.exento(h, k, x[0])]
            if any(c == 'ALIN_PROPORCION' for c, _ in av): avprop.add(kk)
            if ff: fallos[kk] = 'ALINEACION ' + '; '.join('%s %s' % x for x in ff); continue
            es_final = G.recomponer(L['sep'], es_full) if cplx else es_full
            rec = {'row': k[0], 'sub': k[1], 'col': k[2], 'es': es_final, 'estado': 'traducida', 'h': L['h'], 'origen': A.ORIGEN}
            if h not in ja_cache: ja_cache[h] = G.leer_ja(RAIZ, h) or {}
            tr_ja = ja_cache[h].get(k)
            if tr_ja is None: fallos[kk] = 'DAT_FILA_INEXISTENTE no esta en textos/ja'; continue
            try: C.evaluar_cadena(tr_ja[0], tr_ja[1], rec)
            except C.Rechazo as e: fallos[kk] = 'DAT_%s %s' % (e.motivo, e.detalle); continue
            cambios[h][k] = (rec, L.get('linea'), {'accion': L.get('accion'), 'origen_actual': L.get('origen_actual')}); ok_res[kk] = rec; nok += 1
        resumen.append((p, ntot, nok))
    # copias (mismo japones)
    for kk, L in lotes_fila.items():
        src = ok_res.get(kk)
        if src is None: continue
        for c in L.get('copias', ()):
            kc = (c['row'], c['sub'], c['col']); hc = c['hoja']
            rec = {'row': kc[0], 'sub': kc[1], 'col': kc[2], 'es': src['es'] if isinstance(src['es'], str) else list(src['es']), 'estado': 'traducida', 'h': c['h'], 'origen': A.ORIGEN}
            if hc not in ja_cache: ja_cache[hc] = G.leer_ja(RAIZ, hc) or {}
            tr_ja = ja_cache[hc].get(kc)
            if tr_ja is None: fallos[(hc,) + kc] = 'COPIA DAT_FILA_INEXISTENTE'; continue
            try: C.evaluar_cadena(tr_ja[0], tr_ja[1], rec)
            except C.Rechazo as e: fallos[(hc,) + kc] = 'COPIA DAT_%s %s' % (e.motivo, e.detalle); continue
            cambios[hc].setdefault(kc, (rec, c.get('linea'), {'accion': c.get('accion'), 'origen_actual': c.get('origen_actual'), 'copia': True}))
    # aplicar por hoja
    stats = collections.Counter(); pend = {}
    for h in sorted(cambios):
        H = A.Hoja(h); nuevas = {}; nuevos = []
        for k, (rec, hint, meta) in sorted(cambios[h].items(), key=lambda x: (x[0][0], -1 if x[0][1] is None else x[0][1], x[0][2])):
            tag = 'copia' if meta.get('copia') else 'resultado'
            n, motivo = H.localizar(k, hint)
            if n is None:
                if meta.get('accion') == 'anadir': nuevos.append(rec); stats[tag] += 1
                else: fallos[(h,) + k] = 'APLICAR ' + motivo
                continue
            cur = H.json[n]
            if cur == rec: stats['ya_' + tag] += 1; continue
            forzar = meta.get('accion') == 'sustituir' and 'origen_actual' in meta and cur.get('origen') == meta['origen_actual']
            if not A.reemplazable(cur) and not forzar:
                fallos[(h,) + k] = 'APLICAR linea %d no es corpus/dudosa ni coincide con origen_actual (origen=%r, estado=%r): no se pisa' % (n, cur.get('origen'), cur.get('estado')); continue
            if n in nuevas: fallos[(h,) + k] = 'APLICAR linea %d ya sustituida por otra fila' % n; continue
            nuevas[n] = rec; stats[tag] += 1
        if nuevas or nuevos: pend[h] = (H, nuevas, nuevos)
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S'); escritas = []
    for h, (H, nuevas, nuevos) in sorted(pend.items()):
        if a.dry_run: continue
        pt = list(H.partes)
        for n, rec in nuevas.items(): pt[n - 1] = A.dumps(rec) + ('\r' if pt[n - 1].endswith('\r') else '')
        if nuevos:
            fin = pt[-1] == ''
            if fin: pt.pop()
            pt += [A.dumps(r) for r in nuevos]
            if fin or not H.texto: pt.append('')
        bak = os.path.join(RAIZ, 'trabajo', 'lotes', 'bak'); os.makedirs(bak, exist_ok=True)
        with open(os.path.join(bak, '%s.%s.jsonl' % (h, ts)), 'w', encoding='utf-8', newline='') as f: f.write(H.texto)
        tmp = H.ruta + '.tmp.%d' % os.getpid()
        with open(tmp, 'w', encoding='utf-8', newline='') as f: f.write('\n'.join(pt)); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, H.ruta); escritas.append(h)
    if a.reponer: print('intocables repuestos: %d filas con reposicion, %d aplicadas tras validar' % (len(repuestas), sum(1 for kk in repuestas if kk in ok_res)))
    print('AVISOS ALIN_PROPORCION (no bloquea): %d filas' % len(avprop))
    print('partes procesadas (parte, celdas, validas): %s' % resumen)
    print('aplicadas: resultados %d, copias %d | ya aplicadas: resultados %d, copias %d | rechazadas %d | hojas %s %s' % (
        stats['resultado'], stats['copia'], stats['ya_resultado'], stats['ya_copia'], len(fallos), 'a escribir' if a.dry_run else 'escritas', sorted(pend)))
    for k, m in sorted(fallos.items(), key=lambda x: (x[0][0], x[0][1], str(x[0][2]), x[0][3]))[:40]: print('FALLO\t%s\t%s' % ('/'.join(str(x) for x in k), m))
    if not a.dry_run and partes:
        previo = collections.OrderedDict()
        if os.path.exists(f_rech):
            with open(f_rech, encoding='utf-8', newline='') as f:
                for r in csv.DictReader(f, delimiter='\t', quoting=csv.QUOTE_NONE): previo[(r['hoja'], r['row'], r['sub'], r['col'])] = r['motivo']
        sk = lambda k: (k[0], str(k[1]), '' if k[2] is None else str(k[2]), str(k[3]))
        for kk in claves_proc: previo.pop(sk(kk), None)
        for kk, m in fallos.items(): previo[sk(kk)] = m
        os.makedirs(os.path.dirname(f_rech), exist_ok=True)
        with open(f_rech, 'w', encoding='utf-8', newline='\n') as f:
            f.write('hoja\trow\tsub\tcol\tmotivo\n')
            for k, m in previo.items(): f.write('\t'.join(k) + '\t' + m.replace('\t', ' ').replace('\n', ' ') + '\n')
    return 1 if fallos else 0

if __name__ == '__main__': sys.exit(main())
