"""VENTANA FINAL (requisito del propietario, visto en el juego): ninguna ventana de texto puede quedar con 1-2 palabras.
La logica de reparto vive en reflujar_v2.py (penalizacion `vf_penal` en el DP: si el nº de lineas g cumple g % 3 == 1 la ultima ventana es solo la ultima linea y debe tener
>= 4 palabras y >= 15 caracteres; se mueven palabras entre lineas y trozos vecinos con los MISMOS saltos del japones, tope 56 car./linea, mismos invariantes y revalidacion
de reflujar_lineas.procesar_celda). Con --paginar las celdas `no_cabe` se reparten por ventanas (el juego envuelve cada trozo).
Este script: (1) MIDE por familia las celdas con >= 2 ventanas cuya ultima ventana tiene <= 2 palabras (antes/despues) y las «debiles» (< 4 palabras o < 15 car.);
(2) escribe `ventanas_no_arreglables.tsv` (hoja,row,col,ultima_ventana,motivo,sub) con las que siguen <= 2 palabras (solo reescribiendo cabrian; las reescribe Haiku);
(3) con --escribir aplica el reflujo (SOLO sobre una copia --root en /tmp; hace copia en <root>/trabajo/lotes/bak).
Uso: python3 -I reflujar_ventana_final.py --root /tmp/r3 --familias quest,DefaultTalk,cut_scene --paginar [--escribir] [--hojas SUB,..] [--tsv F]"""
import sys, os, re, json, argparse, collections
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import reflujar_v2 as V
R = V.R

def ultima_ventana(s, W):
    """-> (n_ventanas, texto de la ultima ventana) de la cadena tokenizada; (0, '') si no se puede calcular"""
    try: vs = R.ventanas(s[R.prefijo_len(s):], W)
    except Exception: return 0, ''
    if not vs: return 0, ''
    return len(vs), ' '.join(l for l in vs[-1] if l)

def debil(txt): return len(txt.split()) < 4 or len(txt) < 15
def corta(txt): return len(txt.split()) <= 2

ESQ = {'lf_ok': 0, 'lf_rechazo': collections.Counter()}

