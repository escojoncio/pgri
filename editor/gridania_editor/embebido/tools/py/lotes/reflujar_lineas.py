"""REFLUJO de saltos de linea del `es` SIN retraducir: une el texto de una celda y lo redistribuye en los MISMOS saltos estructurales, con
lineas <= ancho seguro, cortando en fin de frase / clausula / limite de palabra, sin lineas huerfanas y equilibradas.
Solo cambia DONDE caen los saltos (y los espacios en los limites de linea): el texto, las tildes, la puntuacion y los marcadores quedan identicos.

- Lista de trozos (via simple): se recompone la cadena tokenizada, se reflujan los saltos y se vuelve a trocear: mismo nº de trozos k, mismos separadores.
- Cadena (via compleja): NewLine y LF reales se tratan como saltos reasignables. Modo `exacto` (dialogos): se conserva el nº de saltos que exige el japones
  (NewLine por hueco entre marcadores no-NewLine; LF totales); no se quitan ni se anaden. Modo `libre` (descripcion del creador de personaje, Lobby, cadena con LF):
  cualquier nº de saltos LF >= los del japones.
- Los marcadores que no son NewLine (color, icono, numero) quedan pegados a su palabra; cada salto solo puede caer en su mismo hueco entre marcadores
  (asi la distribucion por huecos que valida el parcheador no cambia). Cadenas con otros marcadores (If, Switch, Run, Raw...) -> excepcion `tokens_no_soportados`.
- Saltos 'duros' (pegados a otro salto, al inicio o al final de la celda) no se tocan: parten la celda en bloques que se reflujan por separado.
- Coste: fin de frase 0 < clausula (, ; :) < corte a media frase (peor tras articulo/preposicion/conjuncion) + irregularidad de anchura + linea final huerfana (< 15).
  Una celda ya valida (todas las lineas <= ancho) se deja si su coste no supera el optimo en mas de MARGEN: idempotente.
- Si no cabe en esos saltos con el ancho dado -> excepcion `no_cabe` (no se toca; hay que acortar). Cada celda cambiada se revalida con construir_dat.evaluar_cadena:
  si no pasa se omite como `rechazo_<motivo>`. No toca `h`, `origen` ni `estado`.
- Familias (--familias): quest, DefaultTalk, Lobby (por defecto); NpcYell, Balloon, cut_scene desactivadas (anchura sin comprobar; admitidas si se piden).
  Anchos: --ancho-dialogo (58) para quest/DefaultTalk/NpcYell/Balloon/cut_scene; --ancho-creador (49) para Lobby.
Uso: python3 -I reflujar_lineas.py [--familias quest,DefaultTalk,Lobby] [--ancho-dialogo 58] [--ancho-creador 49] [--dry-run] [--root RAIZ]
     [--hojas SUBCADENA,...] [--excepciones F.tsv] [--informe F.md] [--ejemplos N] [--clave hoja:row:col ...]
Modos opcionales (apagados por defecto):
  --paginar : para las celdas `no_cabe` (familias de dialogo) modela VENTANAS de 3 lineas visibles (el juego abre una ventana nueva al pasar de 3 lineas; supuesto del
              propietario, NO verificado) y reparte el texto entre los MISMOS k trozos (sin NewLine extra, sin recortar) para que el corte de ventana caiga en fin de frase /
              salto de trozo y la ultima ventana no quede huerfana (< 60 % de una linea). Los trozos pueden pasar de --ancho-dialogo: el juego los envuelve solo. > --max-ventanas -> `demasiado_largo`.
  --macros  : celdas con macros (If, Switch, Split, Sheet, Run, Raw, String...): cada TROZO (tramo entre saltos) que contiene un marcador no soportado se CONGELA (no se toca; su ancho
              visible se estima) y solo se reflujan los trozos de texto plano contiguos. Saltos junto a un trozo congelado = duros. NewLine dentro de <Run> -> `newline_en_run`.
  --simular hoja,row,col (repetible): imprime las ventanas ANTES/DESPUES de una celda y termina. --informe-paginar F.md: informe de paginacion/macros.
SIN --dry-run escribe traducciones/ (backup en trabajo/lotes/bak/<Hoja>.<fecha>.reflujo.jsonl, atomico). NO ejecutar sobre el repo real sin orden del director."""
import sys, os, re, json, argparse, datetime, shutil, glob, collections
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, '..'))
import sestring as S, segmentar as G, construir_dat as C

RAIZ = os.path.abspath(os.path.join(AQUI, '..', '..', '..'))
FAMILIAS_DIALOGO = ('quest', 'DefaultTalk', 'NpcYell', 'Balloon', 'cut_scene')
FAMILIAS_TODAS = FAMILIAS_DIALOGO + ('Lobby',)
POR_DEFECTO = 'quest,DefaultTalk,Lobby'
TOK_OK = ('ColorType', 'EdgeColorType', 'Icon2', 'Num', 'Kilo', 'Italic')
MARGEN = 4.0
class Cfg(object):
    paginar = False; macros = False; maxwin = 4; solo = False; ancho_max = 61
CFG = Cfg()
AUTO = 3.0; ROBUST = 6.0; WCUT = 2.0; WIN_IN = 4.0; HUERF = 60.0; SOLA = 25.0; MIN_ULT = 0.6   # pesos de la paginacion
VENT = 4   # lineas visibles por ventana (propietario 2026-11-04: 4 = maximo absoluto y NO excepcional; el juego abre ventana nueva al pasar de 4)
VENT_MAX = 4   # TOPE duro (propietario 2026-11-04): una ventana de 4 lineas es valida (excepciones); no se repagina ni es huerfana por ser de 4
ABRE = frozenset(('If', 'Switch', 'Split', 'Sheet', 'Payload4A', 'SwitchPlatform', 'Icon'))   # macros que se cierran con MacroEnd
LINEA = 2.0
KEEP = 3.0; SOLA_STD = 10.0   # bonus por conservar un corte del original / linea de una palabra corta
INF = float('inf')
TOK_RE = re.compile(r'<[A-Za-z][A-Za-z0-9]*(?:#[0-9]+)?>')
FIN_FRASE = re.compile(r'[.!?…♪~]+["\'»”’)\]]*$')
FIN_CLAUS = re.compile(r'[;:]["\'»”’)\]]*$')
FIN_COMA = re.compile(r'[,—–]["\'»”’)\]]*$')
STOP = frozenset('''el la los las un una unos unas de del al a en por para con sin y e o u ni que se su sus mi mis tu tus lo le les me te nos
como mas más pero si sí no sobre entre hacia hasta desde ante bajo tras ese esa esos esas este esta estos estas mismo cada muy tan'''.split())

class Congelada(str):
    """palabra que es un trozo entero con macros: no se toca; `vw` = ancho visible estimado"""
    vw = 0; disp = ''

PRE_RE = re.compile(r'^\(-[^<>\n]*?-\)')   # etiqueta del hablante «(-Nombre-)»: el juego no la muestra en la caja

class ConPrefijo(str):
    """primera palabra de la celda con etiqueta de hablante: `vw` = ancho visible sin la etiqueta"""
    vw = 0; pre = 0

def prefijo_len(s):
    m = PRE_RE.match(s); return len(m.group()) if m else 0

def congelada(t, vw, disp=''):
    c = Congelada(t); c.vw = vw; c.disp = disp; return c

def vis(t):
    """longitud visible: sin tokens <...> y con '<<' = '<' (una Congelada devuelve su ancho estimado)"""
    if isinstance(t, (Congelada, ConPrefijo)): return t.vw
    return len(TOK_RE.sub('', t.replace('<<', '\x00')).replace('\x00', '<'))

def plano(t):
    return TOK_RE.sub('', t.replace('<<', '\x00')).replace('\x00', '<')


def no_ok(t):
    """True si la cadena tiene algun marcador que no sea NewLine ni de TOK_OK (macro)"""
    return any(S._bn(a) != 'NewLine' and S._bn(a) not in TOK_OK for a, _ in S._atoms(t))

ANCHO_NOMBRE = 8; ANCHO_SHEET = 16   # estimaciones del nombre del jugador / de un objeto o PNJ de hoja

def analizar(t):
    """-> (ancho visible ESTIMADO, texto de pantalla) de un trozo con macros. Texto fuera de macros = literal; If/Switch/Payload4A/SwitchPlatform = rama mas ancha;
    Split/String = nombre del jugador; Sheet = nombre de hoja; cada macro se muestra como '#' * ancho. Lanza Exc('macro_no_balanceada') si una macro queda abierta."""
    at = {p: a for p, a in ((p, a) for a, p in S._atoms(t))}
    disp = []; pila = []   # marco: [nombre, run_depth, rama_actual, ramas]
    def sumar(n):
        if pila:
            f = pila[-1]
            if f[1] > 0: f[2] += n
    i = 0; N = len(t)
    while i < N:
        if i in at:
            a = at[i]; b = S._bn(a); i += len(a)
            if b == 'Run':
                if pila:
                    f = pila[-1]
                    if f[1] == 0: f[2] = 0
                    f[1] += 1
            elif b == 'RunEnd':
                if pila and pila[-1][1] > 0:
                    f = pila[-1]; f[1] -= 1
                    if f[1] == 0: f[3].append(f[2])
            elif b == 'MacroEnd':
                if pila:
                    f = pila.pop(); nm = f[0]
                    w = ANCHO_NOMBRE if nm in ('Split', 'String') else ANCHO_SHEET if nm == 'Sheet' else 2 if nm == 'Icon' else 1 if nm == 'Raw' else (max(f[3]) if f[3] else 0)
                    if pila: sumar(w)
                    else: disp.append('#' * w)
            elif b in ABRE: pila.append([b, 0, 0, []])
            elif b == 'Raw':
                if not pila: pila.append(['Raw', 0, 0, []])
            elif b == 'String':
                if pila: sumar(ANCHO_NOMBRE)
                elif any(S._bn(x) == 'Raw' and p == i for p, x in at.items()): pila.append(['String', 0, 0, []])
                else: disp.append('#' * ANCHO_NOMBRE)
            continue
        c = t[i]
        if c == '<' and i + 1 < N and t[i + 1] == '<': c = '<'; i += 1
        i += 1
        if pila:
            if pila[-1][1] > 0 and ord(c) >= 0x20: sumar(1)
        elif ord(c) >= 0x20 or c == ' ': disp.append(c)
    if pila: raise Exc('macro_no_balanceada', t[:80])
    d = ''.join(disp)
    return len(d), d

