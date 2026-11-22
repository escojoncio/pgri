#!/usr/bin/env -S python3 -I
"""Auditoria GLOBAL MECANICA de traducciones/*.jsonl y de su efecto en el .dat.
Uso: python3 -I tools/py/lotes/auditar_global.py --game DIR_0a0000 [--hojas H1,H2] [--corregir] [--dry-run]
Comprueba: alcance (hojas fuera de grupos_interfaz.txt, origen/estado), integridad (h, clave, duplicados, nº de trozos), texto perdido/desplazado (vacios, duplicados contiguos,
relleno, proporcion es/ja, digitos, URLs, intocables), comandos de chat, glifos/anchura/CJK, ingles residual y recuento de filas que entran en el .dat (construir_dat.construir por hoja).
--corregir: SOLO lo determinista: elimina lineas duplicadas EXACTAS (misma clave y mismo contenido), dejando la ultima; backup por hoja en trabajo/lotes/bak/.
Salidas: trabajo/informes/global_pendientes.tsv (hoja,row,sub,col,categoria,es,detalle) y trabajo/informes/global_resumen.md. Solo biblioteca estandar + repo."""
import argparse, collections, datetime, glob, json, os, re, sys
AQUI = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, AQUI); sys.path.insert(0, os.path.join(AQUI, '..'))
import aplicar_resultados as A
import segmentar as G
import construir_dat as C
RAIZ = A.RAIZ
INGLES = set('the of and you your with for are this that will from have not can when which into than their there been would should'.split())
INGLES_FRASES = ('The Fold', 'Crystalline Conflict')
PAL_RE = re.compile(r'[^\W\d_]+', re.U)
CMD_RE = C.CMD_RE; URL_RE = C.URL_RE

def ambito():
    with open(os.path.join(AQUI, '..', 'grupos_interfaz.txt'), encoding='utf-8') as f:
        return {l.strip() for l in f if l.strip() and not l.startswith('#')}

