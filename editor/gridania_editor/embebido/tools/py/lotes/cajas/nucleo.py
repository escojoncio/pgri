"""NUCLEO de las CAJAS DE TEXTO: perfiles por (hoja, col), expansion de macros, envoltura del juego, ventanas y deteccion de problemas.
Lo usan `auditar_cajas.py` (lectura) y `corregir_cajas.py` (correccion). Solo biblioteca estandar + los modulos de tools/py y tools/py/lotes.

Modelo (supuestos del propietario / medidas en pantalla, 2026-11-03):
- Una celda se divide en LINEAS DURAS por NewLine y LF (los del japones). Cada linea dura se expande (macros) y, si la caja envuelve (dialogo, sistema, descripcion),
  el juego la envuelve por palabra al pasar el ancho: la envoltura crea lineas nuevas. Una linea cabe si ancho <= seguro, o si ancho <= duro y termina en puntuacion
  (tolerancia medida: dialogo 58 seguro / 61 duro).
- Ventana = `lineas_ventana` lineas visibles = TOPE duro (dialogo: 4; media/objetivo LINEAS_MEDIA = 3, 4 solo en excepciones); el juego abre ventana nueva al pasar de ese numero.
- Subtitulos (cut_scene/opening): sin caja ni autoajuste; las lineas duras no se envuelven: pasar el tope las saca de pantalla.
- Expansion por macro: <String>/<Split> exp_string car. (nombre de mundo/jugador), <Sheet> exp_sheet, <Num> exp_num, Icon2 = 2.

Problemas: LINEA_EXCEDE, PALABRA_SUELTA, MACRO_NO_CONTADA, SUBTITULO_EXCEDE, CAJA_DESCONOCIDA.
"""
import sys, os, re, csv, json, fnmatch, collections
AQUI = os.path.dirname(os.path.abspath(__file__))
LOTES = os.path.dirname(AQUI); PY = os.path.dirname(LOTES)
for p in (LOTES, PY):
    if p not in sys.path: sys.path.insert(0, p)
import reflujar_lineas as R
import sestring as S, segmentar as G, construir_dat as C

RAIZ = R.RAIZ
PERFILES_TSV = os.path.join(AQUI, 'perfiles_caja.tsv')
TIPOS = ('dialogo', 'sistema', 'subtitulo', 'descripcion', 'hud_fijo', 'guia', 'autoajuste', 'desconocido')
PROBE_DESCONOCIDA = 46      # = menor ancho medido (sistema, 48) - 2: una linea mas ancha en caja desconocida se avisa
LINEAS_MEDIA = 3   # objetivo de lineas por ventana de dialogo (el tope duro es lineas_ventana = 4)
PESOS = {'PALABRA_SUELTA': 3, 'MACRO_NO_CONTADA': 3, 'SUBTITULO_EXCEDE': 3, 'ALTO_EXCEDE': 3, 'LINEA_EXCEDE': 1, 'CAJA_DESCONOCIDA': 0, 'FR_EXCEDE': 0}
PUNT = re.compile(r'[.,;:!?…»”\)]$')
GEN_RE = re.compile(r'<Gender>(.*?)<GenderElse>(.*?)<GenderEnd>', re.S)
NUM_RE = re.compile(r'<(?:Num|Kilo)(?:#\d+)?>')
ICON_RE = re.compile(r'<Icon2(?:#\d+)?>')
SEQ_TODO = re.compile(r'_(?:SEQ|TODO)_\d+$')


class Perfil(object):
    __slots__ = ('patron', 'col', 'filas', 'clave_re', 'tipo', 'seguro', 'duro', 'lineas', 'exp_string', 'exp_num', 'exp_sheet', 'fuente', 'nota', 'fr_ref', 'fr_rel')
    def __init__(self, **kw):
        for k in self.__slots__: setattr(self, k, kw.get(k))
    @property
    def conocido(self): return self.tipo in ('dialogo', 'sistema', 'subtitulo', 'descripcion', 'hud_fijo', 'guia') and bool(self.seguro)
    @property
    def envuelve(self): return self.tipo in ('dialogo', 'sistema', 'descripcion', 'guia')
    def __repr__(self): return 'Perfil(%s,%s,%s,%s/%s,%s)' % (self.patron, self.col, self.tipo, self.seguro, self.duro, self.fuente)