def estimar(t): return analizar(t)[0]

def spans_macro(t):
    """-> [(ini, fin)] de los grupos de macro de primer nivel (opener .. MacroEnd) con las mismas reglas que `analizar`"""
    at = {p: a for a, p in S._atoms(t)}; out = []; pila = 0; ini = 0; i = 0; N = len(t)
    while i < N:
        if i in at:
            a = at[i]; b = S._bn(a); fin = i + len(a)
            if b in ABRE or (b == 'Raw' and pila == 0) or (b == 'String' and pila == 0 and any(S._bn(x) == 'Raw' and p == fin for p, x in at.items())):
                if pila == 0: ini = i
                pila += 1
            elif b == 'MacroEnd' and pila:
                pila -= 1
                if pila == 0: out.append((ini, fin))
            i = fin; continue
        i += 2 if t[i] == '<' and i + 1 < N and t[i + 1] == '<' else 1
    return out

def lf_en_macros(t):
    """nº de saltos LF reales que son parametros de una macro (no son saltos de linea)"""
    return sum(t.count('\n', a, b) for a, b in spans_macro(t)) if '\n' in t else 0

# ---------------------------------------------------------------- escaneo
def escanear(s):
    """cadena tokenizada -> (palabras, uniones). uniones[i] = (clase, hueco, original) entre palabras[i] y palabras[i+1]:
    clase 'sp' (espacio unico), 'NL' (<NewLine>), 'LF' (\\n). hueco = nº de marcadores no-NewLine antes de la union. original = texto del salto.
    Los marcadores no-NewLine quedan dentro de la palabra (ancho cero)."""
    atoms = {p: t for t, p in S._atoms(s)}
    en_macro = set()
    if CFG.macros and '\n' in s:
        for a_, b_ in spans_macro(s): en_macro.update(x for x in range(a_, b_) if s[x] == '\n')
    ws = []; js = []; cur = []; gap = 0; i = 0; n = len(s)
    pre = prefijo_len(s)
    if pre: cur.append(s[:pre]); i = pre
    while i < n:
        if i in atoms:
            t = atoms[i]; i += len(t)
            if S._bn(t) == 'NewLine': ws.append(''.join(cur)); cur = []; js.append(('NL', gap, t))
            else: cur.append(t); gap += 1
            continue
        c = s[i]
        if c == '\n' and i not in en_macro: ws.append(''.join(cur)); cur = []; js.append(('LF', gap, c))
        elif c == ' ' and (i == 0 or s[i - 1] != ' ') and (i + 1 >= n or s[i + 1] != ' '):
            ws.append(''.join(cur)); cur = []; js.append(('sp', gap, ' '))
        else: cur.append(c)
        i += 1
    ws.append(''.join(cur))
    if pre:
        w0 = ConPrefijo(ws[0]); w0.pre = pre; w0.vw = vis(ws[0][pre:]); ws[0] = w0
    if CFG.macros: ws, js = congelar(ws, js)
    return ws, js

def congelar(ws, js):
    """CFG.macros: cada trozo (tramo entre uniones NL/LF) con algun marcador no soportado pasa a ser UNA palabra Congelada (conserva sus espacios); sus saltos vecinos son duros"""
    ow = []; oj = []; i = 0; n = len(ws)
    while i < n:
        j = i
        while j < n - 1 and js[j][0] == 'sp': j += 1
        txt = ''.join(ws[x] + (js[x][2] if x < j else '') for x in range(i, j + 1))
        pr = ws[0].pre if i == 0 and isinstance(ws[0], ConPrefijo) else 0
        if no_ok(txt):
            an = analizar(txt[pr:]); ow.append(congelada(txt, an[0], an[1]))
        else: ow.extend(ws[i:j + 1]); oj.extend(js[i:j])
        if j < n - 1: oj.append(js[j])
        i = j + 1
    return ow, oj

def normalizar_union(ws, js):
    """quita las palabras vacias que quedan entre un espacio y un salto (`A <NL>B`): el espacio sobra"""
    cambio = True
    while cambio:
        cambio = False
        for i in range(1, len(ws) - 1):
            if ws[i] == '' and (js[i - 1][0] == 'sp') != (js[i][0] == 'sp'):
                sp = i - 1 if js[i - 1][0] == 'sp' else i
                del js[sp]
                del ws[i]
                cambio = True
                break
    return ws, js

def simbolo(w):
    """palabra no vacia sin letras ni digitos (`[`, `]`, `*`, `※`): sus saltos no se tocan. Una palabra Congelada siempre"""
    if isinstance(w, Congelada): return True
    p = plano(w)
    return p != '' and not any(c.isalnum() for c in p)

def es_duro(ws, js, i):
    return js[i][0] != 'sp' and (ws[i] == '' or ws[i + 1] == '' or simbolo(ws[i]) or simbolo(ws[i + 1]))

def bloques(ws, js):
    """-> lista de bloques [(a, b)] (indices de palabras inclusivos). Saltos duros (palabra vacia a un lado) parten bloques."""
    out = []; a = 0
    for i, (k, g, o) in enumerate(js):
        if es_duro(ws, js, i): out.append((a, i)); a = i + 1
    out.append((a, len(ws) - 1))
    return out

# ---------------------------------------------------------------- costes
CONJ = frozenset('y e o u ni pero aunque que donde cuando como porque si mientras pues sino cuyo cuya quien'.split())
ART = frozenset('el la los las un una unos unas este esta estos estas ese esa esos esas aquel aquella su sus mi mis tu tus nuestro nuestra nuestros nuestras al del lo'.split())
PREP = frozenset('de a en con por para sin sobre entre hacia hasta desde ante bajo tras según durante contra'.split())
CLIT = frozenset('se me te le les nos os'.split())
AUXI = frozenset('he has ha hemos han había habías habíamos habían habré habrá habrás habrían hube hubo haya hayas hayan estoy está están estamos estás voy vas va vamos van no muy más tan'.split())
APERT = ('¿', '¡', '(', '«', '"', '“', '‘')
CIERRE = (')', ']', '»', '"', '”', '’', ',', '.', ';', ':', '!', '?', '…')

def base_palabra(p):
    return re.sub(r'[^\wÀ-ɏ]', '', p).lower()

def coste_corte(w, w_sig):
    """coste de cortar tras la palabra `w` (con `w_sig` detras): fin de frase 0 < clausula 1 < coma 2 (0.5 si sigue conjuncion/relativo) < corte antes de conjuncion/relativo 3
    < corte a media frase 10 (+14 tras articulo/determinante, +12 tras preposicion, +10 tras clitico/auxiliar/«no», +10 entre dos palabras con mayuscula = nombre propio)"""
    p = plano(w); sig = plano(w_sig); b = base_palabra(p); bs = base_palabra(sig)
    if FIN_FRASE.search(p): return 0.0
    if FIN_CLAUS.search(p): return 1.0
    if FIN_COMA.search(p): return 0.5 if bs in CONJ else 2.0
    c = 10.0
    if b in ART: c += 14.0
    elif b in PREP: c += 12.0
    elif b in CLIT or b in AUXI: c += 10.0
    elif b in CONJ: c += 8.0
    elif bs in CONJ: c = 3.0
    if p[:1].isupper() and sig[:1].isupper() and len(b) > 0: c += 10.0
    if p.endswith(APERT): c += 20.0
    if sig[:1] in CIERRE: c += 20.0
    return c

def irregular(L, W, ultima):
    r = 8.0 * ((W - L) / float(W)) ** 2
    if ultima: r *= 0.5
    if ultima and L < 15: r += 6.0
    return r

class Bloque(object):
    def __init__(self, ws, js, a, b):
        self.ws = ws[a:b + 1]; self.js = js[a:b]; self.n = len(self.ws)
        self.v = [vis(w) for w in self.ws]
        self.P = [0]
        for x in self.v: self.P.append(self.P[-1] + x)
        # candidatas: espacio normal o salto blando
        self.cand = [True] * (self.n - 1)
        for i, (k, g, o) in enumerate(self.js):
            if k == 'sp' and (self.ws[i] == '' or self.ws[i + 1] == ''): self.cand[i] = False
        self.bc = [coste_corte(self.ws[i], self.ws[i + 1]) for i in range(self.n - 1)]
        prof = 0
        for i in range(self.n - 1):   # corte dentro de «...»
            pw = plano(self.ws[i]); prof += pw.count('«') - pw.count('»')
            if prof > 0 and not pw.endswith('»'): self.bc[i] += 12.0
        self.actual = [i for i, (k, g, o) in enumerate(self.js) if k != 'sp']; self.act_set = frozenset(self.actual)   # (los duros nunca quedan dentro de un bloque)   # cortes actuales (blandos)
    def ancho(self, a, b):
        """ancho visible de la linea con palabras a..b"""
        return self.P[b + 1] - self.P[a] + (b - a)

def coste_cortes(bl, cortes, W):
    """coste de una lista de cortes (indices de union); INF si alguna linea supera W"""
    c = 0.0; ini = 0
    cortes = sorted(cortes)
    for p in cortes:
        L = bl.ancho(ini, p)
        if L > W: return INF
        c += irregular(L, W, False) + LINEA + bl.bc[p] + (SOLA_STD if p == ini and L < 12 else 0.0) - (KEEP if p in bl.act_set else 0.0); ini = p + 1
    L = bl.ancho(ini, bl.n - 1)
    if L > W: return INF
    return c + irregular(L, W, True) + LINEA + (SOLA_STD if ini == bl.n - 1 and L < 12 and bl.n > 1 else 0.0)

