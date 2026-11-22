#!/usr/bin/env -S python3 -I
"""RAE: los puntos suspensivos son TRES. Toda racha de puntos suspensivos de mas de tres puntos se recorta a tres: `……`/`………`(…×n) -> `…`; `....`/`......` (.×≥4) -> `...`;
rachas mixtas (… y .) -> `…` si llevan algun `…`, si no `...`. No toca tokens <...> ni {0x..}. Orden del propietario 2026-11-05 (sustituye a la antigua regla «mismos puntos suspensivos»
de la simbologia 1:1 para la LONGITUD de la racha; la presencia/posicion de la pausa se conserva).
API: normalizar(es) -> mismo tipo (str o lista de str). CLI: --medir | --dry-run | --escribir [--hojas H1,H2] [--excluir lista.txt] (reemplazo textual por linea, mismo h/origen/estado)."""
import sys, os, re, json, argparse, collections
RUN = re.compile(r'(?:\.|…){4,}|…{2,}\.*|…\.+|\.…')   # …. y … + puntos tambien (el punto final se absorbe en los suspensivos)
TOK = re.compile(r'(<[^<>]*>|\{0x[0-9A-Fa-f]{2}:[^}]*\})')
def _run(m):
    r = m.group(0)
    return '...'   # 2026-11-08: SIEMPRE tres puntos ASCII (… prohibido)
LET = 'A-Za-zÁÉÍÓÚÜáéíóúüñÑ'
ELL = r"(?:\.\.\.|…)"
# ESPACIO tras suspensivos pegados a la palabra siguiente: «razonable...pero» -> «razonable... pero». Tartamudeos dentro de palabra («cone…xión», «Nu…tri…entes»)
# NO se tocan: con minuscula detras solo se separa si AMBOS fragmentos son palabras conocidas (conjunto del corpus); con mayuscula/¿¡«( detras se separa siempre.
SEP_FUERTE = re.compile(r"(?<!-\))(?<=[" + LET + r"?!)»])(" + ELL + r")(?=[¿¡«(A-ZÁÉÍÓÚÜÑ])")
SEP_MINUS = re.compile(r'([' + LET + r']+)(' + ELL + r')(?=([a-záéíóúüñ]+))')
SEP_SIGNO = re.compile(r'(?<!-\))(?<=[?!)»])(' + ELL + r')(?=[a-záéíóúüñ])')
_PAL = None
def palabras_conocidas(base=None):
    """Palabras (>=3 apariciones, minusculas) del corpus que NO tocan suspensivos; la decision es estable al reescribir."""
    global _PAL
    if _PAL is not None: return _PAL
    c = collections.Counter(); base = base or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'traducciones')
    w = re.compile(r'(?<![' + LET + r'.…])([' + LET + r']{2,})(?![' + LET + r'.…])')
    for dp, _, fs in os.walk(base):
        for f in fs:
            if not f.endswith('.jsonl'): continue
            for l in open(os.path.join(dp, f), encoding='utf-8'):
                if '"es"' not in l: continue
                try: es = json.loads(l)['es']
                except Exception: continue
                for t in (es if isinstance(es, list) else [es]):
                    if isinstance(t, str):
                        for p in TOK.split(t)[::2]: c.update(x.lower() for x in w.findall(p))
    _PAL = {k for k, v in c.items() if v >= 3}; return _PAL
def _sep_minus(m, pal):
    a, b = m.group(1), m.group(3)
    return a + m.group(2) + ' ' if a.lower() in pal and b.lower() in pal and len(a) > 2 else m.group(0)
def normalizar_trozo(t, pal=None):
    if not isinstance(t, str) or ('.' not in t and '…' not in t): return t
    out = []
    for i, p in enumerate(TOK.split(t)):
        if i % 2 == 0:
            p = RUN.sub(_run, p)
            if '.' in p or '…' in p:
                p = SEP_FUERTE.sub(lambda m: m.group(1) + ' ', p)
                p = SEP_SIGNO.sub(lambda m: m.group(1) + ' ', p)
                if SEP_MINUS.search(p):
                    pal = pal if pal is not None else palabras_conocidas()
                    p = SEP_MINUS.sub(lambda m: _sep_minus(m, pal), p)
        out.append(p)
    return ''.join(out)
def normalizar(es, pal=None):
    return [normalizar_trozo(x, pal) for x in es] if isinstance(es, list) else normalizar_trozo(es, pal)
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--repo', default=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')))
    g = ap.add_mutually_exclusive_group(required=True)
    for k in ('medir', 'dry-run', 'escribir'): g.add_argument('--' + k, action='store_true')
    ap.add_argument('--hojas', default=''); ap.add_argument('--excluir', default='')
    a = ap.parse_args()
    solo = set(x for x in a.hojas.split(',') if x); excl = set(open(a.excluir).read().split()) if a.excluir else set()
    base = os.path.join(a.repo, 'traducciones'); cnt = collections.Counter()
    for dp, _, fs in os.walk(base):
        for f in sorted(fs):
            if not f.endswith('.jsonl'): continue
            p = os.path.join(dp, f); hoja = os.path.relpath(p, base)[:-6].replace(os.sep, '/')
            if solo and hoja not in solo or hoja in excl: continue
            out = []; cambio = False
            for l in open(p, encoding='utf-8'):
                if '"es"' in l and l.strip():
                    d = json.loads(l); n = normalizar(d.get('es'))
                    if n != d.get('es'):
                        cnt['celdas'] += 1; cnt[hoja.split('/')[0]] += 1; cambio = True
                        if not a.medir:
                            old = json.dumps(d['es'], ensure_ascii=False); new = json.dumps(n, ensure_ascii=False)
                            if old in l: l = l.replace(old, new, 1)
                            else: d['es'] = n; l = json.dumps(d, ensure_ascii=False) + '\n'
                out.append(l)
            if cambio and a.escribir: open(p, 'w', encoding='utf-8', newline='').write(''.join(out))
    print(dict(cnt.most_common(12)))
if __name__ == '__main__': main()
