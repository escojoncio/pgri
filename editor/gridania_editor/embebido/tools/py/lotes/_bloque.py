"""Utilidades del BLOQUE 2 (importado por gen_lote_bloque.py, expandir_resultados.py y aplicar_resultados.py; no se ejecuta solo).
Representacion segura de CUALQUIER fila: la cadena tokenizada se parte por TODOS sus tokens (<If>, <Sheet>, <Run>, <Raw>, <MacroEnd>...) en
trozos de texto `ja` y separadores `sep` (len(sep) == len(ja)-1). El traductor solo escribe trozos; los tokens nunca los toca (orden y numero
intactos por construccion). En filas complejas algunos trozos son `fijos` (siguen a un <Raw>, literal de <Sheet><Run>, o sin CJK; los trozos
traducibles con caracteres de control, p. ej. saltos reales, deben conservarlos: multiconjunto por trozo y orden global): se devuelven identicos. El `es` final de una fila compleja es la cadena tokenizada recomponer(sep, trozos).
Filas largas (> 400 car.): se parten en `partes` de trozos consecutivos (nunca se corta un trozo ni un token); ver fusionar_partes."""
import json, os, sys, unicodedata
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, '..'))
import sestring as S, segmentar as G

LIMITE_PARTE = 400
FULL_CH = [chr(c) for c in range(0xFF01, 0xFF5F) ] + ['…', '‥']   # U+2026 / U+2025 tambien son ERROR (orden 2026-11-08: puntos suspensivos SIEMPRE '...' ASCII, nunca …)   # anchura completa FF01-FF5E (incluye ～ U+FF5E: norma 2026-11-05, ～ -> ~; sin exenciones)

def letras_cjk(t):
    return any(unicodedata.category(c).startswith('L') and G.tiene_cjk(c) for c in t)

def fijos_de(ja, sep, latin=False):
    """indices de trozos que el traductor debe devolver identicos (solo filas complejas). latin=True (bloque 3, ja latino sin CJK): es fijo el trozo SIN LETRAS
    (en lugar del trozo sin CJK)"""
    f = set()
    for i, t in enumerate(ja):
        if (G.es_simbolos(t) if latin else not G.tiene_cjk(t)): f.add(i)
        elif i > 0 and S._bn(sep[i - 1]) == 'Raw': f.add(i)
    # literal de <Sheet|SheetSub|Fixed><Run>..<RunEnd> (construir_dat.literales_run): trozos entre <Run> y su <RunEnd>
    for j in range(len(sep) - 1):
        if S._bn(sep[j]) in ('Sheet', 'SheetSub', 'Fixed') and S._bn(sep[j + 1]) == 'Run' and ja[j + 1] == '':
            depth = 0
            for k in range(j + 1, len(sep)):
                b = S._bn(sep[k])
                if b == 'Run': depth += 1
                elif b == 'RunEnd':
                    depth -= 1
                    if depth == 0:
                        f.update(range(j + 2, k + 1)); break
    return sorted(f)

def descomponer(text, raw=None, latin=False):
    """(latin=True: ver fijos_de) volcado de textos/ja -> {tok, tipo:'simple'|'complejo', ja:[trozos], sep:[tokens], fijos:[indices]} o None si no se reconstruye exactamente"""
    tok = G.tokenizar_volcado(text, raw)
    if G.clasificar(tok, raw=bool(raw)) == 'simple':
        ja, sep = G.trocear(tok)
        return {'tok': tok, 'tipo': 'simple', 'ja': ja, 'sep': sep, 'fijos': []}
    tr = []; sep = []; prev = 0
    for t, p in S._atoms(tok):
        tr.append(tok[prev:p]); sep.append(t); prev = p + len(t)
    tr.append(tok[prev:])
    ja = [x.replace('<<', '<') for x in tr]
    try:
        if G.recomponer(sep, ja) != tok: return None
    except ValueError: return None
    return {'tok': tok, 'tipo': 'complejo', 'ja': ja, 'sep': sep, 'fijos': fijos_de(ja, sep, latin)}

def longitud(d):
    """longitud de la fila a efectos del limite de 400 (como K.txt: texto plano si simple, cadena tokenizada si compleja)"""
    return sum(len(t) for t in d['ja']) if d['tipo'] == 'simple' else len(d['tok'])