def revisar_fila(e, ja_trozos, seps, tok, text):
    """-> [(categoria, detalle)] para una linea con es lista (ja_trozos) o cadena (ja_trozos None)"""
    out = []; es = e.get('es')
    if isinstance(es, str): ja_trozos = None   # cadena tokenizada (filas complejas o simples traducidas como cadena)
    if ja_trozos is None:
        s = es if isinstance(es, str) else ' '.join(x for x in es if isinstance(x, str)) if isinstance(es, list) else ''
        if not isinstance(es, (str, list)): return [('TIPO_ES', repr(type(es)))]
        trozos_es = es if isinstance(es, list) else [es]; ja_t = None
    else:
        if not isinstance(es, list) or not all(isinstance(x, str) for x in es): return [('TIPO_ES', 'es no es lista de str')]
        trozos_es = es; ja_t = ja_trozos
        if len(es) != len(ja_t): return [('N_TROZOS', 'es=%d ja=%d' % (len(es), len(ja_t)))]
    if isinstance(es, str) or ja_t is None:
        # complejas: es = cadena tokenizada; solo glifos, CJK, ingles, digitos globales
        ja_all = [tok]
    else: ja_all = ja_t
    # ---- glifos
    trozos_es = [C._sin_tokens(t) if '<If>' in t else t for t in trozos_es]   # bloque macro crudo <If>..<MacroEnd#N>: literales de rama identicos al ja, exentos
    for t in trozos_es:
        if '　' in t or any(c in t for c in A.FULL_CH): out.append(('ANCHURA', 'U+3000/anchura completa')); break
    for t in trozos_es:
        if G.tiene_cjk(t): out.append(('CJK', 'CJK en es: ' + ''.join(c for c in t if G.tiene_cjk(c))[:20])); break
    # ---- digitos / URLs / comandos (sobre el conjunto)
    ja_j = ' '.join(ja_all); es_j = ' '.join(trozos_es)
    if ja_t is not None:
        dj, de = A.digitos(ja_t), A.digitos(es)
        if dj != de:
            f = sorted((dj - de).elements()); x = sorted((de - dj).elements()); out.append(('DIGITOS', 'faltan %s sobran %s' % (f, x)))
        for m in A.dif_intocables(ja_t, es): out.append(('INTOCABLES', m))
    for u in URL_RE.findall(ja_j):
        if u not in es_j: out.append(('URL', 'falta o alterada: ' + u)); break
    cj = CMD_RE.findall(ja_j); ce = CMD_RE.findall(es_j)
    if cj or ce:
        d1 = collections.Counter(cj) - collections.Counter(ce); d2 = collections.Counter(ce) - collections.Counter(cj)
        if d1 or d2: out.append(('COMANDO', 'ja %s es %s (faltan %s sobran %s)' % (cj, ce, sorted(d1.elements()), sorted(d2.elements()))))
        elif ja_t is not None:
            # comando conservado: sus argumentos deben haberse traducido (no quedar identicos al ja con letras)
            for i, (j, t) in enumerate(zip(ja_t, es)):
                if CMD_RE.search(j) and j.strip() == t.strip() and any(c.isalpha() for c in j) and G.tiene_cjk(j): out.append(('COMANDO', 'trozo %d sin traducir' % i)); break
    # ---- trozos
    if ja_t is not None:
        for i, (j, t) in enumerate(zip(ja_t, es)):
            tj_alpha = any(c.isalpha() for c in j) and not G.es_simbolos(j)
            if not t.strip():
                if tj_alpha and not G.vacio_permitido(j): out.append(('TROZO_VACIO', 'trozo %d (ja no vacio)' % i))
                continue
            if not j.strip() and not G.es_simbolos(t): out.append(('TROZO_LLENO_JA_VACIO', 'trozo %d: %r' % (i, t[:40])))
            if tj_alpha and re.fullmatch(r'[.º\s]+', t): out.append(('RELLENO', 'trozo %d: %r' % (i, t)))
            elif tj_alpha and not any(c.isalpha() for c in t) and not any(c.isdigit() for c in t): out.append(('RELLENO', 'trozo %d: %r' % (i, t)))
            if len(j.strip()) >= 10 and t.strip():
                r = len(t.strip()) / float(len(j.strip()))
                if r < 0.4 or r > 3: out.append(('PROPORCION_BAJA' if r < 0.4 else 'PROPORCION_ALTA', 'trozo %d ratio %.2f (ja %d, es %d)' % (i, r, len(j.strip()), len(t.strip()))))
        for i in range(len(es) - 1):
            a, b = es[i].strip(), es[i + 1].strip()
            if a and a == b and len(a) >= 4 and ja_t[i].strip() != ja_t[i + 1].strip(): out.append(('DUPLICADO_TROZO', 'trozos %d y %d idénticos: %r' % (i, i + 1, a[:40])))
            for k in (i, i + 1):
                o = i + 1 if k == i else i
                s = es[k].strip()
                if len(s) >= 8 and es[o].strip() != s and s in es[o] and ja_t[k].strip() != ja_t[o].strip() and (s, k, o) not in []:
                    out.append(('DESPLAZADO', 'trozo %d contenido en el vecino %d: %r' % (k, o, s[:40]))); break
    # ---- ingles residual
    ja_cf = ja_j.casefold()
    pal = {w for t in trozos_es for w in (x.lower() for x in PAL_RE.findall(t)) if w in INGLES and w not in ja_cf}
    if len(pal) >= 2: out.append(('INGLES', 'palabras: ' + ', '.join(sorted(pal))))
    for fr in INGLES_FRASES:
        if any(fr in t for t in trozos_es) and fr not in ja_j: out.append(('INGLES', fr))
    return out