def lf_final(text, raw, e, s0, W):
    """celdas `es` STRING (cadena compleja: el validador y pgri admiten LF reales extra) cuyo ultimo bloque es UN solo trozo sin saltos blandos (los demas saltos son del japones
    y no se tocan) y cuya ultima ventana (envuelta por el juego) tiene <= 2 palabras: se insertan LF dentro de ese ultimo trozo (DP de v2 con penalizacion de ventana final).
    -> nueva cadena o None (motivo en ESQ['lf_rechazo'])"""
    if not isinstance(e['es'], str): return None
    try:
        R.tokens_ok(s0)
        ws, js = R.escanear(s0); ws, js = R.normalizar_union(ws, js)
        bls = [R.Bloque(ws, js, a, b) for a, b in R.bloques(ws, js)]
        if any(bl.actual for bl in bls): return None   # hay saltos blandos: nº de saltos fijado por el japones
        bl = bls[-1]
        if bl.n < 4: return None
        off = sum(len(R.lineas_pieza(x, 0, x.n - 1, W)) for x in bls[:-1])
        jmax = max(1, min(bl.n - 1, sum(bl.v) // 28 + 2))
        V.VF.update(off=off, bi=len(bls) - 1, nb=len(bls), exacto=True, on=True)
        c, cuts = V.optimizar2(bl, 1, jmax, W)
        if cuts is None: ESQ['lf_rechazo']['sin_reparto'] += 1; return None
        nuevo = R.reconstruir(ws, js, bls, [[] for _ in bls[:-1]] + [cuts], [(0, 0, None)] * len(bls), True, 'libre')
        if not R.invariante(s0, nuevo): ESQ['lf_rechazo']['invariante'] += 1; return None
        v, t = ultima_ventana(nuevo, W)
        if v >= 2 and corta(t): ESQ['lf_rechazo']['sigue_corta'] += 1; return None
        e2 = dict(e); e2['es'] = nuevo
        R.C.evaluar_cadena(text, raw, e2)
    except R.C.Rechazo as r: ESQ['lf_rechazo']['rechazo_' + r.motivo] += 1; return None
    except Exception as x: ESQ['lf_rechazo']['error_' + type(x).__name__] += 1; return None
    ESQ['lf_ok'] += 1
    return nuevo

CUR = {'hoja': ''}
FILAS = []   # (fam, hoja, row, sub, col, res, motivo, s_antes, s_despues, W)
_proc = R.procesar_celda
def _medir(text, raw, e, W, creador, clave=None, diag=None):
    d = diag if diag is not None else {}
    res = _proc(text, raw, e, W, creador, clave, d)
    try:
        tok = R.S.tokenize_raw(R.G.bytes_ja(text, raw)); es = e['es']
        if isinstance(es, list): tr, seps = R.G.trocear(tok); s0 = R.G.recomponer(seps, es)
        else: s0 = es
        s1 = d.get('despues') if res[0] == 'cambiada' and d.get('despues') else s0
        diario = bool(d.get('diario')) or (bool(clave) and re.search(r'_(?:SEQ|TODO)_\d+$', clave) is not None)
        if diario: return res   # texto del diario de misiones: no usa ventanas de dialogo
        if LF['on'] and res[0] in ('sin_saltos', 'excepcion') and not str(res[1]).startswith(('rechazo', 'estructura')):
            v1, t1 = ultima_ventana(s1, W)
            if v1 >= 2 and corta(t1):
                nuevo = lf_final(text, raw, e, s0, W)
                if nuevo is not None:
                    res = ('cambiada', nuevo, {'lineas': 0, 'modo': 'lf'}); s1 = nuevo; d['despues'] = nuevo; d.setdefault('antes', s0)
        FILAS.append((CUR['fam'], CUR['hoja'], e['row'], e.get('sub'), e['col'], res[0], res[1] if res[0] == 'excepcion' else '', s0, s1, W))
    except Exception: pass
    return res
LF = {'on': True}
_ph = R.procesar_hoja
def _hoja(root, hoja, fam, W, dry, st, exc, cambios, filtro_claves=None):
    CUR['hoja'] = hoja; CUR['fam'] = fam
    return _ph(root, hoja, fam, W, dry, st, exc, cambios, filtro_claves)
def instalar():
    # el monkeypatch solo se aplica al ejecutar el script, no al importar (contaminaba los tests)
    R.procesar_celda = _medir; R.procesar_hoja = _hoja

def motivo(res, mot):
    if res == 'sin_saltos': return 'sin_saltos_ja: una sola linea en el japones; el juego la envuelve y no se puede mover texto'
    if res == 'excepcion': return 'excepcion_' + str(mot) + ': el reflujo no puede tocar la celda'
    return 'sin_reparto: con los saltos del japones y 56 car./linea no cabe una ultima ventana mayor de 2 palabras'

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--familias', default='quest,DefaultTalk,cut_scene'); ap.add_argument('--root', required=True)
    ap.add_argument('--hojas', default=''); ap.add_argument('--paginar', action='store_true'); ap.add_argument('--escribir', action='store_true')
    ap.add_argument('--tsv', default=os.path.join(R.RAIZ, 'trabajo', 'informes', 'ventanas_no_arreglables.tsv'))
    ap.add_argument('--sin-ventana-final', action='store_true'); ap.add_argument('--sin-lf', action='store_true', help='no insertar LF en celdas string sin saltos')
    a = ap.parse_args(argv); instalar()
    V.VF['on'] = not a.sin_ventana_final; LF['on'] = not a.sin_lf
    R.CFG.macros = True; R.CFG.paginar = a.paginar; R.CFG.ancho_max = 61
    filtro = [x for x in a.hojas.split(',') if x]
    print('familia\tceldas\tmulti_ventana\tultima<=2pal antes/despues\tdebiles antes/despues\tcambiadas')
    noarr = []
    for fam in a.familias.split(','):
        del FILAS[:]; st = collections.defaultdict(collections.Counter); exc = []; cambios = []
        W = V.HARD
        for hoja in R.hojas_de_familia(a.root, fam):
            if filtro and not any(x in hoja for x in filtro): continue
            R.procesar_hoja(a.root, hoja, fam, W, not a.escribir, st, exc, cambios)
        n = multi = c0 = c1 = d0 = d1 = cam = 0
        for fam_, hoja, row, sub, col, res, mot, s0, s1, W_ in FILAS:
            n += 1
            v0, t0 = ultima_ventana(s0, W_); v1, t1 = ultima_ventana(s1, W_)
            if v1 >= 2: multi += 1
            if res == 'cambiada': cam += 1
            if v0 >= 2 and corta(t0): c0 += 1
            if v0 >= 2 and debil(t0): d0 += 1
            if v1 >= 2 and debil(t1): d1 += 1
            if v1 >= 2 and corta(t1):
                c1 += 1; noarr.append((hoja, row, col, t1, motivo(res, mot), '' if sub is None else sub))
        print('%s\t%d\t%d\t%d/%d\t%d/%d\t%d' % (fam, n, multi, c0, c1, d0, d1, cam))
    with open(a.tsv, 'w', encoding='utf-8', newline='\n') as f:
        f.write('hoja\trow\tcol\tultima_ventana\tmotivo\tsub\n')
        for r in noarr: f.write('\t'.join(str(x).replace('\t', ' ').replace('\n', ' ') for x in r) + '\n')
    print('LF insertados (celdas string sin saltos): %d; rechazos %s' % (ESQ['lf_ok'], dict(ESQ['lf_rechazo'])))
    print('no arreglables escritas: %d -> %s' % (len(noarr), a.tsv))
    mot_c = collections.Counter(r[4].split(':')[0] for r in noarr)
    for m, c in mot_c.most_common(): print('   %s: %d' % (m, c))
    return 0

if __name__ == '__main__': sys.exit(main())