def partes_de(d, limite=LIMITE_PARTE):
    """-> [(ini, fin)] rangos de trozos (fin exclusivo). Una sola parte si longitud <= limite. Un trozo nunca se parte."""
    ja, sep = d['ja'], d['sep']
    if longitud(d) <= limite: return [(0, len(ja))]
    out = []; ini = 0; acc = 0
    for i, t in enumerate(ja):
        n = len(t) + (len(sep[i - 1]) if d['tipo'] == 'complejo' and i > 0 else 0)
        if i > ini and acc + n > limite: out.append((ini, i)); ini = i; acc = 0
        acc += n
    out.append((ini, len(ja)))
    if d['tipo'] == 'complejo':   # cada parte debe tener algun trozo traducible (si no, se une a la vecina)
        fj = set(d['fijos']); tiene = lambda r: any(i not in fj for i in range(r[0], r[1]))
        i = 0
        while len(out) > 1 and i < len(out):
            if tiene(out[i]): i += 1; continue
            if i > 0: out[i - 1] = (out[i - 1][0], out[i][1]); del out[i]
            else: out[1] = (out[0][0], out[1][1]); del out[0]
    return out

def fusionar_partes(filas):
    """lineas de lote -> filas completas: las lineas con `parte`/`partes` de una misma (hoja,row,sub,col) se fusionan (ja concatenado; sep unido con
    `sep_fin`; fijos desplazados; copias y demas campos de la parte 1). Las demas pasan tal cual. Mantiene el orden de la primera aparicion.
    Si faltan partes la fila se devuelve con '_incompleta': True."""
    grupos = {}; orden = []
    for r in filas:
        k = (r.get('hoja'), r['row'], r.get('sub'), r['col'])
        if k not in grupos: grupos[k] = []; orden.append(k)
        grupos[k].append(r)
    out = []
    for k in orden:
        g = grupos[k]
        if len(g) == 1 and 'parte' not in g[0]: out.append(g[0]); continue
        g = sorted(g, key=lambda r: r.get('parte', 1))
        n = g[0].get('partes', len(g)); m = dict(g[0])
        m['ja'] = []; m['fijos'] = []; sep = []; hay_sep = any('sep' in r for r in g); m_trad = []
        for i, r in enumerate(g):
            off = len(m['ja']); m['ja'] += r['ja']; m['fijos'] += [off + x for x in r.get('fijos', ())]; m_trad += r.get('ja_trad', ())
            if hay_sep:
                sep += r.get('sep', ['<NewLine>'] * (len(r['ja']) - 1))
                if i < len(g) - 1: sep.append(r.get('sep_fin') or '<NewLine>')
        if hay_sep: m['sep'] = sep
        if m_trad: m['ja_trad'] = m_trad
        if m.get('acortar'):   # bloque 5/6: max_len y es_actual de cada parte se concatenan (alineados con los traducibles)
            for x in ('max_len', 'es_actual'): m[x] = [y for r in g for y in r.get(x, ())]
        if m['tipo'] == 'complejo': m['tok'] = G.recomponer(sep, m['ja'])
        for x in ('parte', 'partes', 'sep_fin', 'ctx_antes', 'ctx_despues'): m.pop(x, None)
        if [r.get('parte', 1) for r in g] != list(range(1, n + 1)): m['_incompleta'] = True
        out.append(m)
    return out

def indices_traducibles(L):
    """indices de trozos que el traductor escribe (todos menos los fijos)"""
    f = set(L.get('fijos', ())); return [i for i in range(len(L['ja'])) if i not in f]

def mal_complejo(L, es):
    """motivos por los que `es` (lista de trozos) no vale para una fila compleja del lote (vacia = ok): fijos identicos, nº de trozos, vacios solo en trozos de
    una letra CJK, tipos"""
    if not isinstance(es, list) or not es or not all(isinstance(t, str) for t in es): return ['ES_NO_LISTA_DE_STR']
    ja = L['ja']
    if len(es) != len(ja): return ['N_TROZOS es=%d ja=%d' % (len(es), len(ja))]
    mal = []
    for i in L.get('fijos', ()):
        if es[i] != ja[i]: mal.append('FIJO_ALTERADO trozo %d: %r -> %r' % (i, ja[i], es[i]))
    fj = set(L.get('fijos', ()))
    for i, (j, t) in enumerate(zip(ja, es)):
        if i in fj: continue
        if not t.strip() and not G.vacio_permitido(j): mal.append('TROZO_VACIO %d' % i); break
    if not any(t.strip() for i, t in enumerate(es) if i not in fj): mal.append('SIN_TEXTO_TRADUCIDO')
    for i, t in enumerate(es):
        if i in fj: continue
        if '\u3000' in t: mal.append('U+3000'); break
        if any(c in t for c in FULL_CH): mal.append('ANCHURA_COMPLETA'); break
        if G.tiene_cjk(t): mal.append('CJK_EN_ES'); break
    return mal

