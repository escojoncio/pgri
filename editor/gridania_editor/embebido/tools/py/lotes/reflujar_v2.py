"""REFLUJO v2 (cortes naturales). Reutiliza el motor de reflujar_lineas.py (tokens, macros, trozos, invariantes, revalidacion) y SUSTITUYE solo el coste/optimizador:
- sin 'cascada' (minimo cambio): se busca siempre el optimo global con los MISMOS saltos exigidos por el japones (nº de trozos y huecos intactos);
- fin de frase (. ? ! …) es corte preferente (aunque la linea sea corta); dos puntos/;: casi igual; si la linea ya tiene >= 25 car. el corte en fin de frase gana premio;
- resto: lineas rellenas hacia ~53 car. (maximo 58, hasta 61 si acaba en puntuacion), corte tras coma o antes de conjuncion/relativo/preposicion larga;
  nunca tras articulo/preposicion/clitico; penaliza lineas de 1-2 palabras cortas y el patron «linea corta (<40 %) que no cierra frase seguida de otra mas larga»;
- ventanas de 3 lineas: el corte de ventana en mitad de frase cuesta mas; ultima ventana < 60 % = huerfana (penalizada).
- VENTANA FINAL (prioridad del propietario): si el nº total de lineas g cumple g % 3 == 1 la ultima ventana es solo la ultima linea: se penaliza fuerte (vf_penal) que tenga < 4 palabras / < 15 car. (<= 2 palabras = penalizacion maxima), moviendo palabras entre lineas y trozos vecinos; --paginar reparte las celdas no_cabe por ventanas; --sin-ventana-final = comportamiento anterior.
  Medicion y lista de no arreglables: reflujar_ventana_final.py.
Uso: python3 -I reflujar_v2.py [--familias quest,DefaultTalk,cut_scene,NpcYell,Balloon,Lobby] [--tsv F] [--ejemplos N] [--seed S] [--dry-run (siempre)]
SIN --escribir solo hace dry-run. Escribir en traducciones/ requiere orden del director (no implementado aqui a proposito)."""
import sys, os, re, json, argparse, random, collections
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import reflujar_lineas as R

INF = float('inf')
T_OBJ = 51.0; CORTA = 0.40; SOLA_MIN = 25
PREP_LARGA = frozenset('para desde hasta sobre entre durante contra según mientras aunque porque'.split())
R.MARGEN = 1.0
R.TOL = 56   # tope duro (dato del propietario: pasarse abre ventana nueva)
HARD = 56

def termina_frase(w): return R.FIN_FRASE.search(R.plano(w)) is not None
def termina_clausula(w): return R.FIN_CLAUS.search(R.plano(w)) is not None

def bc2(bl, p):
    """coste de cortar tras la palabra p (mejora el de R: preposicion larga y relativos)"""
    c = bl.bc[p]
    if c >= 10.0:   # corte a media frase: ya penalizado por R; si lo que sigue es preposicion larga y lo anterior no es articulo/prep, es aceptable
        nxt = R.base_palabra(R.plano(bl.ws[p + 1])); b = R.base_palabra(R.plano(bl.ws[p]))
        if nxt in PREP_LARGA and b not in R.ART and b not in R.PREP and b not in R.CLIT and b not in R.AUXI and b not in R.CONJ: c = 4.0 + (c - 10.0)
    return c

def pal_n(bl, a, b): return b - a + 1

# ---- «ventana final»: requisito del propietario (visto en el juego): ninguna ventana puede quedar con 1-2 palabras. Se aplica al ultimo bloque en modo exacto
# (nº de lineas fijo por el japones): si el nº total de lineas g cumple g % VENT == 1 (g > VENT), la ultima ventana es SOLO la ultima linea y debe tener >= VF_PAL palabras
# y >= VF_CAR caracteres; si g % VENT == 2, la ultima linea debe tener >= 2 palabras. Mover palabras entre lineas/trozos vecinos es lo unico que hace el DP.
VF = {'on': True, 'off': 0, 'bi': 0, 'nb': 1, 'exacto': False}
VF_PAL = 4; VF_CAR = 15; VF_PEN = 120.0