def _int(x, d=0):
    x = (x or '').strip()
    return int(x) if x.lstrip('-').isdigit() else d


def cargar_perfiles(path=PERFILES_TSV):
    out = []
    with open(path, encoding='utf-8', newline='') as f:
        rd = csv.DictReader((l for l in f if l.strip() and not l.startswith('#')), delimiter='\t')
        for r in rd:
            filas = set(int(x) for x in r['filas'].split(',') if x.strip().isdigit()) if r.get('filas') else None
            out.append(Perfil(patron=r['patron'], col=(None if r['col'] in ('*', '') else int(r['col'])), filas=filas,
                              clave_re=re.compile(r['clave_re']) if r.get('clave_re') else None, tipo=r['tipo'],
                              seguro=_int(r['ancho_seguro']), duro=_int(r['ancho_duro']) or _int(r['ancho_seguro']), lineas=_int(r['lineas_ventana']),
                              exp_string=_int(r['exp_string'], 12), exp_num=_int(r['exp_num'], 4), exp_sheet=_int(r['exp_sheet'], 16),
                              fuente=r['fuente'], nota=r.get('nota', ''), fr_ref=_int(r.get('fr_ref')), fr_rel=_int(r.get('fr_rel'))))
    for p in out: assert p.tipo in TIPOS, p
    return out


DESCONOCIDO = Perfil(patron='*', col=None, filas=None, clave_re=None, tipo='desconocido', seguro=0, duro=0, lineas=0, exp_string=12, exp_num=4, exp_sheet=16, fuente='desconocido', nota='sin perfil', fr_ref=0, fr_rel=0)


class Perfiles(object):
    def __init__(self, path=PERFILES_TSV):
        self.lista = cargar_perfiles(path); self._c = {}
    def candidatos(self, hoja, col):
        k = (hoja, col)
        if k not in self._c: self._c[k] = [p for p in self.lista if (p.col is None or p.col == col) and fnmatch.fnmatchcase(hoja, p.patron)]
        return self._c[k]
    def de(self, hoja, col, row=None, clave=None):
        for p in self.candidatos(hoja, col):
            if p.filas is not None and row not in p.filas: continue
            if p.clave_re is not None and not (clave is not None and p.clave_re.search(clave)): continue
            return p
        return DESCONOCIDO
    def necesita_clave(self, hoja, col):
        return any(p.clave_re is not None for p in self.candidatos(hoja, col))


# ---------------------------------------------------------------- expansion y layout
def _pantalla(t, pf, expandir):
    """texto de pantalla de una LINEA DURA (cadena tokenizada) -> str. expandir=False: macros de texto/numero cuentan 0 (lo que ve un conteo ingenuo)."""
    t = GEN_RE.sub(lambda m: m.group(1) if len(m.group(1)) >= len(m.group(2)) else m.group(2), t)   # macro de genero: rama mas ancha
    t = NUM_RE.sub('N' * pf.exp_num if expandir else '', t)
    t = ICON_RE.sub('##' if expandir else '', t)
    if not R.no_ok(t): return R.plano(t)
    old = (R.ANCHO_NOMBRE, R.ANCHO_SHEET)
    R.ANCHO_NOMBRE = pf.exp_string if expandir else 0; R.ANCHO_SHEET = pf.exp_sheet if expandir else 0
    try: return R.analizar(t)[1]
    except Exception: return R.plano(t)
    finally: R.ANCHO_NOMBRE, R.ANCHO_SHEET = old


def cabe(w, txt, pf):
    """una linea (ancho w, texto txt) cabe en la caja del perfil"""
    if w <= pf.seguro: return True
    return w <= pf.duro and bool(PUNT.search(txt.rstrip()))


def envolver(txt, pf):
    """envoltura del juego (voraz por palabra) de una linea dura -> lista de lineas. Una palabra mas ancha que la caja se queda sola."""
    if txt == '' or not pf.envuelve or not pf.seguro: return [txt]
    ws = re.split(r' (?! )', txt); out = []; cur = None
    for w in ws:
        if cur is None: cur = w; continue
        n = len(cur) + 1 + len(w)
        if n <= pf.seguro or (n <= pf.duro and PUNT.search(w)): cur += ' ' + w
        else: out.append(cur); cur = w
    out.append(cur); return out


