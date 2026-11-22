#!/usr/bin/env -S python3 -I
"""Auditoria de SIMBOLOGIA ja<->es sobre la CELDA COMPLETA (trozos unidos en orden; solo lectura de traducciones/).
OBJETIVAS (gravedad alta) -> trabajo/informes/simbologia_objetiva.tsv:
  EXCL_BAL     ¡ y ! desbalanceados (recorrido en pila sobre la celda entera)
  INTER_BAL    ¿ y ? desbalanceados
  PAREN_BAL    ( ) desbalanceados (se ignoran enumeraciones «1)», «a)»)
  COMILLAS_BAL « » / “ ” desbalanceadas o " impar
  CONTEO_MULTI el ja lleva signos agrupados (!! ?? !? ‼ ⁉) y el es no lleva el mismo nº de ! y ? en la racha correspondiente
SUBJETIVAS (gravedad baja) -> simbologia_subjetiva.tsv:
  PUNTOS_SUSP COMILLAS_N ALARGA_FALTA TILDE_ONDA ESTRELLA NOTA_MUSICAL CORAZON RAYA_FALTA INTER_N EXCL_N PAREN_N
Se enmascaran (misma longitud) macros, prefijo (-Nombre-), URLs, comandos /xxx y glifos PUA.
`reparar(raw_trozos, ja)` devuelve los trozos corregidos SOLO con arreglos inequivocos (usado por corregir_simbologia.py).
Uso: python3 -I tools/py/lotes/auditar_simbologia.py [--hojas SUB,...] [--raiz R] [--salida-dir D]"""
import argparse, collections, json, os, re, sys
AQUI = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, AQUI)
import detectar_cohesion as DC

RAIZ = os.path.abspath(os.path.join(AQUI, '..', '..', '..'))
RE_IGN = re.compile(r'https?://\S+|(?<![\w/])/[A-Za-z]+|[-]')
RE_PUA = re.compile(r'[-]')
RE_TRANSP = re.compile(r'color|italic|emphasis|macroend|bold|shadow', re.I)
RE_BLOQUE = re.compile(r'<(?:Sheet|Payload)\w*(?:#\d+)?>.*?<MacroEnd(?:#\d+)?>', re.S)
RE_RAW = re.compile(r'<Raw(?:#\d+)?>[^<]*')
RE_RAMAS = re.compile(r'<(Gender|If|Switch)\b', re.I)
OBJ = ('EXCL_BAL', 'INTER_BAL', 'PAREN_BAL', 'COMILLAS_BAL', 'CONTEO_MULTI')
TERM = '.!?…'

def _rep(m, ch): return ch * len(m.group(0))

def enmascarar(t):
    """trozo es crudo -> cadena de igual longitud: macros \\x01 (palabra) / \\x02 (transparente) / ' ' (NewLine); prefijo, URLs, comandos y PUA -> \\x01"""
    t = t or ''
    pm = DC.RE_PREF.match(t)
    if pm: t = ' ' * len(pm.group(0)) + t[pm.end():]
    def tok(m):
        x = m.group(0)
        if re.search('newline', x, re.I) or x.lower().startswith('{0x10'): return ' ' * len(x)
        return ('\x02' if RE_TRANSP.search(x) else '\x01') * len(x)
    t = RE_BLOQUE.sub(lambda m: '\x01' * len(m.group(0)), t)   # macro de referencia <Sheet>..<MacroEnd>: su payload <Raw> puede ser ASCII ( ) " « »
    t = RE_RAW.sub(lambda m: '\x01' * len(m.group(0)), t)
    t = DC.RE_TOK.sub(tok, t)
    return RE_IGN.sub(lambda m: _rep(m, '\x01'), t)

def limpia_ja(t): return RE_IGN.sub(' ', RE_RAW.sub(' ', RE_BLOQUE.sub(' ', re.sub(r'^\(-[^)]*-\)', '', t or ''))))   # los bloques <Sheet>..<MacroEnd> (payload <Raw> con ! ? ( ) de relleno) no cuentan, igual que en el es   # el prefijo (-Nombre-)/(-？？？？-) del ja no cuenta (como en el es)