# ---------------------------------------------------------------- formato del lote en disco
# Filas simples: una linea en lote_fr_<X>.jsonl con `ja` = trozos (lo que escribe el traductor).
# Filas complejas: en lote_fr_<X>.jsonl `ja` = SOLO los trozos traducibles (en orden) + `tok` (cadena tokenizada del trozo, contexto); la estructura completa
# (`ja` entero, `sep`, `fijos`) va en lote_fr_<X>_est.jsonl (no la lee el traductor). El compacto del traductor lleva solo los traducibles; expandir_resultados.py
# reinserta los fijos.
def leer_jsonl(ruta):
    with open(ruta, encoding='utf-8') as f: return [json.loads(l) for l in f if l.strip()]

def ruta_copias(ruta):
    """fichero lateral de copias de un lote: lote_fr_X.jsonl -> lote_fr_X_copias.jsonl"""
    return ruta[:-len('.jsonl')] + '_copias.jsonl'

def aligerar_copias(lineas):
    """-> (lineas sin `copias` pero con `ncopias`, [lateral {hoja,row,sub,col,copias}]). No modifica las originales (lotes aligerados, b7s)."""
    lig = []; lat = []
    for L in lineas:
        if L.get('copias'):
            L2 = {}
            for k, v in L.items():
                if k == 'copias': L2['ncopias'] = len(v)
                else: L2[k] = v
            lat.append({'hoja': L['hoja'], 'row': L['row'], 'sub': L.get('sub'), 'col': L['col'], 'copias': L['copias']}); lig.append(L2)
        else: lig.append(L)
    return lig, lat

def rellenar_copias(lineas, ruta):
    """lotes aligerados: repone `copias` desde el lateral (`ruta` = el lote principal) en las lineas que traen `ncopias` y no `copias`. Lotes antiguos (copias inline): no hace nada."""
    if not any('ncopias' in L and 'copias' not in L for L in lineas): return lineas
    pc = ruta_copias(ruta); lat = {}
    if os.path.exists(pc):
        for e in leer_jsonl(pc): lat[(e['hoja'], e['row'], e.get('sub'), e['col'])] = e['copias']
    for L in lineas:
        if 'ncopias' in L and 'copias' not in L:
            c = lat.get((L.get('hoja'), L['row'], L.get('sub'), L['col']))
            if c is None: raise ValueError('%s: faltan las copias de %s en %s' % (ruta, (L.get('hoja'), L['row'], L.get('sub'), L['col']), pc))
            L['copias'] = c
    return lineas

def cargar_lote(ruta):
    """lineas del lote (sin fusionar partes). Las complejas se completan con su estructura: L['ja'] = trozos completos, L['ja_trad'] = lo que ve el traductor,
    L['sep'], L['fijos']. Las simples quedan igual (sin 'ja_trad')."""
    lineas = rellenar_copias(leer_jsonl(ruta), ruta) if os.path.exists(ruta) else []
    est_ruta = ruta[:-len('.jsonl')] + '_est.jsonl'
    est = {}
    if os.path.exists(est_ruta):
        for e in leer_jsonl(est_ruta): est[(e['hoja'], e['row'], e.get('sub'), e['col'], e.get('parte', 1))] = e
    for L in lineas:
        if L.get('tipo') == 'complejo' and 'ja_trad' not in L:
            e = est[(L['hoja'], L['row'], L.get('sub'), L['col'], L.get('parte', 1))]
            L['ja_trad'] = L['ja']; L['ja'] = e['ja']; L['sep'] = e['sep']; L['fijos'] = e['fijos']
            if 'sep_fin' in e: L['sep_fin'] = e['sep_fin']
    return lineas

def esperados(L):
    """nº de trozos que escribe el traductor para una linea (parte) del lote"""
    return len(L['ja']) - len(L.get('fijos', ())) if L.get('tipo') == 'complejo' else len(L['ja'])

def expandir_fijos(L, es_trad):
    """trozos escritos por el traductor (solo traducibles en filas complejas) -> lista completa alineada con L['ja'] (fijos reinsertados). None si el nº no cuadra"""
    if L.get('tipo') != 'complejo': return list(es_trad)
    if len(es_trad) != esperados(L): return None
    fj = set(L.get('fijos', ())); it = iter(es_trad)
    return [L['ja'][i] if i in fj else next(it) for i in range(len(L['ja']))]
