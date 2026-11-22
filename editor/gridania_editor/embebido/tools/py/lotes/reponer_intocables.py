#!/usr/bin/env -S python3 -I
"""Repone de forma DETERMINISTA los glifos PUA / controles / marcadores («intocables») que el traductor no ve y que faltan en el trozo `es`.
Funcion `reponer(ja, es)` -> (es_nuevo, lista_de_reposiciones, lista_de_no_resueltos). Por trozo i con faltantes (multiconjunto ja - es):
  - trozo ja sin letras (solo intocables/espacios/simbolos): el trozo es = el trozo ja si el es esta vacio o ya tiene los mismos intocables; si no, se anaden al final.
  - faltante con SOLO intocables/espacios/simbolos antes en el trozo ja -> se inserta al INICIO del trozo es (en orden de ja);
  - faltante con SOLO intocables/espacios/simbolos despues -> al FINAL (en orden de ja);
  - faltante en medio -> en la posicion relativa (fraccion de letras del ja) ajustada al espacio mas cercano del es.
  - «sobran» (el es trae intocables que el ja no): NO se toca (queda rechazado).
Uso CLI: python3 -I tools/py/lotes/reponer_intocables.py [--partes p03,...] [--dry-run]   (= aplicar_correccion_b2c.py --reponer: mismas validaciones y escritura; ver ese script).
Los rechazos por INTOCABLES de trabajo/informes/b2c_rechazos_final.tsv salen de las partes b2c (resc_corr); las claves de b2_rechazos_tanda*.tsv estan cubiertas por esas partes."""
import os, re, sys, collections
AQUI = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, AQUI); sys.path.insert(0, os.path.join(AQUI, '..'))
import aplicar_resultados as A
import segmentar as G

def _tokens(t):
    """[(inicio, fin, texto)] de intocables del trozo en orden: PUA, control, marcadores"""
    out = [(m.start(), m.end(), m.group()) for m in A.PUA_RE.finditer(t)]
    out += [(i, i + 1, c) for i, c in enumerate(t) if G.es_control(c)]
    out += [(m.start(), m.end(), m.group()) for m in G.MARCADOR_RE.finditer(t)]
    return sorted(out)

def _sin_tokens(t):
    for a, b, _ in sorted(_tokens(t), reverse=True): t = t[:a] + t[b:]
    return t

def _letras(t): return sum(1 for c in _sin_tokens(t) if c.isalpha())

def reponer_trozo(j, e):
    """-> (e_nuevo, [descripciones], resuelto)"""
    a, b = A.intocables(j), A.intocables(e)
    if a == b: return e, [], True
    if b - a: return e, [], False   # sobran intocables: no se arregla aqui
    falta = a - b
    # faltantes en orden de ja
    pend = collections.Counter(falta); faltan = []
    for s, f, txt in _tokens(j):
        if pend.get(txt, 0) > 0: pend[txt] -= 1; faltan.append((s, f, txt))
    desc = []
    if _letras(j) == 0:
        if not e.strip(): return j, ['trozo propio: es = ja'], True
        return e + ''.join(x[2] for x in faltan), ['trozo sin letras: al final'], True
    pre = []; suf = []; med = []; pre_fin = 0
    for s, f, txt in faltan:
        antes, despues = _letras(j[:s]), _letras(j[f:])
        if antes == 0: pre.append(txt); pre_fin = f
        elif despues == 0: suf.append(txt)
        else: med.append((antes / max(1, _letras(j)), txt))
    n = e
    for fr, txt in reversed(sorted(med)):   # de derecha a izquierda para no desplazar
        pos = int(round(fr * len(n)))
        esp = [i for i, c in enumerate(n) if c == ' ']
        if esp: pos = min(esp, key=lambda i: abs(i - pos)) + 1
        n = n[:pos] + txt + n[pos:]; desc.append('medio %.2f' % fr)
    if pre:
        # conserva el espacio que sigue al glifo en el ja (si el es no empieza ya por espacio)
        esp = j[pre_fin:pre_fin + 1] if j[pre_fin:pre_fin + 1] in (' ', '\u00a0') else ''
        if n[:1].isspace(): esp = ''
        n = ''.join(pre) + esp + n; desc.append('inicio x%d' % len(pre))
    if suf: n = n + ''.join(suf); desc.append('fin x%d' % len(suf))
    return n, desc, A.intocables(j) == A.intocables(n)

def reponer(ja, es):
    """ja, es: listas de trozos de igual longitud -> (es_nuevo, reposiciones[(i,desc)], no_resueltos[i])"""
    nuevo = list(es); rep = []; nores = []
    if len(ja) != len(es): return nuevo, rep, list(range(len(ja)))
    for i, (j, e) in enumerate(zip(ja, es)):
        n, d, ok = reponer_trozo(j, e)
        if not ok: nores.append(i)
        elif n != e: nuevo[i] = n; rep.append((i, '; '.join(d)))
    return nuevo, rep, nores

def main():
    import aplicar_correccion_b2c as P
    sys.argv = [sys.argv[0], '--reponer'] + sys.argv[1:]
    return P.main()

if __name__ == '__main__': sys.exit(main())