class Layout(object):
    """duras: [(ancho_expandido, ancho_sin_expandir, texto_expandido)]; lineas: [(texto, indice_duro, creada_por_envoltura)]; ventanas: lista de listas de textos"""
    __slots__ = ('duras', 'lineas', 'ventanas', 'macros')


def disenar(s, pf):
    """s = cadena tokenizada del es (con NewLine/LF). -> Layout"""
    s = s[R.prefijo_len(s):]
    L = Layout(); L.duras = []; L.lineas = []; L.macros = R.no_ok(s) or bool(NUM_RE.search(s)) or bool(GEN_RE.search(s))
    for i, piece in enumerate(R.partir_lineas(s)):
        txt = _pantalla(piece, pf, True)
        sin = _pantalla(piece, pf, False) if L.macros else txt
        L.duras.append((len(txt), len(sin), txt))
        ls = envolver(txt, pf)
        for j, l in enumerate(ls): L.lineas.append((l, i, j > 0))
    if pf.lineas and pf.envuelve:
        L.ventanas = [[l for l, _, _ in L.lineas[k:k + pf.lineas]] for k in range(0, len(L.lineas), pf.lineas)]
    else: L.ventanas = [[l for l, _, _ in L.lineas]]
    return L


# ---------------------------------------------------------------- criterio RELATIVO AL FRANCES de los subtitulos (sin recuadro)
FR_REL_MIN = 42      # (sin uso; el suelo es el ancho seguro del perfil, 58)
FR_REL_MAX = 90      # 95 sale cortada (medido): el fr de 150-300 car. no es base fiable por encima de esto


def tope_ancho_subtitulo(pf, fr=None):
    """ancho maximo de una linea de subtitulo: perfil fr_rel + fr medido -> min(90, max(fr_ancho, 58)); sin base (fr ausente o sin texto) o perfil absoluto -> pf.seguro (58)"""
    if pf.fr_rel and fr and fr.get('ancho'): return min(FR_REL_MAX, max(fr['ancho'], pf.seguro))
    return pf.seguro


def tope_lineas_subtitulo(pf, fr):
    """lineas no vacias maximas: max(lineas del fr, lineas del japones, 3) (el nº de trozos lo fija el japones)"""
    return max(fr.get('lineas', 0), fr.get('ja_lineas', 0), 3)


def lineas_ja(text):
    """nº de lineas no vacias del volcado ja (cortes {0x10:} y LF)"""
    return sum(1 for seg in FR_HARD.split(text or '') if FR_TAG.sub('', FR_MARK.sub('', seg)).strip())


def _pal(txt): return len([x for x in txt.split() if x])