def optimizar(bl, r_min, r_max, W, req=None):
    """-> (coste, cortes) o (INF, None). Exactamente r cortes si r_min == r_max; si no, el optimo con r en [r_min, r_max].
    req: lista (por corte, en orden) con el hueco exigido (o None = libre)."""
    n = bl.n
    if n == 1: return (0.0 + irregular(bl.ancho(0, 0), W, True) + LINEA, []) if (r_min == 0 and bl.ancho(0, 0) <= W) else (INF, None)
    mejor = (INF, None)
    # f[j][p]: coste con j cortes, el ultimo tras la palabra p
    f = [dict() for _ in range(max(r_max, 1) + 1)]; par = [dict() for _ in range(max(r_max, 1) + 1)]
    for p in range(n - 1):
        if not bl.cand[p]: continue
        L = bl.ancho(0, p)
        if L > W: break
        if req is not None and req[0] is not None and bl.js[p][1] != req[0]: continue
        f[1][p] = irregular(L, W, False) + LINEA + bl.bc[p] + (SOLA_STD if p == 0 and L < 12 else 0.0) - (KEEP if p in bl.act_set else 0.0); par[1][p] = -1
    for j in range(2, r_max + 1):
        for p in range(j - 1, n - 1):
            if not bl.cand[p]: continue
            if req is not None and req[j - 1] is not None and bl.js[p][1] != req[j - 1]: continue
            bestc = INF; bestq = None
            for q, cq in f[j - 1].items():
                if q >= p: continue
                L = bl.ancho(q + 1, p)
                if L > W: continue
                c = cq + irregular(L, W, False) + LINEA + bl.bc[p] + (SOLA_STD if p == q + 1 and L < 12 else 0.0) - (KEEP if p in bl.act_set else 0.0)
                if c < bestc - 1e-9 or (abs(c - bestc) <= 1e-9 and bestq is not None and q < bestq): bestc = c; bestq = q
            if bestq is not None: f[j][p] = bestc; par[j][p] = bestq
    for j in range(max(r_min, 1) if n > 1 else 0, r_max + 1):
        for p, cp in f[j].items():
            L = bl.ancho(p + 1, n - 1)
            if L > W: continue
            c = cp + irregular(L, W, True) + LINEA + (SOLA_STD if p + 1 == n - 1 and L < 12 else 0.0)
            if c < mejor[0] - 1e-9: mejor = (c, (j, p))
    if r_min == 0 and bl.ancho(0, n - 1) <= W:
        c = irregular(bl.ancho(0, n - 1), W, True) + LINEA
        if c < mejor[0] - 1e-9: return (c, [])
    if mejor[1] is None: return (INF, None)
    j, p = mejor[1]; cortes = []
    while j >= 1: cortes.append(p); p = par[j][p]; j -= 1
    return (mejor[0], sorted(cortes))


TOL = 61   # tolerancia (medida en el juego por el propietario): una linea de hasta 61 car. vale si termina en signo de puntuacion
FIN_PUNT = re.compile(r'[.,;:!?…»”\)]$')

def cabe(bl, a, b, W):
    L = bl.ancho(a, b)
    return L <= W or (L <= TOL and FIN_PUNT.search(plano(bl.ws[b])) is not None)

def piezas(bl, cs):
    ini = 0; out = []
    for c in sorted(cs) + [bl.n - 1]: out.append((ini, c)); ini = c + 1
    return out

def actual_solas(bl):
    return set(x for x in piezas(bl, bl.actual) if x[0] == x[1])

def cascada(bl, r, req, W):
    """MINIMO CAMBIO: conserva los cortes actuales cuando la linea cabe; si una se pasa, mueve solo las palabras necesarias al trozo siguiente (en cascada), eligiendo el corte
    de menor coste entre los que caben. -> lista de cortes o None si no hay manera (entonces se usa el optimo global)"""
    cuts = sorted(bl.actual)
    if len(cuts) != r: return None
    ini = 0; out = []
    for j, c in enumerate(cuts):
        if not cabe(bl, ini, c, W):
            mejor = None
            for q in range(c - 1, ini - 1, -1):
                if not bl.cand[q] or not cabe(bl, ini, q, W): continue
                if req is not None and req[j] is not None and bl.js[q][1] != req[j]: continue
                co = bl.bc[q] + 1.0 * (c - q) + (SOLA_STD if q == ini and bl.ancho(ini, q) < 12 else 0.0)
                if mejor is None or co < mejor[0] - 1e-9: mejor = (co, q)
            if mejor is None: return None
            c = mejor[1]
        out.append(c); ini = c + 1
    if not cabe(bl, ini, bl.n - 1, W): return None
    return out

def lineas_ok(s, W):
    """todas las lineas (sin la etiqueta del hablante) caben en W (o en TOL si acaban en puntuacion)"""
    s = s[prefijo_len(s):]
    for x in partir_lineas(s):
        w_ = analizar(x)[0] if no_ok(x) else vis(x)
        if w_ > W and not (w_ <= TOL and FIN_PUNT.search(plano(x).rstrip()) is not None): return False
    return True

# ---------------------------------------------------------------- celda
class Exc(Exception):
    def __init__(self, motivo, detalle=''):
        Exception.__init__(self, motivo, detalle); self.motivo = motivo; self.detalle = detalle

def tokens_ok(s):
    prof = 0
    for t, p in S._atoms(s):
        b = S._bn(t)
        if b == 'Run': prof += 1
        elif b == 'RunEnd': prof = max(0, prof - 1)
        if b == 'NewLine':
            if prof > 0: raise Exc('newline_en_run', t)
        elif b not in TOK_OK and not CFG.macros: raise Exc('tokens_no_soportados', t)