def vf_penal(bl, a, p, nth, L):
    """penalizacion de la ultima linea (palabras a..p, ancho L, linea nº nth del bloque) por ventana final casi vacia"""
    if not (VF['on'] and VF['exacto']): return 0.0
    if bl.__dict__.get('vf_bi') is None: bl.vf_bi = VF['bi']; bl.vf_off = VF['off']; bl.vf_last = VF['bi'] == VF['nb'] - 1
    if not bl.vf_last: return 0.0
    g = bl.vf_off + nth; nw = p - a + 1
    if g <= R.VENT_MAX: return 0.0
    r = g % R.VENT
    if r == 1:
        pen = max(0, VF_PAL - nw) * 25.0 + max(0, VF_CAR - L) * 2.0
        return pen + (VF_PEN if nw <= 2 else 0.0)
    if r == 2:
        return (VF_PEN if nw <= 1 else 0.0) + (10.0 if nw <= 2 and L < 10 else 0.0)
    return 0.0

def linea_coste(bl, a, p, W, prev, nth, last):
    """coste de la linea con palabras a..p. prev = (ancho, fin_frase) de la linea anterior o None. nth = nº de linea (1..). last = es la ultima del bloque"""
    L = bl.ancho(a, p)
    if L > W and not (L <= R.TOL and R.FIN_PUNT.search(R.plano(bl.ws[p]))): return INF
    c = R.LINEA
    if L > W: c += 3.0
    fin = termina_frase(bl.ws[p]) or termina_clausula(bl.ws[p])
    if not last:
        fill = 12.0 * (max(0.0, W - L) / float(W)) ** 2   # llenar la linea (avaricia suave): cortar solo cuando esta llena
        bueno = termina_frase(bl.ws[p]) and L >= 0.6 * W   # punto y seguido en margen razonable (linea >= 60 % llena)
        if bueno: fill *= 0.5
        cc = bc2(bl, p)
        if termina_frase(bl.ws[p]) and not bueno: cc = min(cc, 2.0)   # punto en linea medio vacia: corte aceptable, sin premio
        c += fill + cc - (3.0 if bueno else 0.0)
        if p in bl.act_set and re.search(r'(?:…|\.\.\.)["»”)]*$', R.plano(bl.ws[p])): c -= 4.0   # pausa dramatica del original: se respeta
        if pal_n(bl, a, p) <= 2 and L < 15 and not fin: c += 12.0
        if nth % R.VENT == 0 and bl.bc[p] > 2.0: c += 4.0   # corte de ventana en mitad de frase
    else:
        if L < 10 and bl.n > 1 and a > 0: c += 18.0
        elif (L < 15 or pal_n(bl, a, p) <= 2) and a > 0: c += 8.0
        c += vf_penal(bl, a, p, nth, L)
    if prev is not None:
        pw, pfin = prev
        if pw < CORTA * W and not pfin and L > pw: c += 10.0 + (4.0 if pw < 12 else 0.0)
    return c

def coste_total(bl, cortes, W):
    ini = 0; tot = 0.0; prev = None; ws_ = []; cortes = sorted(cortes)
    for k, p in enumerate(cortes + [bl.n - 1]):
        last = p == bl.n - 1
        c = linea_coste(bl, ini, p, W, prev, k + 1, last)
        if c == INF: return INF
        tot += c; L = bl.ancho(ini, p); ws_.append(L)
        prev = (L, termina_frase(bl.ws[p]) or termina_clausula(bl.ws[p])); ini = p + 1
    if len(ws_) > R.VENT_MAX:
        ult = sum(ws_[-(len(ws_) % R.VENT or R.VENT):])
        if ult < R.MIN_ULT * W: tot += 20.0
    return tot