def problemas(s, pf, fr=None):
    """-> (lista de codigos con repeticion, Layout). Codigos: ver cabecera."""
    if not (pf.conocido or pf.tipo == 'desconocido'): return [], None
    L = disenar(s, pf); out = []
    if pf.tipo == 'desconocido':
        if any(w > PROBE_DESCONOCIDA for w, _, _ in L.duras): out.append('CAJA_DESCONOCIDA')
        return out, L
    for w, ws, txt in L.duras:
        if pf.tipo == 'subtitulo':
            if w > tope_ancho_subtitulo(pf, fr): out.append('SUBTITULO_EXCEDE')
        elif not cabe(w, txt, pf):
            # solo la expansion de macros la saca de la caja -> MACRO_NO_CONTADA; si ya sobra sin expandir -> LINEA_EXCEDE
            out.append('MACRO_NO_CONTADA' if cabe(ws, txt, pf) else 'LINEA_EXCEDE')
    if pf.tipo == 'subtitulo' and pf.lineas and len(L.duras) > pf.lineas: out.append('SUBTITULO_EXCEDE')
    if pf.tipo == 'subtitulo' and pf.fr_rel and fr is not None and sum(1 for w, _, _ in L.duras if w) > tope_lineas_subtitulo(pf, fr): out.append('SUBTITULO_EXCEDE')
    if pf.envuelve:
        ya = False
        # (a) ultima linea creada por la envoltura con <= 2 palabras
        for i in range(len(L.duras)):
            ls = [l for l, d, _ in L.lineas if d == i]
            if len(ls) >= 2 and _pal(ls[-1]) <= 2: out.append('PALABRA_SUELTA'); ya = True
        # (b) ventana final con <= 2 palabras (>= 2 ventanas)
        if pf.lineas and len(L.ventanas) >= 2 and _pal(' '.join(L.ventanas[-1])) <= 2: out.append('PALABRA_SUELTA'); ya = True
        # (c) ultima linea de la celda corta (< 10 car., <= 2 palabras) con >= 2 lineas
        if not ya and pf.tipo != 'guia' and len(L.lineas) >= 2 and len(L.lineas[-1][0].strip()) < 10 and _pal(L.lineas[-1][0]) <= 2: out.append('PALABRA_SUELTA')
    if fr and pf.fr_ref and not R.no_ok(s[R.prefijo_len(s):]):   # con macros If/Run/Sheet el fr no es comparable (las ramas van dentro de {0x..})
        # altura: nº de lineas tras la envoltura > lineas del frances de la MISMA celda (mismo modelo de envoltura) -> sale por debajo de la caja
        if pf.envuelve and len(L.lineas) > max(fr['lineas'], 3): out.append('ALTO_EXCEDE')
        aes = max((w for w, _, _ in L.duras), default=0)
        if aes > fr['ancho'] * 1.25 and aes - fr['ancho'] >= 6: out.append('FR_EXCEDE')
    return out, L


def puntuacion(cods):
    return sum(PESOS.get(c, 0) for c in cods)


# ---------------------------------------------------------------- frances de referencia (cajas de tamaño variable: Addon, HUD)
FR_HARD = re.compile(r'\n|\{0x10:\}')
FR_MARK = re.compile(r'\{0x[0-9A-Fa-f]+:[^}]*\}')
FR_TAG = re.compile(r'<[^>]*>')


def leer_fr(root, hoja):
    base = os.path.join(root, 'textos', 'fr', hoja)
    paths = [base + '.jsonl'] if os.path.exists(base + '.jsonl') else []
    n = 1
    while os.path.exists('%s_part%02d.jsonl' % (base, n)): paths.append('%s_part%02d.jsonl' % (base, n)); n += 1
    res = {}
    for p in paths:
        with open(p, encoding='utf-8') as f:
            for l in f:
                if l.strip():
                    j = json.loads(l); res[(j['row'], j['sub'], j['col'])] = j['text']
    return res


def medida_fr(text, pf):
    """texto fr del volcado -> dict(lineas, ancho, largo): lineas tras envolver cada segmento duro al ancho del perfil; ancho = segmento mas largo; largo = caracteres"""
    t = text.replace('{0x1D:}', ' '); n = 0; mx = 0; tot = 0
    for seg in FR_HARD.split(t):
        seg = FR_TAG.sub('', FR_MARK.sub('', seg)).replace('\u00ad', '').replace('\u00a0', ' ').strip()
        if not seg: continue
        mx = max(mx, len(seg)); tot += len(seg); n += len(envolver(seg, pf))
    return dict(lineas=max(n, 1), ancho=mx, largo=tot) if tot else None


# ---------------------------------------------------------------- celdas
def cadena_tokenizada(es, ja_text, ja_raw):
    """es (str o lista de trozos) + volcado ja -> cadena tokenizada completa (None si no se puede)"""
    if isinstance(es, str): return es
    if len(es) == 1: return G.escapar(es[0])
    try:
        tok = S.tokenize_raw(G.bytes_ja(ja_text, ja_raw))
        tr, seps = G.trocear(tok)
        return G.recomponer(seps, es)
    except Exception:
        return None