def listar_hojas(raiz=None):
    """Nombres de hoja de traducciones/ incluidas las subcarpetas (cut_scene/NNN/X, quest/NNN/X...), con '/' como separador, ordenados."""
    base = os.path.join(raiz or RAIZ, 'traducciones'); out = []
    for d, _, fs in os.walk(base):
        for fn in fs:
            if fn.endswith('.jsonl'): out.append(os.path.relpath(os.path.join(d, fn), base)[:-6].replace(os.sep, '/'))
    return sorted(out)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', required=True); ap.add_argument('--hojas'); ap.add_argument('--corregir', action='store_true'); ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    from sqpack_raw import Pack
    pk = Pack(a.game); cache = {}
    def exh(s):
        if s not in cache: cache[s] = pk.exh(s)
        return cache[s]
    interfaz = ambito(); solo = set(a.hojas.split(',')) if a.hojas else None
    hojas_all = listar_hojas()
    pend = []; cat = collections.Counter(); catfilas = collections.defaultdict(set)
    fuera = []; por_origen = collections.Counter(); entran_origen = collections.Counter(); entran_estado = collections.Counter()
    tabla = []; dedup_quitadas = collections.Counter(); ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S'); filas_tot = 0
    rech_total = collections.Counter(); hojas_tocadas = []; entra = set()
    for hoja in hojas_all:
        ruta = os.path.join(RAIZ, 'traducciones', *hoja.split('/')) + '.jsonl'
        if solo and hoja not in solo: continue
        H = A.Hoja(hoja)
        ja = G.leer_ja(RAIZ, hoja)
        lineas = [(n, j) for n, j in H.json.items()]
        filas_tot += len(lineas)
        if hoja not in interfaz: fuera.append((hoja, len(lineas)))
        # duplicados
        cnt = collections.Counter(A.clave(j) for _, j in lineas)
        borrar = set()
        for k, c in cnt.items():
            if c > 1:
                ns = H.idx[k]; contenidos = {A.dumps(H.json[n], False) for n in ns}
                if len(contenidos) == 1: borrar.update(ns[:-1])
                else:
                    pend.append((hoja, k[0], k[1], k[2], 'DUPLICADO_CLAVE', ' || '.join(str(H.json[ns[-1]].get('es'))), '%d lineas con distinto contenido' % c))
        if borrar and a.corregir and not a.dry_run:
            bak = os.path.join(RAIZ, 'trabajo', 'lotes', 'bak'); os.makedirs(bak, exist_ok=True)
            with open(os.path.join(bak, '%s.%s.jsonl' % (hoja, ts)), 'w', encoding='utf-8', newline='') as f: f.write(H.texto)
            partes = [p for n, p in enumerate(H.partes, 1) if n not in borrar]
            tmp = H.ruta + '.tmp.%d' % os.getpid()
            with open(tmp, 'w', encoding='utf-8', newline='') as f: f.write('\n'.join(partes)); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, H.ruta); dedup_quitadas[hoja] = len(borrar); hojas_tocadas.append(hoja)
            H = A.Hoja(hoja); lineas = list(H.json.items())
        elif borrar: dedup_quitadas[hoja] = -len(borrar)   # (dry-run / sin --corregir: cuantas se podrian quitar)
        info = {}   # clave -> (ja_trozos|None, seps, tok, text)
        for n, e in lineas:
            k = A.clave(e); por_origen[(e.get('origen'), e.get('estado'))] += 1
            if ja is None: pend.append((hoja, k[0], k[1], k[2], 'HOJA_SIN_JA', '', '')); continue
            if k not in ja: pend.append((hoja, k[0], k[1], k[2], 'CLAVE_INEXISTENTE', ' || '.join(e['es']) if isinstance(e.get('es'), list) else str(e.get('es')), 'no esta en textos/ja')); continue
            text, raw = ja[k]
            if e.get('h') != G.hash_ja(text): pend.append((hoja, k[0], k[1], k[2], 'HASH_OBSOLETO', ' || '.join(e['es']) if isinstance(e.get('es'), list) else str(e.get('es')), 'h=%s actual=%s origen=%s' % (e.get('h'), G.hash_ja(text), e.get('origen')))); continue
            tok = G.tokenizar_volcado(text, raw)
            simple = G.clasificar(tok, raw=bool(raw)) == 'simple'
            if simple: tr, seps = G.trocear(tok)
            else: tr, seps = None, None
            if simple and not isinstance(e.get('es'), list): pass
            for c, d in revisar_fila(e, tr, seps, tok, text):
                es_txt = ' || '.join(e['es']) if isinstance(e.get('es'), list) else str(e.get('es'))
                pend.append((hoja, k[0], k[1], k[2], c, es_txt, '[origen=%s estado=%s] %s' % (e.get('origen'), e.get('estado'), d)))
        # efecto en el .dat
        avisos = []
        ok, rech, nleidas = C.procesar_hoja(RAIZ, hoja, ruta, exh, set(), avisos, False)
        ok2, rech2, _ = C.procesar_hoja(RAIZ, hoja, ruta, exh, set(), None, True)
        rm = collections.Counter(r['motivo'] for r in rech); rech_total.update(rm)
        rechk = {(r['row'], r['sub'], r['col']) for r in rech}
        ent_o = collections.Counter()
        for n, e in H.json.items():
            k = A.clave(e); kk = (k[0], '' if k[1] is None else k[1], k[2])
            if kk not in rechk and (k[0], k[1], k[2]) not in rechk:
                entra.add((hoja, k[0], k[1], k[2])); ent_o[e.get('origen')] += 1; entran_origen[e.get('origen')] += 1; entran_estado[e.get('estado')] += 1
        tabla.append((hoja, len(H.json), len(ok), len(ok2), dict(rm), dict(ent_o)))
    cat_dat = collections.Counter(); fil_dat = collections.defaultdict(set)
    for p in pend:
        cat[p[4]] += 1; catfilas[p[4]].add(p[:4])
        if p[:4] in entra: cat_dat[p[4]] += 1; fil_dat[p[4]].add(p[:4])
    ts_out = os.path.join(RAIZ, 'trabajo', 'informes'); os.makedirs(ts_out, exist_ok=True)
    if not a.dry_run:
        with open(os.path.join(ts_out, 'global_pendientes.tsv'), 'w', encoding='utf-8', newline='\n') as f:
            f.write('hoja\trow\tsub\tcol\tcategoria\tes\tdetalle\n')
            for p in pend: f.write('\t'.join('' if x is None else str(x).replace('\t', ' ').replace('\n', ' ').replace('\r', ' ') for x in p) + '\n')
        L = ['# Auditoría global mecánica (%s)' % datetime.date.today().isoformat(), '',
             'Script: `tools/py/lotes/auditar_global.py`. Líneas en traducciones/: %d en %d hojas (59 en alcance de interfaz).' % (filas_tot, len(tabla)), '',
             '## Alcance', 'Hojas con traducciones fuera de grupos_interfaz.txt: %d %s' % (len(fuera), fuera), '',
             'Líneas por (origen, estado): ' + ', '.join('%s/%s=%d' % (o, s, n) for (o, s), n in sorted(por_origen.items(), key=lambda x: str(x[0]))), '',
             'Entran en el .dat por origen: ' + ', '.join('%s=%d' % (o, n) for o, n in sorted(entran_origen.items(), key=lambda x: str(x[0]))),
             'Entran por estado: ' + ', '.join('%s=%d' % kv for kv in entran_estado.items()),
             'Rechazos construir_dat (sin corpus): ' + ', '.join('%s=%d' % kv for kv in sorted(rech_total.items())), '',
             '## Pendientes por categoría (líneas / filas)']
        for c, n in sorted(cat.items(), key=lambda x: -x[1]): L.append('- %s: %d (%d filas) | de ellas en el .dat: %d (%d filas)' % (c, n, len(catfilas[c]), cat_dat[c], len(fil_dat[c])))
        L += ['', '## Autocorrección', 'Líneas duplicadas exactas eliminadas: ' + (', '.join('%s=%d' % kv for kv in dedup_quitadas.items()) or 'ninguna'), '',
              '## Por hoja (hoja, líneas, entran, entrarían con corpus, rechazos, entran por origen)']
        for t in tabla: L.append('- %s | %d | %d | %d | %s | %s' % t)
        with open(os.path.join(ts_out, 'global_resumen.md'), 'w', encoding='utf-8', newline='\n') as f: f.write('\n'.join(L) + '\n')
    print('lineas %d | hojas %d | fuera de ambito %d | pendientes %d: %s' % (filas_tot, len(tabla), len(fuera), len(pend), dict(cat)))
    print('pendientes EN el .dat por categoria: %s' % dict(cat_dat))
    print('entran por origen: %s | por estado: %s | rechazos: %s' % (dict(entran_origen), dict(entran_estado), dict(rech_total)))
    print('duplicadas exactas %s: %s' % ('eliminadas' if a.corregir else 'detectadas', dict(dedup_quitadas)))
    return 0
if __name__ == '__main__': sys.exit(main())