def optimizar2(bl, r_min, r_max, W, req=None):
    n = bl.n
    if n == 1:
        c = linea_coste(bl, 0, 0, W, None, 1, True)
        return (c, []) if (r_min == 0 and c < INF) else (INF, None)
    if r_max == 0:
        c = coste_total(bl, [], W)
        return (c, []) if (r_min == 0 and c < INF) else (INF, None)
    # estados: f[j][(q, p)] = coste con j cortes, penultimo corte q, ultimo p (q=-1 si j=1)
    f = [dict() for _ in range(r_max + 1)]; par = [dict() for _ in range(r_max + 1)]
    for p in range(n - 1):
        if not bl.cand[p]: continue
        if req is not None and req[0] is not None and bl.js[p][1] != req[0]: continue
        c = linea_coste(bl, 0, p, W, None, 1, False)
        if c < INF: f[1][(-1, p)] = c; par[1][(-1, p)] = None
    for j in range(2, r_max + 1):
        for p in range(j - 1, n - 1):
            if not bl.cand[p]: continue
            if req is not None and req[j - 1] is not None and bl.js[p][1] != req[j - 1]: continue
            for (qq, q), cq in f[j - 1].items():
                if q >= p: continue
                L0 = bl.ancho(qq + 1, q); prev = (L0, termina_frase(bl.ws[q]) or termina_clausula(bl.ws[q]))
                c = linea_coste(bl, q + 1, p, W, prev, j, False)
                if c == INF: continue
                c += cq; key = (q, p)
                if key not in f[j] or c < f[j][key] - 1e-9 or (abs(c - f[j][key]) <= 1e-9 and (qq, q) < par[j][key]):
                    f[j][key] = c; par[j][key] = (qq, q)
    mejor = (INF, None)
    if r_min == 0:
        c = coste_total(bl, [], W)
        if c < mejor[0]: mejor = (c, [])
    for j in range(max(r_min, 1), r_max + 1):
        for (q, p), cp in f[j].items():
            L0 = bl.ancho(q + 1, p) if j >= 1 else 0
            prev = (L0, termina_frase(bl.ws[p]) or termina_clausula(bl.ws[p]))
            cl = linea_coste(bl, p + 1, n - 1, W, prev, j + 1, True)
            if cl == INF: continue
            # reconstruir cortes
            cuts = []; st = (q, p); jj = j
            while jj >= 1:
                cuts.append(st[1]); st = par[jj][st]; jj -= 1
            cuts.sort()
            c = coste_total(bl, cuts, W)   # incluye terminos de ventana; coherente con el DP
            if c < mejor[0] - 1e-9 or (abs(c - mejor[0]) <= 1e-9 and mejor[1] is not None and cuts < mejor[1]): mejor = (c, cuts)
    if mejor[1] is None: return (INF, None)
    return mejor

def optimizar_vf(bl, r_min, r_max, W, req=None):
    """optimizar2 + seguimiento de la linea global (para la ventana final): VF['off'] = lineas de los bloques anteriores"""
    res = optimizar2(bl, r_min, r_max, W, req)
    VF['bi'] += 1
    if res[1] is not None: VF['off'] += len(res[1]) + 1
    return res

R.optimizar = optimizar_vf
R.coste_cortes = coste_total
R.cascada = lambda bl, r, req, W: None

# ---------------------------------------------------------------- metricas
def lineas_pantalla(s):
    return [R.pantalla(x).strip() for x in R.partir_lineas(s[R.prefijo_len(s):])]

def metrica(s, W=58):
    """-> (corta_larga, huerfanas) de una cadena tokenizada. corta_larga: lineas con relleno < 40 % que no cierran frase seguidas de otra mas larga.
    huerfanas: ultima linea < 10 car. (>=2 lineas) o ultima ventana < 60 % (> 3 lineas)"""
    ls = [l for l in lineas_pantalla(s) if l]
    cl = 0
    for a, b in zip(ls, ls[1:]):
        if len(a) < CORTA * W and len(b) > len(a) and not (R.FIN_FRASE.search(a) or R.FIN_CLAUS.search(a)): cl += 1
    h = 0
    if len(ls) > R.VENT_MAX and sum(len(x) for x in ls[-(len(ls) % R.VENT or R.VENT):]) < R.MIN_ULT * W: h = 1
    elif len(ls) >= 2 and len(ls[-1]) < 10: h = 1
    return cl, h

def desbordo(s, W):
    """1 si la cadena tiene >=2 ventanas (el juego envuelve cada trozo a W) y la ultima ventana tiene <=2 palabras"""
    try: vs = R.ventanas(s[R.prefijo_len(s):], W)
    except Exception: return 0
    if len(vs) < 2: return 0
    return 1 if len(' '.join(vs[-1]).split()) <= 2 else 0

# ---- punto y aparte: SOLO un salto del japones tras «…» se conserva como parrafo; tras 。！？ NO se fuerza (decision del propietario); en modo libre (nº de saltos distinto) no hay duros forzados
FIN_JA = '…'   # solo la pausa «…» se conserva como punto y aparte; un salto tras 。！？ es solo la linea del original (el propietario vio una separacion gratuita en Brennan)
HARD_ORD = set()   # ordinales (entre los saltos no-espacio de la celda) que son punto y aparte
ESTAD = collections.Counter()

def duros_ja(tok):
    """-> (nº de saltos del japones, set de ordinales que siguen a puntuacion final)"""
    out = set(); n = 0; prev = 0
    brks = []
    for t, p in R.S._atoms(tok):
        if R.S._bn(t) == 'NewLine': brks.append((p, len(t)))
    for i, c in enumerate(tok):
        if c == '\n': brks.append((i, 1))
    brks.sort()
    for k, (p, ln) in enumerate(brks):
        ant = R.TOK_RE.sub('', tok[prev:p]).rstrip()
        if ant and ant[-1] in FIN_JA: out.add(k)
        prev = p + ln
    return len(brks), out