def leer_es(root, hoja):
    """traducciones/<hoja>.jsonl -> [(row, sub, col, es, origen)] con la ULTIMA linea de cada clave; solo estado traducida y origen valido (lo que entra en el .dat)"""
    path = os.path.join(root, 'traducciones', hoja + '.jsonl'); ult = {}
    if not os.path.exists(path): return []
    with open(path, encoding='utf-8') as f:
        for l in f:
            if not l.strip(): continue
            j = json.loads(l); ult[(j['row'], j.get('sub'), j['col'])] = j
    out = []
    for k, j in ult.items():
        if j.get('estado') != 'traducida' or j.get('origen') not in C.ORIGENES_VALIDOS: continue
        es = j['es']
        if not (isinstance(es, str) or (isinstance(es, list) and all(isinstance(x, str) for x in es))): continue
        out.append((k[0], k[1], k[2], es, j.get('origen')))
    out.sort(key=lambda x: (x[0], -1 if x[1] is None else x[1], x[2]))
    return out


def listar_hojas(root):
    base = os.path.join(root, 'traducciones'); out = []
    for dp, dn, fn in os.walk(base):
        for n in fn:
            if n.endswith('.jsonl'): out.append(os.path.relpath(os.path.join(dp, n), base)[:-6])
    return sorted(out)


def total_crudo(es):
    return sum(len(x) for x in ([es] if isinstance(es, str) else es))


def tiene_saltos_o_macros(es):
    return any(('\n' in x or '<' in x) for x in ([es] if isinstance(es, str) else es))


def evaluar_hoja(root, hoja, perfiles, ja_cache=None, cb=None):
    """-> (stats, filas). filas = [dict(row,sub,col,tipo,fuente,problemas,ancho_max,lineas,ventanas,es)] SOLO celdas con problema.
    stats = Counter: celdas, evaluadas, omitidas_cortas, sin_ja, por tipo de caja y por codigo (celdas con el codigo)."""
    st = collections.Counter(); filas = []
    cel = leer_es(root, hoja)
    if not cel: return st, filas
    ja = None; frd = None
    for row, sub, col, es, origen in cel:
        st['celdas'] += 1
        clave = None
        if perfiles.necesita_clave(hoja, col):
            if ja is None: ja = G.leer_ja(root, hoja) or {}
            clave = ja.get((row, sub, 0), ('', None))[0]
        pf = perfiles.de(hoja, col, row, clave)
        st['tipo_' + pf.tipo] += 1
        if pf.tipo == 'autoajuste': continue
        lim = pf.seguro if pf.conocido else PROBE_DESCONOCIDA
        if not pf.fr_ref and not pf.fr_rel and total_crudo(es) <= lim and (isinstance(es, str) or len(es) <= 1 or not pf.envuelve): st['omitidas_cortas'] += 1; continue
        if isinstance(es, list) and len(es) > 1:
            if ja is None: ja = G.leer_ja(root, hoja) or {}
            t = ja.get((row, sub, col))
            if t is None: st['sin_ja'] += 1; continue
            s = cadena_tokenizada(es, t[0], t[1])
        else: s = cadena_tokenizada(es, None, None)
        if s is None: st['sin_ja'] += 1; continue
        st['evaluadas'] += 1
        fr = None
        if pf.fr_ref or pf.fr_rel:
            if frd is None: frd = leer_fr(root, hoja)
            if (row, sub, col) in frd: fr = medida_fr(frd[(row, sub, col)], pf)
        if pf.fr_rel:
            if ja is None: ja = G.leer_ja(root, hoja) or {}
            tj = ja.get((row, sub, col))
            fr = dict(fr or dict(lineas=0, ancho=0, largo=0)); fr['ja_lineas'] = lineas_ja(tj[0]) if tj else 0
        cods, L = problemas(s, pf, fr)
        if not cods: continue
        if set(cods) - {'FR_EXCEDE'}: st['con_problema'] += 1
        for c in set(cods): st['c_' + c] += 1
        filas.append(dict(row=row, sub=sub, col=col, tipo=pf.tipo, fuente=pf.fuente, problemas=cods,
                          ancho_max=max((w for w, _, _ in L.duras), default=0), lineas=len(L.lineas), ventanas=len(L.ventanas), origen=origen, fr_lineas=fr['lineas'] if fr else '', fr_ancho=fr['ancho'] if fr else '', es_largo=total_crudo(es), fr_largo=fr['largo'] if fr else '',
                          es=(es if isinstance(es, str) else ' || '.join(es))))
    return st, filas