def reflujar_cadena(s, tok, W, modo, diag=None):
    """s: cadena tokenizada del `es` (con sus saltos actuales); tok: source; modo 'exacto' | 'libre' (LF) | 'libre_nl' (NewLine extra, solo sin marcadores no-NewLine). -> (nueva cadena, coste_actual, coste_nuevo, info). Lanza Exc."""
    tokens_ok(s)
    ws, js = escanear(s)
    ws, js = normalizar_union(ws, js)
    bls = [Bloque(ws, js, a, b) for a, b in bloques(ws, js)]
    # saltos requeridos por el japones
    sn = [t for t, _ in S._atoms(tok)]; sr, sg, _ = S._huecos(sn)
    req_lf = tok.count('\n') - (lf_en_macros(tok) if CFG.macros else 0)
    duros = [(k, g) for i, (k, g, o) in enumerate(js) if es_duro(ws, js, i)]
    # cuentas por clase y hueco
    plan = []   # por bloque: (r_min, r_max, req)
    libre = modo != 'exacto'
    if libre:
        if modo == 'libre' and (any(k == 'NL' for k, g, o in js) or any(S._bn(t) == 'NewLine' for t, _ in S._atoms(tok))): raise Exc('libre_con_newline', 'cadena con <NewLine>: modo exacto')
        kind = 'LF' if modo == 'libre' else 'NL'
        req_tot = req_lf if modo == 'libre' else sum(sg)
        hard_n = sum(1 for k, g in duros if k == kind)
        falta = req_tot - hard_n
        for bl in bls:
            jmax = max(len(bl.actual), 1)
            jmax = min(bl.n - 1, max(jmax, sum(bl.v) // max(W // 2, 1) + 2) + 2)
            plan.append((max(0, falta) if len(bls) == 1 else 0, max(jmax, 0, falta if len(bls) == 1 else 0), None))
    else:
        # exacto: nº de saltos blandos requerido por hueco (NL) y total (LF)
        nl_hueco = collections.Counter(); lf_blandos = 0
        for k, g in duros:
            if k == 'NL': nl_hueco[g] += 1
        need_nl = {g: max(0, sg[g] - nl_hueco.get(g, 0)) for g in range(len(sg))}
        need_lf = max(0, req_lf - sum(1 for k, g in duros if k == 'LF'))
        have_nl = collections.Counter(); have_lf = 0
        for bl in bls:
            for k, g, o in bl.js:
                if k == 'NL': have_nl[g] += 1
                elif k == 'LF': have_lf += 1
        for g in set(have_nl) | set(need_nl):
            if have_nl.get(g, 0) < need_nl.get(g, 0): raise Exc('faltan_saltos', 'hueco %d' % g)
        if have_lf < need_lf: raise Exc('faltan_saltos', 'LF')
        # extras: solo repartibles si el hueco/clase aparece en un unico bloque
        for g in have_nl:
            if have_nl[g] > need_nl.get(g, 0):
                if sum(1 for bl in bls if any(k == 'NL' and gg == g for k, gg, o in bl.js)) > 1: raise Exc('extras_ambiguos', 'NL hueco %d' % g)
        if have_lf > need_lf and sum(1 for bl in bls if any(k == 'LF' for k, gg, o in bl.js)) > 1: raise Exc('extras_ambiguos', 'LF')
        asignado = collections.Counter(); asig_lf = 0
        for bl in bls:
            seq = []
            for k, g, o in bl.js:
                if k == 'sp': continue
                if k == 'NL':
                    if asignado[g] < need_nl.get(g, 0): asignado[g] += 1; seq.append((k, g))
                else:
                    if asig_lf < need_lf: asig_lf += 1; seq.append((k, g))
            plan.append((len(seq), len(seq), [g if k == 'NL' else None for k, g in seq], [k for k, g in seq]))
    if diag is not None and not libre: diag['k'] = max(pl[0] for pl in plan) + 1
    # optimizar cada bloque
    cortes_all = []; c_act = 0.0; c_new = 0.0; lineas_max = 0; fallo = None
    for bi, bl in enumerate(bls):
        pl = plan[bi]
        ca = coste_cortes(bl, bl.actual, W)
        res = None
        if not libre:
            cs = cascada(bl, pl[0], pl[2] if pl[0] else None, W)
            if cs is not None and not any(bl.ancho(a_, b_) < 12 and a_ == b_ and bl.n > 1 and (a_, b_) not in actual_solas(bl) for a_, b_ in piezas(bl, cs)):
                res = (coste_cortes(bl, cs, W), cs)
        if res is None:
            if libre: res = optimizar(bl, pl[0], pl[1], W)
            else: res = optimizar(bl, pl[0], pl[1], W, pl[2] if pl[0] else None)
        if res[1] is None:
            fallo = (bi, bl, pl); break
        c_act += ca; c_new += res[0]; cortes_all.append(res[1]); lineas_max = max(lineas_max, len(res[1]) + 1)
    if fallo is not None:
        bi, bl, pl = fallo
        pag_ok = CFG.paginar and not libre and not (diag or {}).get('creador')
        if bl.n == 1 and isinstance(bl.ws[0], Congelada) and not pag_ok:
            raise Exc('macro_pieza_larga', 'trozo con macros de %d car. estimados > %d' % (bl.v[0], W))
        if pag_ok:
            return paginar_cadena(s, ws, js, bls, plan, W, diag)
        minimas = -(-sum(bl.v) // W) if W else 0
        raise Exc('no_cabe', 'bloque %d: %d palabras, %d car. visibles, %s saltos, ancho %d' % (bi, bl.n, sum(bl.v) + bl.n - 1, pl[0] if not libre else 'libres', W))
    if libre and falta > 0 and sum(len(c) for c in cortes_all) < falta: raise Exc('faltan_saltos', 'el japones exige %d saltos' % req_tot)
    return reconstruir(ws, js, bls, cortes_all, plan, libre, modo), c_act, c_new, {'lineas': lineas_max, 'bloques': len(bls)}

def reconstruir(ws, js, bls, cortes_all, plan, libre, modo):
    out = []
    for bi, bl in enumerate(bls):
        cortes = set(cortes_all[bi])
        kinds = None if libre else plan[bi][3]
        ki = 0
        for i in range(bl.n):
            out.append(bl.ws[i])
            if i < bl.n - 1:
                if i in cortes:
                    if libre: out.append('\n' if modo == 'libre' else '<NewLine>')
                    else:
                        k = kinds[ki]; ki += 1
                        out.append('<NewLine>' if k == 'NL' else '\n')
                else: out.append(' ')
        # union dura tras el bloque (si no es el ultimo)
        if bi < len(bls) - 1:
            idx = sum(b.n for b in bls[:bi + 1]) - 1
            out.append(js[idx][2])
    return ''.join(out)

def paginar_cadena(s, ws, js, bls, plan, W, diag):
    """celda `no_cabe`: reparto por ventanas (ver cabecera). -> (nueva cadena, coste_actual, coste_nuevo, info) o lanza Exc"""
    d = diag if diag is not None else {}
    d['pag'] = True
    # propietario 2026-11-05: todas las celdas pueden usar hasta 4 lineas; el diario (SEQ/TODO) no abre ventanas: tope = UNA ventana de VENT lineas
    cap = VENT if d.get('diario') else CFG.maxwin * VENT
    actual0 = [list(bl.actual) for bl in bls]; actual = actual0
    ca0 = None; cambiado = False
    for it in range(5):   # se itera hasta que el reparto sea estable (idempotencia)
        ca, cta, wfa = evaluar_layout(bls, actual, W, cap)
        if ca0 is None: ca0 = ca
        mejor = paginar_celda(bls, plan, W, cap)
        if mejor is None:
            if it > 0: break
            if d.get('diario'): raise Exc('diario_sin_ventanas', 'texto del diario de misiones: no cabe en %d lineas' % VENT)
            if paginar_celda(bls, plan, W, 99, 99) is not None: raise Exc('demasiado_largo', 'mas de %d ventanas de %d lineas' % (CFG.maxwin, VENT))
            raise Exc('no_cabe', 'sin reparto posible con los saltos fijos del japones')
        cn, ctn, wfn, cortes_all = mejor
        ok_n = not huerfana(ctn, wfn, W); ok_a = ca < INF and not huerfana(cta, wfa, W)
        d['pag_lineas'] = (cta, ctn)
        qa = calidad(bls, ws, actual, W); qn = calidad(bls, ws, cortes_all, W)
        # se conserva la celda si ya esta bien: cabe en una ventana, o su corte de ventana ya es fin de frase / clausula / coma (coste <= 3); solo se cambia si mejora el corte de ventana o quita la huerfana
        if ok_a and (not ok_n or cta <= VENT_MAX or qa[2] <= 3.0 or qn[2] + 4.0 > qa[2]): break
        if not ok_n:
            if it > 0: break
            raise Exc('k1_ultima_huerfana' if d['k'] == 1 else 'ultima_huerfana', 'ultima ventana de %d caracteres (< %d)' % (wfn, int(MIN_ULT * W)))
        if [sorted(c) for c in cortes_all] == [sorted(c) for c in actual]: break
        actual = [list(c) for c in cortes_all]; cambiado = True
        for bl, c in zip(bls, actual): bl.actual = list(c); bl.act_set = frozenset(c); bl.__dict__.pop('_ep', None)
    if not cambiado: return s, ca0, ca0, {'lineas': cta, 'bloques': len(bls), 'pag': True}
    return reconstruir(ws, js, bls, actual, plan, False, 'exacto'), ca0, evaluar_layout(bls, actual, W, cap)[0], {'lineas': evaluar_layout(bls, actual, W, cap)[1], 'bloques': len(bls), 'pag': True}

# ---------------------------------------------------------------- paginacion (ventanas de VENT lineas)
def tabla_alcance(bl, W):
    """reach[s] = ultima palabra e tal que las palabras s..e caben en W (siempre >= s)"""
    cache = bl.__dict__.setdefault('_reach', {})
    if W not in cache:
        r = [0] * bl.n; e = 0
        for s in range(bl.n):
            if e < s: e = s
            while e + 1 < bl.n and bl.ancho(s, e + 1) <= W: e += 1
            r[s] = e
        cache[W] = r
    return cache[W]

def lineas_rango(bl, a, b, W):
    """envuelve voraz las palabras a..b a ancho W -> [(ini, fin)]"""
    cache = bl.__dict__.setdefault('_lr', {})
    k = (a, b, W)
    if k not in cache:
        reach = tabla_alcance(bl, W); out = []; s = a
        while s <= b:
            e = min(reach[s], b); out.append((s, e)); s = e + 1
        cache[k] = out
    return cache[k]

def lineas_pieza(bl, a, b, W):
    """-> [(ancho, ultima_palabra)] de las lineas de la pieza a..b envuelta a W. Un trozo congelado se envuelve por su texto de pantalla"""
    if a == b and isinstance(bl.ws[a], Congelada):
        return [(len(x), a) for x in pieza_lineas(bl.ws[a].disp, W)]
    return [(bl.ancho(s_, e_), e_) for s_, e_ in lineas_rango(bl, a, b, W)]

def eval_pieza(bl, a, b, g0m, final, W):
    """coste de la pieza (palabras a..b = un trozo entre saltos fijos; el juego la envuelve en N lineas) cuya primera linea es la linea global g0m (mod VENT).
    -> (coste, nlineas, suma_anchos, fill_ultima_ventana_abierta | None si la pieza no abre ventana)"""
    cache = bl.__dict__.setdefault('_ep', {})
    k = (a, b, g0m, final, W)
    if k in cache: return cache[k]
    L = lineas_pieza(bl, a, b, W); nl = len(L); cost = 0.0; sw = 0; wf = None
    for l, (w, e_) in enumerate(L):
        ult_pieza = l == nl - 1; ult_celda = final and ult_pieza
        cost += LINEA + irregular(w, W, ult_celda)
        if w < 8 and not ult_celda and bl.n > 1: cost += SOLA   # linea de una palabra corta en medio del texto
        g = g0m + l
        if g % VENT == 0: wf = 0
        if wf is not None: wf += w
        sw += w
        if not ult_celda:
            bcut = bl.bc[e_] if e_ < bl.n - 1 else 0.0
            cost += (1.0 if ult_pieza else 0.5) * bcut
            if ult_pieza and e_ in bl.act_set: cost -= KEEP
            if (g + 1) % VENT == 0: cost += WCUT * bcut + (0.0 if ult_pieza else WIN_IN)
    cost += (nl - 1) * AUTO
    if nl > 1 and len(lineas_pieza(bl, a, b, W + 3)) != nl: cost += ROBUST
    cache[k] = (cost, nl, sw, wf)
    return cache[k]

def terminal(ct, wf, W, maxwin):
    """penalizacion de la ultima ventana: ct = lineas totales, wf = caracteres de la ultima ventana"""
    if ct <= 0: return 0.0
    nw = -(-ct // VENT)
    if nw > maxwin: return INF
    if nw == 1 or ct <= VENT_MAX: return 0.0
    if wf < MIN_ULT * W: return HUERF + (MIN_ULT * W - wf) * 0.5
    if ct % VENT == 1: return HUERF   # ultima ventana de 1 sola linea
    return 4.0 * max(0.0, 1.0 - wf / (1.5 * W))

def huerfana(ct, wf, W):
    return ct > VENT_MAX and (wf < MIN_ULT * W or ct % VENT == 1)

def dp_bloque(bl, r, req, W, c0, wf0, final, cap):
    """reparto optimo de las palabras del bloque en r+1 trozos (cortes en uniones con el hueco exigido por `req`), sabiendo que ya hay c0 lineas globales
    y wf0 caracteres en la ventana abierta. -> {lineas_del_bloque: (coste, fill_ventana_abierta, cortes)} (cap = tope de lineas globales)"""
    n = bl.n
    if r == 0:
        cost, nl, sw, wf = eval_pieza(bl, 0, n - 1, c0 % VENT, final, W)
        if c0 + nl > cap: return {}
        return {nl: (cost, wf if wf is not None else wf0 + sw, [])}
    f = [None] * (r + 1); f[0] = {(-1, 0): (0.0, wf0, None)}
    for j in range(1, r + 1):
        cur = {}
        for p in range(j - 1, n - 1):
            if not bl.cand[p]: continue
            if req is not None and req[j - 1] is not None and bl.js[p][1] != req[j - 1]: continue
            for (q, c), (cq, wfq, _) in f[j - 1].items():
                if q >= p: continue
                cost, nl, sw, wf = eval_pieza(bl, q + 1, p, (c0 + c) % VENT, False, W)
                c2 = c + nl
                if c0 + c2 + (r - j + 1) > cap: continue
                tot = cq + cost; wfo = wf if wf is not None else wfq + sw
                key = (p, c2)
                if key not in cur or tot < cur[key][0] - 1e-9: cur[key] = (tot, wfo, (q, c))
        f[j] = cur
        if not cur: return {}
    res = {}
    for (p, c), (cp, wfp, _) in f[r].items():
        cost, nl, sw, wf = eval_pieza(bl, p + 1, n - 1, (c0 + c) % VENT, final, W)
        c2 = c + nl
        if c0 + c2 > cap: continue
        tot = cp + cost; wfo = wf if wf is not None else wfp + sw
        if c2 not in res or tot < res[c2][0] - 1e-9: res[c2] = (tot, wfo, (p, c))
    out = {}
    for c2, (tot, wfo, last) in res.items():
        cortes = []; st_ = last; j = r
        while j >= 1:
            cortes.append(st_[0]); st_ = f[j][st_][2]; j -= 1
        out[c2] = (tot, wfo, sorted(cortes))
    return out

def evaluar_layout(bls, cortes_all, W, cap):
    """mismo modelo para un reparto dado -> (coste, lineas, fill_ultima_ventana) con coste INF si supera cap"""
    c0 = 0; wf0 = 0; tot = 0.0
    for bi, bl in enumerate(bls):
        final = bi == len(bls) - 1; cuts = sorted(cortes_all[bi]); ini = 0
        for p in cuts + [bl.n - 1]:
            fin = final and p == bl.n - 1
            cost, nl, sw, wf = eval_pieza(bl, ini, p, c0 % VENT, fin, W)
            tot += cost; wf0 = wf if wf is not None else wf0 + sw; c0 += nl; ini = p + 1
    if c0 > cap: return (INF, c0, wf0)
    return (tot + terminal(c0, wf0, W, CFG.maxwin), c0, wf0)

def calidad(bls, ws_g, cortes_all, W):
    """-> (lineas, fill_ultima_ventana, coste_de_los_cortes_de_ventana) de un reparto"""
    wf = 0; wc = 0.0; off = 0; nlin = 0
    for bi, bl in enumerate(bls):
        cuts = sorted(cortes_all[bi]); ini = 0
        for p in cuts + [bl.n - 1]:
            L = lineas_pieza(bl, ini, p, W)
            for l, (w, e_) in enumerate(L):
                if nlin % VENT == 0: wf = 0
                wf += w; nlin += 1
                ult_celda = bi == len(bls) - 1 and p == bl.n - 1 and l == len(L) - 1
                if nlin % VENT == 0 and not ult_celda:
                    gi = off + e_
                    wc += coste_corte(ws_g[gi], ws_g[gi + 1]) if gi + 1 < len(ws_g) else 0.0
            ini = p + 1
        off += bl.n
    return nlin, wf, wc

def paginar_celda(bls, plan, W, cap, maxwin=None):
    """-> (coste, lineas, fill, cortes_all) o None si no hay reparto"""
    estados = {0: (0.0, 0, [])}
    for bi, bl in enumerate(bls):
        final = bi == len(bls) - 1; r = plan[bi][0]; req = plan[bi][2] if r else None
        nuevos = {}
        for c0, (cost0, wf0, cuts0) in estados.items():
            for cl, (cst, wfo, cuts) in dp_bloque(bl, r, req, W, c0, wf0, final, cap).items():
                ct = c0 + cl; tot = cost0 + cst
                if ct not in nuevos or tot < nuevos[ct][0] - 1e-9: nuevos[ct] = (tot, wfo, cuts0 + [cuts])
        estados = nuevos
        if not estados: return None
    mejor = None
    for ct, (cst, wf, cuts) in sorted(estados.items()):
        t = cst + terminal(ct, wf, W, CFG.maxwin if maxwin is None else maxwin)
        if mejor is None or t < mejor[0] - 1e-9: mejor = (t, ct, wf, cuts)
    return mejor if mejor and mejor[0] < INF else None

def pieza_lineas(txt, W):
    """envuelve voraz una pieza (texto de pantalla) a ancho W -> lista de lineas"""
    if txt == '': return ['']
    ws = re.split(r' (?! )', txt); out = []; cur = None
    for w in ws:
        if cur is None: cur = w
        elif len(cur) + 1 + len(w) <= W: cur += ' ' + w
        else: out.append(cur); cur = w
    out.append(cur); return out

def ventanas(s, W):
    """cadena tokenizada del `es` (con sus saltos) -> lista de ventanas, cada una lista de hasta VENT lineas de pantalla"""
    lineas = []
    for piece in re.split(r'\n|<NewLine(?:#[0-9]+)?>', s):
        lineas.extend(pieza_lineas(pantalla(piece), W))
    return [lineas[i:i + VENT] for i in range(0, len(lineas), VENT)]

def pantalla(t):
    if not no_ok(t): return plano(t)
    try: return analizar(t)[1]
    except Exc: return plano(t)

def metricas(vs):
    """ventanas -> dict(nv, lineas, ultima = caracteres de la ultima ventana)"""
    n = sum(len(v) for v in vs)
    return {'nv': len(vs), 'lineas': n, 'ultima': sum(len(l) for l in vs[-1]) if vs else 0}

def caja(v, W, tit):
    out = ['+-- %s ' % tit + '-' * max(0, W + 2 - len(tit) - 4) + '+']
    for l in v: out.append('| ' + l.ljust(W) + ' |')
    out.append('+' + '-' * (W + 2) + '+'); return '\n'.join(out)

def texto_ventanas(vs, W):
    return '\n'.join(caja(v, W, 'ventana %d/%d' % (i + 1, len(vs))) for i, v in enumerate(vs))

def invariante(a, b):
    """mismo texto salvo espacios/saltos; mismos marcadores no-NewLine en el mismo orden"""
    quitar = lambda x: re.sub(r'<NewLine(?:#[0-9]+)?>|[\n ]', '', x)
    ta = [t for t, _ in S._atoms(a) if S._bn(t) != 'NewLine']; tb = [t for t, _ in S._atoms(b) if S._bn(t) != 'NewLine']
    return quitar(a) == quitar(b) and ta == tb

def partir_lista(s, seps):
    """parte la cadena tokenizada `s` en len(seps)+1 trozos por los separadores del japones (tokens con su nombre, en orden); los NewLine EXTRA
    (nombre distinto) quedan dentro del trozo como token. ValueError si faltan separadores."""
    out = []; prev = 0; i = 0
    for tk, p in S._atoms(s):
        if i < len(seps) and tk == seps[i]: out.append(s[prev:p]); prev = p + len(tk); i += 1
    if i != len(seps): raise ValueError('faltan separadores')
    out.append(s[prev:])
    return [x.replace('<<', '<') for x in out]

def partir_lineas(s):
    """parte la cadena tokenizada en lineas por <NewLine> y LF reales (los LF que son parametro de una macro no cuentan)"""
    if '\n' not in s or not no_ok(s): return re.split(r'\n|<NewLine(?:#[0-9]+)?>', s)
    dentro = set()
    for a_, b_ in spans_macro(s): dentro.update(range(a_, b_))
    out = []; prev = 0
    for m in re.finditer(r'\n|<NewLine(?:#[0-9]+)?>', s):
        if m.start() in dentro: continue
        out.append(s[prev:m.start()]); prev = m.end()
    out.append(s[prev:]); return out

def lineas_vis(s):
    s = s[prefijo_len(s):]
    out = []
    for x in partir_lineas(s):
        if no_ok(x):
            try: out.append(analizar(x)[0])
            except Exc: out.append(len(plano(x)))   # trozo con <NewLine> dentro de una macro (ramas If/Switch): fragmento no balanceado, se mide en plano
        else: out.append(vis(x))
    return out

def procesar_celda(text, raw, e, W, creador, clave=None, diag=None):
    """-> ('cambiada', es_nuevo, info) | ('ya_correcta', None, info) | ('sin_saltos'|'excepcion', motivo, detalle). `e` = fila de traducciones (no se modifica)."""
    tok = S.tokenize_raw(G.bytes_ja(text, raw))
    if '\n' not in tok and not any(S._bn(t) == 'NewLine' for t, _ in S._atoms(tok)): return ('sin_saltos', None, '')
    es = e['es']
    try: C.evaluar_cadena(text, raw, e)
    except C.Rechazo as r: return ('excepcion', 'rechazo_previo_' + r.motivo, r.detalle)
    lista = isinstance(es, list)
    try:
        if lista:
            tr, seps = G.trocear(tok); s = G.recomponer(seps, es)
        else: s = es
    except ValueError as x: return ('excepcion', 'estructura', str(x))
    hay_nl = any(S._bn(t) == 'NewLine' for t, _ in S._atoms(tok))
    modo = 'exacto'
    if creador and '\n' in tok and not hay_nl: modo = 'libre'
    elif creador and hay_nl and '\n' not in tok and all(S._bn(t) == 'NewLine' for t, _ in S._atoms(tok)) and not any('\n' in x for x in ([es] if isinstance(es, str) else es)): modo = 'libre_nl'
    d = diag if diag is not None else {}
    d['macros'] = no_ok(s); d['antes'] = s; d['creador'] = creador
    d['diario'] = bool(clave) and re.search(r'_(?:SEQ|TODO)_\d+$', clave) is not None
    try:
        nuevo, ca, cn, info = reflujar_cadena(s, tok, W, modo, d)
    except Exc as x:
        return ('excepcion', x.motivo, x.detalle)
    info['modo'] = modo
    for _ in range(4):   # punto fijo: el resultado se vuelve a pasar por el algoritmo hasta que no cambie (idempotencia)
        if nuevo == s: break
        try: n2, _c, cn2, info2 = reflujar_cadena(nuevo, tok, W, modo, {'k': d.get('k'), 'creador': creador, 'diario': d.get('diario')})
        except Exc: break
        if n2 == nuevo: break
        nuevo, cn = n2, cn2; info = dict(info2, modo=modo, pag=info.get('pag') or info2.get('pag'))
    d['despues'] = nuevo
    if nuevo == s or (ca != INF and ca - cn <= MARGEN): info['coste'] = (ca, cn); return ('ya_correcta', None, info)
    if not invariante(s, nuevo): return ('excepcion', 'invariante', 'el texto cambia')
    if not info.get('pag') and not lineas_ok(nuevo, W): return ('excepcion', 'no_cabe', 'linea > %d tras reflujo' % W)
    if lista:
        try:
            nes = partir_lista(S.renumerar_newlines(nuevo, tok), seps)
        except ValueError as x: return ('excepcion', 'estructura', str(x))
    else: nes = nuevo
    if nes == es: return ('ya_correcta', None, info)
    e2 = dict(e); e2['es'] = nes
    try: C.evaluar_cadena(text, raw, e2)
    except C.Rechazo as r: return ('excepcion', 'rechazo_' + r.motivo, r.detalle)
    info['coste'] = (ca, cn)
    return ('cambiada', nes, info)

# ---------------------------------------------------------------- hojas
def hojas_de_familia(root, fam):
    if fam == 'quest' or fam == 'cut_scene':
        base = os.path.join(root, 'traducciones', fam)
        out = []
        for p in sorted(glob.glob(os.path.join(base, '**', '*.jsonl'), recursive=True)):
            out.append(os.path.relpath(p, os.path.join(root, 'traducciones'))[:-6])
        return out
    return [fam] if os.path.exists(os.path.join(root, 'traducciones', fam + '.jsonl')) else []

def mostrar(es):
    return es if isinstance(es, str) else ' | '.join(es)

CORTES = collections.defaultdict(collections.Counter)   # clase de los cortes antes/despues (todas las celdas en alcance y solo las cambiadas)

def clasificar_cortes(s):
    """-> Counter de la clase de cada salto de linea explicito de la cadena tokenizada: fuerte (. ! ? … ; :), coma, conj (antes de conjuncion/relativo), malo (tras articulo,
    preposicion, clitico, auxiliar, abrir signo, dentro de «», nombre propio multipalabra), medio (otro corte a media frase)"""
    out = collections.Counter()
    ls = [pantalla(x).strip() for x in partir_lineas(s[prefijo_len(s):])]
    prof = 0
    for i, l in enumerate(ls):
        prof += l.count('«') - l.count('»')
        if i + 1 >= len(ls) or not l or not ls[i + 1]: continue
        sig = ls[i + 1]; w = l.split(' ')[-1]; ns = sig.split(' ')[0]; b = base_palabra(w)
        if FIN_FRASE.search(w) or FIN_CLAUS.search(w): c = 'fuerte'
        elif FIN_COMA.search(w): c = 'coma'
        elif base_palabra(ns) in CONJ and b not in ART and b not in PREP: c = 'conj'
        elif b in ART or b in PREP or b in CLIT or b in AUXI or w.endswith(APERT) or prof > 0 or (w[:1].isupper() and ns[:1].isupper()): c = 'malo'
        else: c = 'medio'
        out[c] += 1
    return out

REGS = []   # resultados de celdas paginadas / con macros (para el informe)

SEL = []   # --solo-incumplen: (fam, hoja, row, col, resultado, motivo, v_antes, v_despues, coste)

def lineas_reales(s):
    """lineas de pantalla tras la envoltura voraz del juego a CFG.ancho_max columnas dentro de cada linea explicita (el prefijo (-Nombre-) no cuenta)"""
    out = []
    for piece in partir_lineas(s[prefijo_len(s):]): out.extend(pieza_lineas(pantalla(piece), CFG.ancho_max))
    return out

def huerfana_real(s):
    """True si la cadena abre mas de una ventana (4 lineas reales) y la ultima tiene 1 sola linea o <= 2 palabras"""
    try: L = lineas_reales(s)
    except Exception: return False
    n = len(L)
    if n <= VENT_MAX: return False
    ult = L[-(n % VENT or VENT):]
    return len(ult) == 1 or sum(len(x.split()) for x in ult) <= 2

def violaciones(s):
    """--solo-incumplen: ventana final huerfana REAL (envoltura del juego a ancho_max; ver huerfana_real) + ultima linea < 10 caracteres cuando hay >= 2 lineas.
    Las lineas explicitas > ancho_max NO cuentan: el juego las envuelve solo (se informan aparte en desglose)."""
    try: L = lineas_reales(s)
    except Exception: return 0
    v = 1 if huerfana_real(s) else 0
    if not v and len(L) >= 2 and len(L[-1]) < 10: v += 1
    return v

def desglose(s):
    """-> (lineas explicitas > ancho_max [informativo], ventanas > maxwin, ultima ventana huerfana real)"""
    try: lv = lineas_vis(s); n = len(lineas_reales(s))
    except Exception: return (0, 0, 0)
    return (sum(1 for w in lv if w > CFG.ancho_max), 1 if -(-n // VENT) > CFG.maxwin else 0, 1 if huerfana_real(s) else 0)

def procesar_hoja(root, hoja, fam, W, dry, st, exc, cambios, filtro_claves=None):
    ja = G.leer_ja(root, hoja)
    path = os.path.join(root, 'traducciones', hoja + '.jsonl')
    if ja is None or not os.path.exists(path): st[fam]['hoja_sin_ja'] += 1; return
    with open(path, encoding='utf-8') as f: lineas = f.read().split('\n')
    fin_nl = bool(lineas) and lineas[-1] == ''
    if fin_nl: lineas.pop()
    ultima = {}
    for n, l in enumerate(lineas):
        if l.strip(): j = json.loads(l); ultima[(j['row'], j.get('sub'), j['col'])] = n
    cam = 0; creador = fam == 'Lobby'
    for n, l in enumerate(lineas):
        if not l.strip(): continue
        e = json.loads(l); k = (e['row'], e.get('sub'), e['col'])
        if ultima.get(k) != n: continue
        if e.get('origen') not in C.ORIGENES_VALIDOS or e.get('estado') != 'traducida' or k not in ja: st[fam]['fuera_alcance'] += 1; continue
        es = e['es']
        if not (isinstance(es, str) or (isinstance(es, list) and all(isinstance(x, str) for x in es))): st[fam]['tipo_es'] += 1; continue
        text, raw = ja[k]
        d = {}; clave = ja.get((k[0], k[1], 0), ('', None))[0] if k[2] != 0 else ''
        try: res, a, b = procesar_celda(text, raw, e, W, creador, clave, d)
        except Exception as x:   # fallo inesperado: no se toca
            res, a, b = 'excepcion', 'error_interno', '%s: %s' % (type(x).__name__, x)
        if res == 'sin_saltos': st[fam]['sin_saltos'] += 1; continue
        if CFG.solo:
            s0 = d.get('antes')
            if s0 is None: v0 = None
            else: v0 = violaciones(s0)
            if v0 is None:
                if res == 'excepcion': st[fam]['solo_no_evaluable'] += 1
                continue
            d0 = desglose(s0); fin0 = d0
            if v0 == 0: st[fam]['solo_cumple'] += 1; continue
            st[fam]['solo_incumplia'] += 1
            for i_, nm_ in enumerate(('long', 'vent', 'huerf')): st[fam]['ant_' + nm_] += d0[i_]
            if res == 'cambiada':
                v1 = violaciones(d.get('despues') or s0); ca_, cn_ = (b.get('coste') or (None, None))
                peor = ca_ is not None and ca_ != INF and cn_ > ca_
                if v1 >= v0 or peor:
                    for i_, nm_ in enumerate(('long', 'vent', 'huerf')): st[fam]['des_' + nm_] += d0[i_]
                    SEL.append((fam, hoja, k[0], k[2], 'sigue', 'sin_mejora' if v1 >= v0 else 'empeora_coste', v0, v1, b.get('coste'))); st[fam]['solo_sigue'] += 1; continue
                d1 = desglose(d.get('despues') or s0)
                for i_, nm_ in enumerate(('long', 'vent', 'huerf')): st[fam]['des_' + nm_] += d1[i_]
                SEL.append((fam, hoja, k[0], k[2], 'arreglada' if v1 == 0 else 'mejorada', '', v0, v1, b.get('coste'))); st[fam]['solo_arreglada' if v1 == 0 else 'solo_mejorada'] += 1
            else:
                for i_, nm_ in enumerate(('long', 'vent', 'huerf')): st[fam]['des_' + nm_] += d0[i_]
                SEL.append((fam, hoja, k[0], k[2], 'sigue', (a if res == 'excepcion' else 'ya_correcta_por_metrica'), v0, v0, None)); st[fam]['solo_sigue'] += 1; continue
        st[fam]['en_alcance'] += 1
        if res in ('cambiada', 'ya_correcta') and d.get('antes') is not None:
            fin_ = d.get('despues') if res == 'cambiada' else d['antes']
            CORTES['antes'].update(clasificar_cortes(d['antes'])); CORTES['despues'].update(clasificar_cortes(fin_))
            if res == 'cambiada': CORTES['cam_antes'].update(clasificar_cortes(d['antes'])); CORTES['cam_despues'].update(clasificar_cortes(fin_))
        if d.get('pag') or d.get('macros'):
            etiqueta = {'cambiada': 'cambiada', 'ya_correcta': 'ya_ok'}.get(res, 'exc_' + str(a))
            if d.get('pag'): st[fam]['p_' + etiqueta] += 1
            if d.get('macros'): st[fam]['m_' + etiqueta] += 1
            nuevo_s = d.get('despues') if res != 'excepcion' else None
            REGS.append({'fam': fam, 'hoja': hoja, 'row': k[0], 'col': k[2], 'res': etiqueta, 'pag': bool(d.get('pag')), 'macros': bool(d.get('macros')), 'k': d.get('k', 0), 'diario': bool(d.get('diario')),
                         'antes': d.get('antes'), 'despues': nuevo_s if res == 'cambiada' else d.get('antes'), 'W': W})
        if res == 'ya_correcta':
            st[fam]['ya_correcta'] += 1
            if isinstance(b, dict) and b.get('lineas', 0) > 3 and fam != 'Lobby': st[fam]['ya_correctas_mas_de_3_lineas'] += 1
            continue
        if res == 'excepcion':
            st[fam]['exc_' + a] += 1; st[fam]['excepciones'] += 1
            exc.append((fam, hoja, k[0], '' if k[1] is None else k[1], k[2], a, str(b).replace('\t', ' ').replace('\n', ' ')[:200]))
            continue
        st[fam]['cambiada'] += 1; cam += 1
        if b.get('lineas', 0) > 3 and fam != 'Lobby': st[fam]['cambiadas_mas_de_3_lineas'] += 1
        info = b
        cambios.append({'fam': fam, 'hoja': hoja, 'k': k, 'antes': es, 'despues': a, 'info': info, 'ntrozos': len(es) if isinstance(es, list) else 0})
        e2 = dict(e); e2['es'] = a
        lineas[n] = json.dumps(e2, ensure_ascii=False, separators=(',', ':'))
    if cam and not dry:
        bak = os.path.join(root, 'trabajo', 'lotes', 'bak'); os.makedirs(bak, exist_ok=True)
        shutil.copy2(path, os.path.join(bak, '%s.%s.reflujo.jsonl' % (hoja.replace('/', '__'), datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))))
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f: f.write('\n'.join(lineas) + ('\n' if fin_nl else ''))
        os.replace(tmp, path)

def elegir_ejemplos(cambios, n, claves):
    """ejemplos deterministas: las claves pedidas + n repartidos (por familia y por k)"""
    out = []; vistos = set()
    for c in cambios:
        id_ = '%s:%d:%d' % (c['hoja'], c['k'][0], c['k'][2])
        if id_ in claves and id_ not in vistos: out.append(c); vistos.add(id_)
    grupos = collections.defaultdict(list)
    for c in cambios:
        tipo = 'color' if re.search(r'<(?:Color|EdgeColor|Icon|Num)', mostrar(c['despues'])) else ''
        grupos[(c['fam'], min(c['ntrozos'], 4), tipo)].append(c)
    claves_g = sorted(grupos); meta = len(out) + n
    if n > 0 and claves_g:
        i = 0
        while len(out) < meta and i < n * 40:
            g = grupos[claves_g[i % len(claves_g)]]; pos = (i // len(claves_g)) * 7919 % len(g)
            c = g[pos]; id_ = '%s:%d:%d' % (c['hoja'], c['k'][0], c['k'][2])
            if id_ not in vistos: out.append(c); vistos.add(id_)
            i += 1
    return out

def formato_ejemplo(c, W_por_fam):
    W = W_por_fam[c['fam']]
    def fmt(x):
        t = x if isinstance(x, str) else '<NewLine>'.join(x)
        ls = re.split(r'\n|<NewLine(?:#[0-9]+)?>', t)
        return '\n'.join('    [%2d] %s' % (vis(l), l) for l in ls)
    s = '### %s  fila %d col %d  (%s, %s, ancho %d)\n' % (c['hoja'], c['k'][0], c['k'][2], c['fam'], ('lista de %d trozos' % c['ntrozos']) if c['ntrozos'] else 'cadena', W)
    s += 'ANTES:\n```\n%s\n```\nDESPUES:\n```\n%s\n```\n' % (fmt(c['antes']), fmt(c['despues']))
    return s

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--familias', default=POR_DEFECTO); ap.add_argument('--ancho-dialogo', type=int, default=58); ap.add_argument('--ancho-creador', type=int, default=49)
    ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--root', default=RAIZ)
    ap.add_argument('--hojas', default='', help='solo hojas cuyo nombre contenga alguna de estas subcadenas (separadas por coma)')
    ap.add_argument('--excepciones', help='TSV de salida con las celdas que no se tocan'); ap.add_argument('--informe', help='Markdown con cifras y ejemplos ANTES/DESPUES')
    ap.add_argument('--ejemplos', type=int, default=0, help='nº de ejemplos repartidos para el informe'); ap.add_argument('--clave', action='append', default=[], help='hoja:row:col a incluir en los ejemplos')
    ap.add_argument('--paginar', action='store_true', help='celdas no_cabe: repartir por ventanas de 3 lineas (el juego pagina solo)')
    ap.add_argument('--macros', action='store_true', help='celdas con macros: congelar los trozos con macros y reflujar los demas')
    ap.add_argument('--solo-incumplen', metavar='TSV', help='solo celdas que hoy incumplen (linea > 61 visibles, >3 lineas, ultima huerfana); acepta el cambio solo si baja el nº de incumplimientos y no empeora el coste; informe TSV')
    ap.add_argument('--max-ventanas', type=int, default=4); ap.add_argument('--simular', action='append', default=[], help='hoja,row,col: imprime las ventanas ANTES/DESPUES y termina')
    ap.add_argument('--informe-paginar', help='Markdown con cifras de paginacion y macros, distribucion de la ultima ventana y 15 ejemplos')
    a = ap.parse_args(argv)
    global MARGEN
    CFG.solo = bool(a.solo_incumplen); del SEL[:]
    if CFG.solo: MARGEN = 0.0
    CFG.paginar = a.paginar; CFG.macros = a.macros; CFG.maxwin = a.max_ventanas; del REGS[:]; CORTES.clear()
    if a.simular: return simular_claves(a)
    fams = [f for f in a.familias.split(',') if f]
    for f in fams:
        if f not in FAMILIAS_TODAS: ap.error('familia desconocida: ' + f)
    W_por_fam = {f: (a.ancho_creador if f == 'Lobby' else a.ancho_dialogo) for f in FAMILIAS_TODAS}
    filtro = [x for x in a.hojas.split(',') if x]
    st = collections.defaultdict(collections.Counter); exc = []; cambios = []
    for fam in fams:
        for hoja in hojas_de_familia(a.root, fam):
            if filtro and not any(x in hoja for x in filtro): continue
            procesar_hoja(a.root, hoja, fam, W_por_fam[fam], a.dry_run, st, exc, cambios)
    tot = collections.Counter()
    for fam in fams:
        c = st[fam]; tot.update(c)
        print('%s (ancho %d)%s: en_alcance %d | cambiadas %d | ya_correctas %d | excepciones %d | sin_saltos %d | fuera_alcance %d' % (
            fam, W_por_fam[fam], ' [dry-run]' if a.dry_run else '', c['en_alcance'], c['cambiada'], c['ya_correcta'], c['excepciones'], c['sin_saltos'], c['fuera_alcance']))
        for m in sorted(x for x in c if x.startswith('exc_')): print('    %s: %d' % (m[4:], c[m]))
        if CFG.solo: print('    DESGLOSE (celdas que incumplian): lineas>61 %d->%d | ventanas>%d %d->%d | ultima huerfana %d->%d' % (c['ant_long'], c['des_long'], CFG.maxwin, c['ant_vent'], c['des_vent'], c['ant_huerf'], c['des_huerf']))
        for m in ('cambiadas_mas_de_3_lineas', 'ya_correctas_mas_de_3_lineas'):
            if c[m]: print('    %s: %d' % (m, c[m]))
    if a.excepciones:
        with open(a.excepciones, 'w', encoding='utf-8', newline='\n') as f:
            f.write('familia\thoja\trow\tsub\tcol\tmotivo\tdetalle\n')
            for r in exc: f.write('\t'.join(str(x) for x in r) + '\n')
    if a.informe:
        ej = elegir_ejemplos(cambios, a.ejemplos, set(a.clave))
        with open(a.informe, 'w', encoding='utf-8', newline='\n') as f:
            f.write('# Reflujo de saltos de linea: cifras y ejemplos\n\nModo: %s. Anchos: dialogo %d, creador %d. Familias: %s.\n\n' % (
                'dry-run' if a.dry_run else 'ESCRITURA', a.ancho_dialogo, a.ancho_creador, ', '.join(fams)))
            f.write('## Cifras por familia\n\n| familia | en alcance | cambiadas | ya correctas | excepciones | sin saltos (no aplicable) |\n|---|---|---|---|---|---|\n')
            for fam in fams:
                c = st[fam]; f.write('| %s | %d | %d | %d | %d | %d |\n' % (fam, c['en_alcance'], c['cambiada'], c['ya_correcta'], c['excepciones'], c['sin_saltos']))
            f.write('\nCeldas de dialogo con un bloque de mas de 3 lineas (estructura del japones, no cambia): cambiadas %d, ya correctas %d.\n' % (sum(st[x]['cambiadas_mas_de_3_lineas'] for x in fams), sum(st[x]['ya_correctas_mas_de_3_lineas'] for x in fams)))
            f.write('\n## Excepciones por motivo\n\n| familia | motivo | celdas |\n|---|---|---|\n')
            for fam in fams:
                c = st[fam]
                for m in sorted(x for x in c if x.startswith('exc_')): f.write('| %s | %s | %d |\n' % (fam, m[4:], c[m]))
            f.write('\n## Ejemplos ANTES/DESPUES (entre corchetes: ancho visible de cada linea)\n\n')
            for c in ej: f.write(formato_ejemplo(c, W_por_fam) + '\n')
    if CFG.solo:
        with open(a.solo_incumplen, 'w', encoding='utf-8', newline='\n') as f:
            f.write('familia\thoja\trow\tcol\tresultado\tmotivo\tviol_antes\tviol_despues\tcoste\n')
            for r in SEL: f.write('\t'.join(str(x) for x in r) + '\n')
        tt = collections.Counter()
        for fam in fams: tt.update(st[fam])
        print('SOLO-INCUMPLEN: incumplian %d | arregladas %d | mejoradas %d | siguen %d | cumplen %d' % (tt['solo_incumplia'], tt['solo_arreglada'], tt['solo_mejorada'], tt['solo_sigue'], tt['solo_cumple']))
    if a.informe_paginar: informe_paginar(a.informe_paginar, st, fams, W_por_fam, a)
    return 0

# ---------------------------------------------------------------- simulacion e informe de paginacion
def familia_de(hoja):
    for f in ('quest', 'cut_scene'):
        if hoja.startswith(f + '/'): return f
    return hoja

def simular_celda(root, hoja, row, col, W):
    """-> texto con las ventanas ANTES y DESPUES de la celda segun la configuracion actual (CFG)"""
    ja = G.leer_ja(root, hoja)
    if ja is None: return 'sin textos/ja/%s' % hoja
    e = None
    with open(os.path.join(root, 'traducciones', hoja + '.jsonl'), encoding='utf-8') as f:
        for l in f:
            if l.strip():
                j = json.loads(l)
                if j['row'] == row and j['col'] == col: e = j
    if e is None or (row, e.get('sub'), col) not in ja: return 'celda no encontrada: %s,%d,%d' % (hoja, row, col)
    text, raw = ja[(row, e.get('sub'), col)]
    clave = ja.get((row, e.get('sub'), 0), ('', None))[0] if col != 0 else ''
    d = {}
    res, a_, b_ = procesar_celda(text, raw, e, W, familia_de(hoja) == 'Lobby', clave, d)
    antes = d.get('antes')
    if antes is None:
        tok = S.tokenize_raw(G.bytes_ja(text, raw)); es = e['es']
        antes = G.recomponer(G.trocear(tok)[1], es) if isinstance(es, list) else es
    despues = G.recomponer(G.trocear(S.tokenize_raw(G.bytes_ja(text, raw)))[1], a_) if res == 'cambiada' and isinstance(a_, list) else (a_ if res == 'cambiada' else antes)
    va = ventanas(antes, W); vd = ventanas(despues, W); ma = metricas(va); md = metricas(vd)
    estado = {'cambiada': 'CAMBIADA', 'ya_correcta': 'SIN CAMBIO (ya correcta)', 'excepcion': 'EXCEPCION: %s (%s)' % (a_, b_), 'sin_saltos': 'sin saltos en el japones (no aplicable)'}[res]
    out = '### %s fila %d col %d  [%s]\nANTES: %d ventanas, %d lineas, ultima ventana %d caracteres\n%s\n\nDESPUES: %d ventanas, %d lineas, ultima ventana %d caracteres\n%s\n' % (
        hoja, row, col, estado, ma['nv'], ma['lineas'], ma['ultima'], texto_ventanas(va, W), md['nv'], md['lineas'], md['ultima'], texto_ventanas(vd, W))
    return out

def simular_claves(a):
    for c in a.simular:
        try: hoja, row, col = c.rsplit(',', 2); row = int(row); col = int(col)
        except ValueError: print('clave mal formada (hoja,row,col): ' + c); continue
        fam = familia_de(hoja)
        print(simular_celda(a.root, hoja, row, col, a.ancho_creador if fam == 'Lobby' else a.ancho_dialogo))
    return 0

CUBOS = ((0, 14), (15, 34), (35, 59), (60, 89), (90, 119), (120, 179), (180, 9999))

def cubo(n):
    for lo, hi in CUBOS:
        if lo <= n <= hi: return '%d-%d' % (lo, hi) if hi < 9999 else '%d+' % lo

def escoger(regs, pred, n):
    c = sorted((r for r in regs if pred(r)), key=lambda r: (r['hoja'], r['row'], r['col']))
    if not c: return []
    paso = max(1, len(c) // n)
    return [c[(i * paso + 7 * i) % len(c)] for i in range(min(n, len(c)))]

def informe_paginar(path, st, fams, W_por_fam, a):
    regs = list(REGS); W = a.ancho_dialogo
    f = open(path, 'w', encoding='utf-8', newline='\n')
    w = lambda x='': f.write(x + '\n')
    w('# Reflujo con paginacion por ventanas y macros (dry-run)\n')
    w('Modo: %s. Ancho dialogo %d, ventana = %d lineas, maximo %d ventanas. --paginar %s, --macros %s. Familias: %s.\n' % ('dry-run' if a.dry_run else 'ESCRITURA', W, VENT, CFG.maxwin, CFG.paginar, CFG.macros, ', '.join(fams)))
    def tabla(titulo, pred, extra=None):
        w('## ' + titulo + '\n')
        w('| familia | celdas | cambiadas | ya correctas (sin cambio) | quedan como excepcion |\n|---|---|---|---|---|')
        motivos = collections.Counter()
        for fam in fams:
            rs = [r for r in regs if r['fam'] == fam and pred(r)]
            c = collections.Counter('exc' if r['res'].startswith('exc_') else r['res'] for r in rs)
            w('| %s | %d | %d | %d | %d |' % (fam, len(rs), c['cambiada'], c['ya_ok'], c['exc']))
            for r in rs:
                if r['res'].startswith('exc_'): motivos[(fam, r['res'][4:])] += 1
        w('\nQuedan por motivo:\n\n| familia | motivo | celdas |\n|---|---|---|')
        for (fam, m), v in sorted(motivos.items()): w('| %s | %s | %d |' % (fam, m, v))
        w()
    tabla('A1. Celdas `no_cabe` sin macros repartidas por ventanas (--paginar)', lambda r: r['pag'] and not r['macros'])
    tabla('A2. Celdas con macros que ademas no cabian (reparto por ventanas)', lambda r: r['pag'] and r['macros'])
    tabla('B1. Celdas con macros (antes `tokens_no_soportados`) resueltas SIN paginar (reflujo normal con trozos congelados)', lambda r: r['macros'] and not r['pag'])
    tabla('B2. Total de celdas con macros (B1 + A2) y excepciones de macros', lambda r: r['macros'])
    # k de las pag
    w('## Calidad de los cortes de linea (saltos explicitos), antes y despues\n')
    w('| conjunto | momento | fuerte (. ! ? … ; :) | coma | antes de conjuncion/relativo | MALO (articulo, preposicion, clitico, auxiliar, «», nombre propio) | medio (otro) | total | % buenos (fuerte+coma+conj) | % malo |\n|---|---|---|---|---|---|---|---|---|---|')
    for nom, ka, kd in (('todas las celdas en alcance', 'antes', 'despues'), ('solo las celdas cambiadas', 'cam_antes', 'cam_despues')):
        for mom, k_ in (('antes', ka), ('despues', kd)):
            c = CORTES[k_]; t = sum(c.values()) or 1
            w('| %s | %s | %d | %d | %d | %d | %d | %d | %.1f | %.1f |' % (nom, mom, c['fuerte'], c['coma'], c['conj'], c['malo'], c['medio'], sum(c.values()), 100.0 * (c['fuerte'] + c['coma'] + c['conj']) / t, 100.0 * c['malo'] / t))
    w()
    w('## Celdas paginadas por k (nº maximo de trozos de un bloque; k=1: sin saltos que mover). Sin las filas del diario de misiones (SEQ/TODO: no usan ventanas de dialogo, %d celdas, motivo diario_sin_ventanas)\n' % sum(1 for r in regs if r['pag'] and r['diario']))
    w('| familia | k | celdas | cambiadas | ya correctas | excepciones |\n|---|---|---|---|---|---|')
    ck = collections.defaultdict(collections.Counter)
    for r in regs:
        if r['pag'] and not r['diario']: ck[(r['fam'], min(r['k'], 3))][r['res'] if not r['res'].startswith('exc_') else 'exc'] += 1
    for (fam, k), c in sorted(ck.items()): w('| %s | %s | %d | %d | %d | %d |' % (fam, '3+' if k == 3 else k, sum(c.values()), c['cambiada'], c['ya_ok'], c['exc']))
    w('\n## Longitud (caracteres) de la ULTIMA ventana, celdas paginadas con 2 o mas ventanas\n')
    antes = collections.Counter(); desp = collections.Counter(); k1 = collections.Counter(); n_a = n_d = 0
    for r in regs:
        if not r['pag'] or r['diario']: continue
        ma = metricas(ventanas(r['antes'], r['W'])); md = metricas(ventanas(r['despues'], r['W']))
        if ma['nv'] >= 2: antes[cubo(ma['ultima'])] += 1; n_a += 1
        if md['nv'] >= 2:
            desp[cubo(md['ultima'])] += 1; n_d += 1
            if r['k'] == 1: k1[cubo(md['ultima'])] += 1
    w('| ultima ventana (car.) | ANTES | DESPUES (todas) | DESPUES (solo k=1) |\n|---|---|---|---|')
    for lo, hi in CUBOS:
        k_ = '%d-%d' % (lo, hi) if hi < 9999 else '%d+' % lo
        w('| %s | %d | %d | %d |' % (k_, antes[k_], desp[k_], k1[k_]))
    w('| total con >= 2 ventanas | %d | %d | %d |' % (n_a, n_d, sum(k1.values())))
    w('\nHuerfana = ultima ventana de menos de %d caracteres (%d %% de una linea de %d). DESPUES incluye las celdas que quedan como excepcion (su texto no se toca: es el ANTES).\n' % (int(MIN_ULT * W), int(MIN_ULT * 100), W))
    w('## 15 ejemplos ANTES / DESPUES (cada caja = una ventana de %d lineas; los macros se muestran como `#` de su ancho estimado)\n' % VENT)
    grupos = (('k=1 (sin saltos que mover)', lambda r: r['pag'] and r['k'] == 1 and not r['macros'] and not r['diario'], 3), ('k=2', lambda r: r['pag'] and r['k'] == 2 and r['res'] == 'cambiada' and not r['macros'], 3),
              ('k>=3', lambda r: r['pag'] and r['k'] >= 3 and r['res'] == 'cambiada' and not r['macros'], 3), ('con macros, cambiadas', lambda r: r['macros'] and r['res'] == 'cambiada', 3),
              ('quedan como excepcion', lambda r: r['pag'] and r['res'].startswith('exc_') and not r['diario'], 3))
    for tit, pred, n in grupos:
        w('### ' + tit + '\n')
        for r in escoger(regs, pred, n):
            va = ventanas(r['antes'], r['W']); vd = ventanas(r['despues'], r['W']); ma = metricas(va); md = metricas(vd)
            w('#### %s  fila %d col %d  (%s, k=%s, resultado: %s)\n' % (r['hoja'], r['row'], r['col'], r['fam'], r['k'] or '-', r['res']))
            w('ANTES (%d ventanas, ultima %d car.):\n```\n%s\n```\nDESPUES (%d ventanas, ultima %d car.):\n```\n%s\n```\n' % (ma['nv'], ma['ultima'], texto_ventanas(va, r['W']), md['nv'], md['ultima'], texto_ventanas(vd, r['W'])))
    f.close()

if __name__ == '__main__': sys.exit(main())