_es_duro0 = R.es_duro
def es_duro2(ws, js, i):
    if _es_duro0(ws, js, i): return True
    if not HARD_ORD or js[i][0] == 'sp': return False
    return sum(1 for x in js[:i] if x[0] != 'sp') in HARD_ORD
R.es_duro = es_duro2
_rc0 = R.reflujar_cadena
def rc2(s, tok, W, modo, diag=None):
    global HARD_ORD
    n, hs = duros_ja(tok); HARD_ORD = set()
    VF.update(off=0, bi=0, nb=1, exacto=(modo == 'exacto'))
    try:
        ws, js = R.escanear(s); ws, js = R.normalizar_union(ws, js)
        VF['nb'] = len(R.bloques(ws, js))
        nb = [i for i, x in enumerate(js) if x[0] != 'sp']
        if len(nb) == n: HARD_ORD = hs
        else: HARD_ORD = set()   # modo libre: sin puntos y aparte forzados
    except Exception: pass
    return _rc0(s, tok, W, modo, diag)
R.reflujar_cadena = rc2

def hs_es(s):
    ls = R.partir_lineas(s[R.prefijo_len(s):])
    return set(k for k, l in enumerate(ls[:-1]) if R.FIN_FRASE.search(R.pantalla(l).rstrip()))

def parrafos_fin(s, hs):
    """palabra final y palabra inicial alrededor de cada punto y aparte (ordinales hs) en la cadena tokenizada"""
    ls = R.partir_lineas(s[R.prefijo_len(s):]); out = []
    for k in sorted(hs):
        if k + 1 < len(ls):
            a = R.pantalla(ls[k]).split(); b = R.pantalla(ls[k + 1]).split()
            out.append((a[-1] if a else '', b[0] if b else ''))
    return out

REGISTRO = []
_orig = R.procesar_celda
def _wrap(text, raw, e, W, creador, clave=None, diag=None):
    d = diag if diag is not None else {}
    res = _orig(text, raw, e, W, creador, clave, d)
    try: tok_ = R.S.tokenize_raw(R.G.bytes_ja(text, raw)); nj, hs_ = duros_ja(tok_)
    except Exception: nj, hs_ = 0, set()
    if hs_ and d.get('antes') is not None:
        fin_s = d.get('despues') if res[0] == 'cambiada' and d.get('despues') else d['antes']
        ESTAD['detectados'] += len(hs_)
        libre_ = nj != sum(1 for _ in R.partir_lineas(d['antes'])) - 1
        todos_ = set(parrafos_fin(fin_s, set(range(len(R.partir_lineas(fin_s[R.prefijo_len(fin_s):])) - 1))))
        ok_ = all(x in todos_ for x in parrafos_fin(d['antes'], hs_es(d['antes']) if libre_ else hs_))   # cada punto y aparte sigue siendo un salto entre las mismas palabras
        if ok_: ESTAD['conservados'] += len(hs_)
        else:
            ESTAD['perdidos'] += len(hs_)
            if ESTAD['perdidos'] < 40: print('PERDIDO', repr(d['antes'][:150]), '=>', repr(fin_s[:150]), file=sys.stderr)
    if res[0] == 'cambiada' and d.get('antes') is not None and d.get('despues'):
        x = metrica(d['antes'], W); y = metrica(d['despues'], W)
        dv0 = desbordo(d['antes'], W); dv1 = desbordo(d['despues'], W)
        if dv1 > dv0 or (dv1 == dv0 and (sum(y) > sum(x) or y[1] > x[1])): res = ('ya_correcta', None, res[2])   # nunca empeorar la metrica (salvo que quite una ventana final de 1-2 palabras: prioridad del propietario)
    if d.get('antes') is not None:
        REGISTRO.append((d['antes'], d.get('despues') if res[0] == 'cambiada' else d['antes'], res[0], W))
    return res
R.procesar_celda = _wrap

def mostrar_ven(s, W):
    return '\n'.join('    --- ventana ---\n' + '\n'.join('    ' + l for l in v) for v in R.ventanas(s[R.prefijo_len(s):], W))