def unir(masc):
    """-> (T, inicios) T = trozos enmascarados unidos con ' '"""
    ini = []; p = 0
    for m in masc: ini.append(p); p += len(m) + 1
    return ' '.join(masc), ini

def a_trozo(ini, masc, pos):
    """posicion en T -> (trozo, offset); si cae en el separador, inicio del siguiente"""
    for i in range(len(masc) - 1, -1, -1):
        if pos >= ini[i]: return (i, min(pos - ini[i], len(masc[i])))
    return (0, 0)

# ---------- balance ----------
def pila(T, ab, ce, ignorar=None):
    """-> (cierres sin apertura [pos], aperturas sin cierre [pos], pares [(a,c)])"""
    st = []; sc = []; pares = []
    for i, ch in enumerate(T):
        if ch == ab: st.append(i)
        elif ch == ce:
            if ignorar and not st and ignorar(T, i): continue   # enumeracion «1)» solo si no hay apertura abierta
            if st: pares.append((st.pop(), i))
            else: sc.append(i)
    return sc, st, pares

def _enum(T, i):   # «1)» «a)» al inicio de palabra
    return i >= 1 and T[i - 1].isalnum() and (i == 1 or not (T[i - 2].isalnum() or T[i - 2] == '('))   # «(1)» NO es enumeracion

def balances(T):
    r = {}
    r['!'] = pila(T, '¡', '!'); r['?'] = pila(T, '¿', '?')
    r['('] = pila(T, '(', ')', _enum)
    c1 = pila(T, '«', '»'); c2 = pila(T, '“', '”')
    r['«'] = c1; r['“'] = c2
    return r

def tipos_bal(T):
    b = balances(T); t = []
    if b['!'][0] or b['!'][1]: t.append('EXCL_BAL')
    if b['?'][0] or b['?'][1]: t.append('INTER_BAL')
    if b['('][0] or b['('][1]: t.append('PAREN_BAL')
    if b['«'][0] or b['«'][1] or b['“'][0] or b['“'][1] or T.count('"') % 2: t.append('COMILLAS_BAL')
    return t

# ---------- rachas ----------
RE_RJA = re.compile('[！!？?‼⁉]+')
def _t_ja(s):
    ne = len(re.findall('[！!]', s)) + 2 * s.count('‼') + s.count('⁉')
    nq = len(re.findall('[？?]', s)) + s.count('⁉')
    return (ne, nq)
def rachas_ja(ja): return [(m.group(0), _t_ja(m.group(0))) for m in RE_RJA.finditer(ja)]
def rachas_es(T): return [(m.start(), m.end(), (m.group(0).count('!'), m.group(0).count('?'))) for m in re.finditer(r'[!?]+', T)]

