"""SUBTITULOS SIN RECUADRO (cut_scene/* y opening/*): el juego dibuja la linea sobre la pantalla, sin caja ni auto-ajuste (medido por el propietario: una linea de ~95 car. sale
cortada; lineas de 42-45 caben). El nº de lineas lo fija el japones (un trozo `es` por trozo `ja`; no se anaden saltos). Este script SOLO toca celdas con alguna linea > TOPE:
reutiliza el motor de reflujar_v2/reflujar_lineas (mismos invariantes, macros, revalidacion con construir_dat.evaluar_cadena; no toca h/origen/estado) con W = TOPE y sin
penalizacion de ventana final (no hay ventanas). Lo que no cabe en los trozos del japones con el tope se registra (no se toca) para reescritura posterior.
  --medir : escribe trabajo/informes/anchos_sin_recuadro.tsv (francés por LINEA, partiendo por NewLine/LF; tope por grupo = max(45, min(fr_p99, 58)))
  --escribir : aplica (SIN el, dry-run); escribe trabajo/informes/subtitulos_no_caben.tsv
Uso: python3 -I reflujar_subtitulos.py [--root R] [--tope 58] [--medir] [--escribir] [--hojas SUB,..]"""
import sys, os, re, json, glob, math, argparse, collections
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import reflujar_v2 as V
R = V.R
TOPE_MAX = 58; TOPE_MIN = 45
FAMILIAS = ('cut_scene', 'opening')
HARD = re.compile(r'\n|\{0x10:\}')
MARK = re.compile(r'\{0x[0-9A-Fa-f]+:[^}]*\}')
NL_RE = re.compile(r'<NewLine(?:#\d+)?>|\n')
TAG_RE = re.compile(r'<[^>]*>')

def pct(v, p):
    if not v: return 0
    v = sorted(v); return v[max(0, math.ceil(p * len(v)) - 1)]

def segs(t):
    t = t.replace('{0x1D:}', ' '); out = []
    for s in HARD.split(t):
        s = TAG_RE.sub('', MARK.sub('', s)).strip()
        if s: out.append(len(s))
    return out

def hojas(root, filtro=()):
    out = []
    for fam in FAMILIAS:
        for p in sorted(glob.glob(os.path.join(root, 'traducciones', fam, '**', '*.jsonl'), recursive=True)):
            h = os.path.relpath(p, os.path.join(root, 'traducciones'))[:-6]
            if filtro and not any(x in h for x in filtro): continue
            out.append(h)
    return out

def grupo(h):
    p = h.split('/')
    return '/'.join(p[:2]) if p[0] == 'cut_scene' else h

def medir(root, tsv):
    g = collections.defaultdict(lambda: {'fr': [], 'ja': [], 'nl': [], 'cel': 0, 'es': []})
    for h in hojas(root):
        for lang in ('fr', 'ja'):
            p = os.path.join(root, 'textos', lang, h + '.jsonl')
            if not os.path.exists(p): continue
            for l in open(p, encoding='utf-8'):
                j = json.loads(l)
                if j['col'] == 0: continue
                s = segs(j['text'])
                if not s: continue
                if lang == 'fr': g[grupo(h)]['fr'].extend(s); g[grupo(h)]['nl'].append(len(s)); g[grupo(h)]['cel'] += 1
                else: g[grupo(h)]['ja'].extend(s)
        for l in open(os.path.join(root, 'traducciones', h + '.jsonl'), encoding='utf-8'):
            j = json.loads(l); es = j['es']
            for x in ([es] if isinstance(es, str) else es):
                for ln in NL_RE.split(x): g[grupo(h)]['es'].append(len(TAG_RE.sub('', ln)))
    with open(tsv, 'w', encoding='utf-8', newline='\n') as f:
        f.write('grupo\tfamilia\tceldas_fr\tfr_lineas_max\tfr_max\tfr_p95\tfr_p99\tja_max\tja_p99\tes_max_actual\tes_p99_actual\ttope_fr=min(fr_p99,58)\ttope_final=max(45,tope_fr)\tnota\n')
        for k in sorted(g):
            d = g[k]
            if not d['fr']: continue
            tf = min(pct(d['fr'], .99), TOPE_MAX); tfin = max(TOPE_MIN, tf)
            f.write('%s\t%s\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%s\n' % (k, k.split('/')[0], d['cel'], max(d['nl']), max(d['fr']), pct(d['fr'], .95), pct(d['fr'], .99),
                    max(d['ja'] or [0]), pct(d['ja'], .99), max(d['es'] or [0]), pct(d['es'], .99), tf, tfin,
                    'subtitulo sin recuadro; fr_p99 > 58 en todos los grupos: el fr NO acota; manda min(.,58), la medida del propietario (95 corta, 42-45 buenas) y ja_p99 (CJK ancho doble: 30 ~ 60 latinas)'))
        f.write('Balloon\tBalloon\t10455\t3\t144\t74\t92\t31\t14\t56\t38\t58\t58\tCON caja que autoajusta (fr 144 car./linea con hasta 3 lineas): NO entra en el tope\n')
        f.write('NpcYell\tNpcYell\t19452\t3\t235\t86\t129\t52\t27\t126\t57\t58\t58\tCON caja que autoajusta (fr 235 car./linea): NO entra en el tope\n')