def mostrar_s(s):
    return '\n'.join('    [%2d] %s' % (len(x), x) for x in lineas_pantalla(s))

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--familias', default='quest,DefaultTalk,cut_scene,NpcYell,Balloon,Lobby')
    ap.add_argument('--tsv', default=os.path.join(R.RAIZ, 'trabajo', 'informes', 'reflujo_v2_dryrun.tsv'))
    ap.add_argument('--ejemplos', type=int, default=15); ap.add_argument('--seed', type=int, default=20261103)
    ap.add_argument('--clave', action='append', default=['quest/005/ManSea000_00541:81:1'])
    ap.add_argument('--escribir', action='store_true', help='escribe en <root>/traducciones (SOLO sobre una copia en /tmp)'); ap.add_argument('--sin-metricas', action='store_true')
    ap.add_argument('--hojas', default=''); ap.add_argument('--root', default=R.RAIZ)
    ap.add_argument('--paginar', action='store_true', help='celdas no_cabe: reparto por ventanas (R.paginar_cadena)'); ap.add_argument('--sin-ventana-final', action='store_true', help='desactiva la penalizacion de ventana final (comportamiento v2 anterior)')
    a = ap.parse_args(argv)
    VF['on'] = not a.sin_ventana_final
    R.CFG.macros = True; R.CFG.paginar = a.paginar
    filtro = [x for x in a.hojas.split(',') if x]
    fams = a.familias.split(',')
    tsv = open(a.tsv, 'w', encoding='utf-8', newline='\n'); tsv.write('hoja\trow\tcol\tantes\tdespues\n')
    todos = []
    print('familia\tceldas\tcambian\tcorta_larga antes/despues (cambiadas)\thuerfanas antes/despues\tcorta_larga total antes/despues\thuerf total antes/despues')
    for fam in fams:
        W = 50 if fam == 'Lobby' else HARD
        R.CFG.ancho_max = 61
        del REGISTRO[:]; st = collections.defaultdict(collections.Counter); exc = []; cambios = []
        for hoja in R.hojas_de_familia(a.root, fam):
            if filtro and not any(x in hoja for x in filtro): continue
            R.procesar_hoja(a.root, hoja, fam, W, not a.escribir, st, exc, cambios)
        c = st[fam]
        mb = [0, 0]; ma = [0, 0]; tb = [0, 0]; ta = [0, 0]; ob = oa = 0; ejo = []
        for antes, des, res, W_ in REGISTRO:
            x = metrica(antes, W_); y = metrica(des, W_)
            u = desbordo(antes, W_); v = desbordo(des, W_); ob += u; oa += v
            if u and len(ejo) < 3: ejo.append(antes)
            tb[0] += x[0]; tb[1] += x[1]; ta[0] += y[0]; ta[1] += y[1]
            if res == 'cambiada': mb[0] += x[0]; mb[1] += x[1]; ma[0] += y[0]; ma[1] += y[1]
        print('%s\t%d\t%d\t%d/%d\t%d/%d\t%d/%d\t%d/%d\t(exc %d) desbordo<=2pal %d/%d' % (fam, c['en_alcance'], c['cambiada'], mb[0], ma[0], mb[1], ma[1], tb[0], ta[0], tb[1], ta[1], c['excepciones'], ob, oa))
        for e_ in ejo: print('  ej. desbordo (ahora):\n' + mostrar_ven(e_, W))
        for cb in cambios:
            es_a = cb['antes'] if isinstance(cb['antes'], str) else '<NewLine>'.join(cb['antes'])
            es_d = cb['despues'] if isinstance(cb['despues'], str) else '<NewLine>'.join(cb['despues'])
            tsv.write('%s\t%d\t%d\t%s\t%s\n' % (cb['hoja'], cb['k'][0], cb['k'][2], es_a.replace('\n', '\\n').replace('\t', ' '), es_d.replace('\n', '\\n').replace('\t', ' ')))
            todos.append((cb['hoja'], cb['k'][0], cb['k'][2], es_a, es_d))
    print('PUNTO Y APARTE (salto del ja tras puntuacion final): detectados %d, conservados %d, perdidos %d' % (ESTAD['detectados'], ESTAD['conservados'], ESTAD['perdidos']))
    tsv.close()
    rnd = random.Random(a.seed); elegidos = []
    for cl in a.clave:
        h, r, c = cl.rsplit(':', 2)
        for t in todos:
            if t[0] == h and t[1] == int(r) and t[2] == int(c): elegidos.append(t)
    resto = [t for t in todos if t not in elegidos]
    elegidos += rnd.sample(resto, min(max(0, a.ejemplos - len(elegidos)), len(resto)))
    for h, r, c, x, y in elegidos:
        print('\n## %s fila %d col %d\nANTES:\n%s\nDESPUES:\n%s' % (h, r, c, mostrar_s(x), mostrar_s(y)))
    return 0

if __name__ == '__main__': sys.exit(main())