def _placeholder_desconocido(s, tj, te):
    """regla del propietario (2026-11-04): ja «？？？？» (personaje/nombre desconocido) -> es «¿¿??»: n//2 aperturas ¿ y n-n//2 cierres ?.
    Se admite el cierre reducido (n-n//2 «?») en rachas puras de ？ con n>=3 (o n==2: «¿?»)."""
    n = len(s)
    return bool(re.fullmatch('[？?]+', s)) and tj == (0, n) and te == (0, n - n // 2) and n >= 2

def conteo_multi(ja, T):
    """-> (incumple, [(indice_racha_es, n_objetivo, tipo)]) ; los arreglos solo si alineado y racha pura"""
    rj = rachas_ja(ja)
    if not any(len(s) >= 2 for s, _ in rj): return False, []
    re_ = rachas_es(T)
    if len(rj) != len(re_):
        sj = (sum(t[0] for _, t in rj), sum(t[1] for _, t in rj)); se = (sum(x[2][0] for x in re_), sum(x[2][1] for x in re_))
        return sj != se, []
    mal = False; fix = []
    for k, ((s, tj), (a, b, te)) in enumerate(zip(rj, re_)):
        if len(s) < 2 or tj == te: continue
        if _placeholder_desconocido(s, tj, te): continue   # «？？？？» (nombre desconocido) -> «¿¿??» (n//2 aperturas, n-n//2 cierres)
        mal = True
        if (tj[1] == 0 and te[1] == 0 and tj[0] >= 1) : fix.append((k, tj[0], '!'))
        elif (tj[0] == 0 and te[0] == 0 and tj[1] >= 1): fix.append((k, tj[1], '?'))
    return mal, fix

# ---------- subjetivas ----------
def puntos(t):
    """nº de pausas (rachas) de puntos suspensivos: regla RAE 2026-11-05, la racha es de ≤3 puntos y su longitud ya no se compara con el japones"""
    return len(re.findall(r'[…‥]+|[.・]{3,}', t))

def subjetivas(ja, es):
    ja, es = limpia_ja(ja), re.sub('[\x01\x02]', ' ', es); r = []
    jx = len(re.findall('[！!]', ja)) + 2 * ja.count('‼') + ja.count('⁉'); jq = len(re.findall('[？?]', ja)) + ja.count('⁉')
    if jx != es.count('!'): r.append('EXCL_N')
    if jq != es.count('?'): r.append('INTER_N')
    if puntos(ja) != puntos(es): r.append('PUNTOS_SUSP')
    ja_o = len(re.findall('[「『]', ja)); ja_c = len(re.findall('[」』]', ja))
    es_o = len(re.findall('[«“]', es)); es_c = len(re.findall('[»”]', es)); rect = es.count('"')
    if (ja_o, ja_c) != (es_o + rect // 2, es_c + rect // 2) or rect % 2: r.append('COMILLAS_N')
    if re.search('[―─]', ja) and not re.search('[—―─]', es): r.append('RAYA_FALTA')
    if ja.count('♪') != es.count('♪'): r.append('NOTA_MUSICAL')
    if len(re.findall('[★☆]', ja)) != len(re.findall('[★☆]', es)): r.append('ESTRELLA')
    if len(re.findall('[♥♡]', ja)) != len(re.findall('[♥♡]', es)): r.append('CORAZON')
    if ja.count('～') > es.count('~'): r.append('TILDE_ONDA')
    if re.search('[ぁ-ん]ー', ja) and not (re.search('[ー~]', es) or re.search(r'(\w)\1\1', es)): r.append('ALARGA_FALTA')
    if len(re.findall('[（(]', ja)) != es.count('(') or len(re.findall('[）)]', ja)) != es.count(')'): r.append('PAREN_N')
    return r

# ---------- auditoria de una celda ----------
def auditar_celda(ja_trozos, es_raw):
    """-> (objetivas, subjetivas)"""
    masc = [enmascarar(x) for x in es_raw]; T, _ = unir(masc); ja = limpia_ja(' '.join(ja_trozos))
    obj = tipos_bal(T)
    if conteo_multi(ja, T)[0]: obj.append('CONTEO_MULTI')
    sub = []
    if len(T.split()) > 1 or len(ja) > 6: sub = subjetivas(ja, T)   # una palabra suelta = UI/sistema
    return obj, sub

def objetivas_puerta(ja_trozos, es_trozos):
    """PUERTA de validacion (aplicar_resultados.mal_es, aplicar_correcciones, verificar_antes_de_commit): tipos objetivos
    (EXCL_BAL INTER_BAL PAREN_BAL COMILLAS_BAL CONTEO_MULTI) de la celda unida. Fuera (falsos positivos conocidos): macros de rama
    (<Gender>/<If>/<Switch>), UI de una palabra; URLs, comandos y glifos PUA ya van enmascarados."""
    es = [es_trozos] if isinstance(es_trozos, str) else list(es_trozos or ())
    ja = [ja_trozos] if isinstance(ja_trozos, str) else list(ja_trozos or ())
    if not es or any(not isinstance(x, str) for x in es) or any(RE_RAMAS.search(x) for x in es): return []
    T, _ = unir([enmascarar(x) for x in es])
    if len(T.split()) <= 1 and len(limpia_ja(' '.join(ja))) <= 6: return []
    # excepciones legitimas (no son errores de simbologia): lista de simbolos permitidos en nombres («. , : ; ! ? & - _») y comandos de chat que empiezan por «/»
    jj = ' '.join(ja)
    # titulos OST/Orchestrion (oficiales en ingles, no siguen el ja), frases /say (ガウッ: la ! pertenece a la frase escrita), «???» de interfaz y marcadores solo de ？
    if 'オーケストリオン譜' in jj or 'ガウッ' in jj or '???' in jj or '/?' in jj or re.fullmatch(r'[\s？?]+', jj or ' '): return []
    if re.search(r'\.\s*,\s*:\s*;\s*!\s*\?', jj) or any(x.lstrip().startswith('/') and len(x.strip().split()) <= 4 for x in ja[:1]): return []
    obj = auditar_celda(ja, es)[0]; jt = limpia_ja(' '.join(ja))
    if len(re.findall('[「『]', jt)) != len(re.findall('[」』]', jt)): obj = [t for t in obj if t != 'COMILLAS_BAL']   # cita japonesa partida entre filas
    if len(re.findall('[（(]', jt)) != len(re.findall('[）)]', jt)): obj = [t for t in obj if t != 'PAREN_BAL']
    return obj

def simbolos(ja, es):
    """compat: tipos para un par (ja, es) de una sola cadena"""
    o, s = auditar_celda([ja], [es]); return o + s

# ---------- arreglos inequivocos ----------
# Solo se toca: (A) celdas de UNA sola frase, con la apertura al inicio absoluto de la frase (tras el prefijo); (B) rachas de
# signos agrupados ya emparejadas. Nunca se cambia «.» por !/?, nunca se inserta un signo a mitad de frase ni uno que el ja no tenga.
def _run_ja(ja):
    """-> (ne, nq, excl_primero) del unico terminador del ja, o None si el ja no es de una sola frase"""
    if re.search('[…‥]|[・.]{2,}', ja): return None
    runs = re.findall('[。！？!?‼⁉]+', ja)
    if len(runs) != 1 or '。' in runs[0]: return None
    if not ja.rstrip(' 」』）)').endswith(runs[0]): return None
    ne, nq = _t_ja(runs[0]); c0 = runs[0][0]
    return ne, nq, c0 in '！!‼⁉'

def _inicio_frase(T, p):
    """la posicion p abre frase: inicio de celda o tras un terminador !/?/. (nunca puntos suspensivos ni coma)"""
    i = p - 1
    while i >= 0 and T[i] in ' \n\x02': i -= 1
    if i < 0: return True
    if i == p - 1 and T[i] not in '!?.': return False
    return T[i] in '!?' or (T[i] == '.' and not (i > 0 and T[i - 1] == '.'))

def _canon(ne, nq, excl_primero):
    """-> (apertura, cierre) canonicos; None si no es un caso definido"""
    if nq == 0 and ne >= 1: return '¡' * ne, '!' * ne
    if ne == 0 and nq >= 1: return '¿' * nq, '?' * nq
    if ne == 1 and nq == 1: return ('¡¿', '?!') if excl_primero else ('¿¡', '!?')
    return None

def _caso_a(T, ja):
    """celda de una sola frase -> lista de ediciones (pos, borrar, texto) o None"""
    rj = _run_ja(ja)
    if not rj: return None
    cn = _canon(*rj)
    if not cn: return None
    ab, ce = cn
    body = T.rstrip(' \n\x02'); s0 = len(T) - len(T.lstrip(' \n'))
    m = re.search(r'[!?]+$', body)
    if not m or m.start() <= s0: return None
    run = m.group(0)
    lead = re.match('[¡¿]+', body[s0:]).group(0) if re.match('[¡¿]+', body[s0:]) else ''
    mid = body[s0 + len(lead):m.start()]
    if re.search(r'[.!?…:;¡¿«»“”"()—\x02]', mid) or re.search('[\x01\x02]$', mid): return None
    if not re.search(r'[^\W\d_]', mid): return None
    if mid[:1] in ' ' or mid[:1] == '\x01': return None
    cE, cQ = run.count('!'), run.count('?')
    if rj[1] == 0:
        if cQ or lead.strip('¡'): return None
        if lead and len(lead) != cE: return None
    elif rj[0] == 0:
        if cE or lead.strip('¿'): return None
        if lead and len(lead) != cQ: return None
    else:
        if (cE, cQ) != (1, 1) or len(lead) > 2 or (len(lead) == 2 and set(lead) != {'¡', '¿'}): return None
        if len(lead) == 1 and lead not in '¡¿': return None
    if not lead and not (mid[0].isupper() or mid[0].isdigit()): return None
    ed = []
    if lead != ab: ed.append((s0, len(lead), ab))
    if run != ce: ed.append((m.start(), len(run), ce))
    return ed or None

def reparar(es_raw, ja_trozos):
    """-> (nuevos trozos, [tipos arreglados]); solo arreglos inequivocos y verificados"""
    es = list(es_raw)
    if any(RE_RAMAS.search(x or '') for x in es) or not any(x for x in es): return es, []
    ja = limpia_ja(' '.join(ja_trozos)); hechos = []
    masc = [enmascarar(x) for x in es]; T, ini = unir(masc)
    ed = _caso_a(T, ja)
    if ed:
        nuevo = _aplicar(es, masc, ini, ed)
        if nuevo is not None:
            m2 = [enmascarar(x) for x in nuevo]; T2, _ = unir(m2)
            if not (set(tipos_bal(T2)) - set(tipos_bal(T))) and not conteo_multi(ja, T2)[0]:
                t0, t2 = tipos_bal(T), tipos_bal(T2)
                return nuevo, [t for t in ('EXCL_BAL', 'INTER_BAL') if t in t0 and t not in t2] + (['CONTEO_MULTI'] if conteo_multi(ja, T)[0] else []) or ['SIMBOLOS']
        return es, []
    # etapa B: rachas agrupadas ya emparejadas
    mal, fix = conteo_multi(ja, T)
    rj = rachas_ja(ja); re_ = rachas_es(T)
    if len(rj) != len(re_): return es, []
    b = balances(T); ed = []
    def bloque(a, e, cs):
        op = []
        for x in range(a, e):
            m = [pp for pp in b[T[x]][2] if pp[1] == x]
            if not m: return None
            op.append(m[0][0])
        op.sort()
        if op != list(range(op[0], op[0] + len(op))) or any(T[x] not in '¡¿' for x in op): return None
        return op
    for k, ((sj, tj), (a, e, te)) in enumerate(zip(rj, re_)):
        if len(sj) < 2: continue
        if tj == te and tj == (1, 1):
            cn = _canon(1, 1, sj[0] in '！!‼⁉')
            op = bloque(a, e, None)
            if not op or len(op) != 2: continue
            if T[op[0]:op[0] + 2] != cn[0] or T[a:e] != cn[1]:
                ed.append((e - 2, 2, cn[1])); ed.append((op[0], 2, cn[0]))
        elif tj != te and ((tj[1] == 0 and te[1] == 0 and tj[0] >= 1) or (tj[0] == 0 and te[0] == 0 and tj[1] >= 1)):
            c = '!' if tj[1] == 0 else '?'; ab = '¡' if c == '!' else '¿'; n = max(tj); kk = e - a
            op = bloque(a, e, None)
            if not op or any(T[x] != ab for x in op): continue
            if n > kk and not _inicio_frase(T, op[0]): continue
            if n > kk: ed.append((e, 0, c * (n - kk))); ed.append((op[0], 0, ab * (n - kk)))
            else: ed.append((e - (kk - n), kk - n, '')); ed.append((op[0], kk - n, ''))
    if ed:
        nuevo = _aplicar(es, masc, ini, ed)
        if nuevo is not None:
            m2 = [enmascarar(x) for x in nuevo]; T2, _ = unir(m2)
            if not conteo_multi(ja, T2)[0] and not (set(tipos_bal(T2)) - set(tipos_bal(T))):
                return nuevo, ['CONTEO_MULTI']
    return es, []

def _aplicar(es, masc, ini, ed):
    por = collections.defaultdict(list)
    for pos, borrar, txt in ed:
        i, off = a_trozo(ini, masc, pos)
        if borrar and off + borrar > len(masc[i]): return None
        por[i].append((off, borrar, txt))
    nuevo = list(es)
    for i, lst in por.items():
        t = nuevo[i]
        for off, borrar, txt in sorted(lst, key=lambda x: -x[0]):
            t = t[:off] + txt + t[off + borrar:]
        nuevo[i] = t
    return nuevo

# ---------- carga ----------
def es_crudo(raiz, hoja):
    ruta = os.path.join(raiz, 'traducciones', *hoja.split('/')) + '.jsonl'; ult = {}
    with open(ruta, encoding='utf-8') as f:
        for l in f:
            if l.strip():
                j = json.loads(l); ult[(j['row'], j.get('sub'), j['col'])] = j['es']
    return ult

def celdas_hoja(raiz, hoja):
    """-> {clave: (ja_trozos, es_crudo_lista, es_es_lista)}"""
    celdas = DC.cargar_celdas(raiz, hoja)
    if not celdas: return {}
    raw = es_crudo(raiz, hoja); out = {}
    for k, c in celdas.items():
        r = raw.get(k); r = r if isinstance(r, list) else [r]
        if len(r) != len(c['ja']): continue
        out[k] = (c['ja'], r, isinstance(raw.get(k), list))
    return out

def hojas_todas(raiz, filtro=None):
    base = os.path.join(raiz, 'traducciones')
    todas = sorted(os.path.relpath(os.path.join(d, f), base)[:-6] for d, _, fs in os.walk(base) for f in fs if f.endswith('.jsonl'))
    return [h for h in todas if not filtro or any(s in h for s in filtro)]

def auditar(raiz, hojas=None):
    obj = []; sub = []; ncel = 0
    for h in hojas_todas(raiz, hojas):
        try: cs = celdas_hoja(raiz, h)
        except FileNotFoundError: continue
        for k, (ja, es, _) in cs.items():
            ncel += 1
            o, s = auditar_celda(ja, es)
            if not o and not s: continue
            jt = ' | '.join(ja)
            if o:
                nuevo, hechos = reparar(es, ja)
                arr = ' | '.join(nuevo)
                for t in o: obj.append((h, k, t, jt, ' | '.join(es), arr if t in hechos else ''))
            for t in s: sub.append((h, k, t, jt, ' | '.join(es), ''))
    return obj, sub, ncel

def escribir(ruta, filas):
    fl = lambda s: str(s).replace('\t', ' ').replace('\n', '\\n')
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('hoja\trow\tsub\tcol\ttipo\tja\tes\tarreglo_propuesto\n')
        for h, k, t, j, e, a in filas:
            f.write('\t'.join(fl(x) for x in (h, k[0], '' if k[1] is None else k[1], k[2], t, j, e, a)) + '\n')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--hojas'); ap.add_argument('--raiz', default=RAIZ)
    ap.add_argument('--salida-dir'); a = ap.parse_args()
    d = a.salida_dir or os.path.join(a.raiz, 'trabajo', 'informes')
    obj, sub, ncel = auditar(a.raiz, a.hojas.split(',') if a.hojas else None)
    escribir(os.path.join(d, 'simbologia_objetiva.tsv'), obj); escribir(os.path.join(d, 'simbologia_subjetiva.tsv'), sub)
    po = collections.Counter(o[2] for o in obj); ps = collections.Counter(o[2] for o in sub)
    fx = collections.Counter(o[2] for o in obj if o[5])
    print('celdas %d; objetivas %d (arreglables %d); subjetivas %d' % (ncel, len(obj), sum(fx.values()), len(sub)))
    print('objetivas: ' + ', '.join('%s %d (arreglables %d)' % (t, n, fx[t]) for t, n in po.most_common()))
    print('subjetivas: ' + ', '.join('%s %d' % x for x in ps.most_common()))

if __name__ == '__main__': main()