PESO_DESPL = 2.5   # coste por palabra desplazada respecto al corte del original (minimo cambio: el corte del japones suele ser semantico)

def dp_lista(palabras, orig, k, W):
    """reparte `palabras` en k lineas contiguas no vacias de ancho <= W con coste minimo = cortes naturales (coste_corte) + desplazamiento de cada corte respecto a `orig`
    (indices de palabra tras los que cortaba el original) + penalizacion de lineas de una palabra. -> lista de cortes (indices de la ultima palabra de cada linea salvo la ultima) o None"""
    n = len(palabras)
    if k > n: return None
    pre = [0]
    for w in palabras: pre.append(pre[-1] + len(R.plano(w)))
    def ancho(a, b): return pre[b + 1] - pre[a] + (b - a)   # palabras a..b
    INF = float('inf')
    f = [dict() for _ in range(k)]   # f[j][p] = (coste, previo): j+1 lineas, la ultima acaba en p
    for p in range(n):
        if ancho(0, p) <= W: f[0][p] = (0.0, None)
    for j in range(1, k):
        for p in range(j, n):
            mejor = None
            for q, (cq, _) in f[j - 1].items():
                if q >= p: continue
                L = ancho(q + 1, p)
                if L > W: continue
                c = cq + R.coste_corte(palabras[q], palabras[q + 1]) + PESO_DESPL * abs(q - orig[j - 1])
                if q + 1 == p and (p - q) < 2 and L < 12: c += 6.0
                if mejor is None or c < mejor[0] - 1e-9: mejor = (c, q)
            if mejor is not None: f[j][p] = mejor
    if (n - 1) not in f[k - 1]: return None
    # ultima linea: penaliza una sola palabra corta
    cuts = []; p = n - 1; j = k - 1
    while j > 0: q = f[j][p][1]; cuts.append(q); p = q; j -= 1
    return sorted(cuts)

def reflujar_lista(es):
    """es: lista de trozos sin marcadores -> nueva lista (mismo nº de trozos) o None si no cabe. Respeta el prefijo (-Nombre-) del primer trozo."""
    k = len(es)
    if k < 2: return None
    pre = R.prefijo_len(es[0]); etiqueta = es[0][:pre]
    trozos = [es[0][pre:]] + list(es[1:])
    palabras = []; orig = []
    for t in trozos:
        ws = t.split()
        if not ws: return None
        palabras.extend(ws); orig.append(len(palabras) - 1)
    cuts = dp_lista(palabras, orig[:-1], k, W_ACT[0])
    if cuts is None: return None
    out = []; ini = 0
    for c in cuts + [len(palabras) - 1]: out.append(' '.join(palabras[ini:c + 1])); ini = c + 1
    out[0] = etiqueta + out[0]
    return out
W_ACT = [TOPE_MAX]

def lineas_celda(es):
    """anchos visibles por linea (misma medida que el motor: macros estimadas, sin etiqueta del hablante)"""
    out = []
    for x in ([es] if isinstance(es, str) else es):
        x = x[R.prefijo_len(x):]
        for ln in R.partir_lineas(x): out.append(R.analizar(ln)[0] if R.no_ok(ln) else R.vis(ln))
    return out

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=R.RAIZ); ap.add_argument('--tope', type=int, default=TOPE_MAX)
    ap.add_argument('--medir', action='store_true'); ap.add_argument('--escribir', action='store_true')
    ap.add_argument('--hojas', default=''); ap.add_argument('--ejemplos', type=int, default=0)
    ap.add_argument('--tsv-no-caben', default=os.path.join(R.RAIZ, 'trabajo', 'informes', 'subtitulos_no_caben.tsv'))
    ap.add_argument('--tsv-medida', default=os.path.join(R.RAIZ, 'trabajo', 'informes', 'anchos_sin_recuadro.tsv'))
    a = ap.parse_args(argv)
    if a.medir: medir(a.root, a.tsv_medida); print('medida ->', a.tsv_medida)
    W = a.tope; W_ACT[0] = W
    V.VF['on'] = False; R.TOL = W; R.CFG.macros = True; R.CFG.paginar = False; R.CFG.ancho_max = W
    proc0 = R.procesar_celda
    cnt = collections.Counter()
    def filtro(text, raw, e, W_, creador, clave=None, diag=None):
        if max(lineas_celda(e['es']) or [0]) <= W_: cnt['ya_cabe'] += 1; return ('ya_correcta', None, {})
        es = e['es']
        if isinstance(es, list) and not any('<' in x for x in es):
            if len(es) < 2: return ('sin_saltos', None, '')
            nes = reflujar_lista(es)
            if nes is None: return ('excepcion', 'no_cabe', 'lista de %d trozos' % len(es))
            if ' '.join(' '.join(nes).split()) != ' '.join(' '.join(es).split()): return ('excepcion', 'invariante', 'el texto cambia')
            e2 = dict(e); e2['es'] = nes
            try: R.C.evaluar_cadena(text, raw, e2)
            except R.C.Rechazo as r: return ('excepcion', 'rechazo_' + r.motivo, r.detalle)
            return ('cambiada', nes, {'lineas': len(nes), 'modo': 'lista_dp'})
        return proc0(text, raw, e, W_, creador, clave, diag)
    R.procesar_celda = filtro
    st = collections.defaultdict(collections.Counter); exc = []; cambios = []
    fl = [x for x in a.hojas.split(',') if x]
    for h in hojas(a.root, fl): R.procesar_hoja(a.root, h, 'cut_scene', W, not a.escribir, st, exc, cambios)
    c = st['cut_scene']
    print('tope %d | cambiadas %d | excepciones %d | fuera_alcance %d | tipo_es %d' % (W, c['cambiada'], c['excepciones'], c['fuera_alcance'], c['tipo_es']))
    porfam = collections.Counter()
    for cb in cambios: porfam[cb['hoja'].split('/')[0]] += 1
    print('cambiadas por familia:', dict(porfam)); print('motivos:', {k: v for k, v in c.items() if k.startswith('exc_')})
    if a.ejemplos:
        import random
        for cb in random.Random(3).sample(cambios, min(a.ejemplos, len(cambios))): print(cb['hoja'], cb['k'], '\n  ', cb['antes'], '\n =>', cb['despues'])
    # no caben: excepciones + celdas fuera de alcance con linea > tope (se registran todas las que siguen incumpliendo tras el reflujo)
    filas = []
    for (fam, h, row, sub, col, mot, det) in exc:
        filas.append((h, row, sub, col, mot))
    def leer(lang, h):
        d = {}
        p = os.path.join(a.root, 'textos', lang, h + '.jsonl')
        if os.path.exists(p):
            for l in open(p, encoding='utf-8'):
                j = json.loads(l); d[(j['row'], j.get('sub'), j['col'])] = j['text']
        return d
    with open(a.tsv_no_caben, 'w', encoding='utf-8', newline='\n') as f:
        f.write('hoja\trow\tsub\tcol\tes\tja\tfr\tmotivo\n')
        n = 0
        for h in hojas(a.root, fl):
            ja = leer('ja', h); fr = leer('fr', h)
            pend = {}
            for l in open(os.path.join(a.root, 'traducciones', h + '.jsonl'), encoding='utf-8'):
                if not l.strip(): continue
                j = json.loads(l); pend[(j['row'], j.get('sub'), j['col'])] = j['es']
            mots = {(r, s if s != '' else None, cc): m for (hh, r, s, cc, m) in filas if hh == h}
            for k, es in pend.items():
                if max(lineas_celda(es) or [0]) <= W: continue
                es_t = es if isinstance(es, str) else '<NewLine>'.join(es)
                f.write('\t'.join([h, str(k[0]), '' if k[1] is None else str(k[1]), str(k[2]), es_t.replace('\t', ' ').replace('\n', '\\n'),
                                   ja.get(k, '').replace('\t', ' ').replace('\n', '\\n'), fr.get(k, '').replace('\t', ' ').replace('\n', '\\n'), mots.get(k, 'una_sola_linea_en_ja_o_sin_cambio')]) + '\n')
                n += 1
    print('no caben (lineas > %d tras el reflujo%s): %d -> %s' % (W, '' if a.escribir else ' [DRY-RUN: cuenta tambien las que se arreglarian]', n, a.tsv_no_caben))
    return 0

if __name__ == '__main__': sys.exit(main())
