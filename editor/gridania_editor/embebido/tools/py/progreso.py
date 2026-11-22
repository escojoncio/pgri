#!/usr/bin/env -S python3 -I
"""Cuenta traducciones/**/*.jsonl frente a textos/INDEX.csv y escribe PROGRESO.csv
(hoja,total_cadenas,traducidas,revisadas,dudosas,pendientes; contadores excluyentes por `estado`;
pendientes = total_cadenas - traducidas - revisadas, es decir cadenas aun sin traduccion aprovechable, dudosas incluidas;
heredadas (ultima columna) = filas con origen corpus aun sin retraducir).
Uso: python3 -I tools/py/progreso.py [--root RAIZ] [--excluir-no-traducibles]  (por defecto la raiz del repo).
--excluir-no-traducibles: modo «pendiente real» (cifra para informar): lee trabajo/informes/corpus_no_traducible.tsv (lineas corpus cuyo ja no tiene CJK; se conservan, no se borran) y
  añade la columna `no_traducibles` (esas lineas de la hoja, aun corpus); pendientes = total - (traducidas - heredadas) - revisadas - no_traducibles, es decir, ni el corpus heredado
  ni las lineas sin nada que traducir cuentan como hecho/pendiente. Sin el flag, PROGRESO.csv no cambia."""
import csv, json, os, sys, argparse
RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
ESTADOS = ('traducida', 'revisada', 'dudosa')

def contar(root, h):
    c = dict.fromkeys(ESTADOS, 0); c['heredadas'] = 0
    p = os.path.join(root, 'traducciones', h + '.jsonl')
    if os.path.exists(p):
        with open(p, encoding='utf8') as f:
            for l in f:
                if l.strip():
                    try: d = json.loads(l)
                    except ValueError: continue
                    e = d.get('estado') if isinstance(d, dict) else None
                    if e in ESTADOS: c[e] += 1
                    if e in ESTADOS and d.get('origen') == 'corpus': c['heredadas'] += 1
    return c

def no_traducibles(root):
    """{hoja: n} de trabajo/informes/corpus_no_traducible.tsv (hoja,row,sub,col,motivo)"""
    c = {}; p = os.path.join(root, 'trabajo', 'informes', 'corpus_no_traducible.tsv')
    if os.path.exists(p):
        with open(p, encoding='utf8') as f:
            next(f, None)
            for l in f:
                h = l.split('\t', 1)[0]
                if h.strip(): c[h] = c.get(h, 0) + 1
    return c

def escribir(root=RAIZ, excluir=False):
    nt = no_traducibles(root) if excluir else {}
    with open(os.path.join(root, 'textos', 'INDEX.csv'), encoding='utf8', newline='') as f, \
         open(os.path.join(root, 'PROGRESO.csv'), 'w', encoding='utf8', newline='') as o:
        w = csv.writer(o, lineterminator='\n'); w.writerow(['hoja', 'total_cadenas', 'traducidas', 'revisadas', 'dudosas', 'pendientes', 'heredadas'] + (['no_traducibles'] if excluir else []))
        for row in csv.DictReader(f):
            c = contar(root, row['hoja'])
            n = nt.get(row['hoja'], 0)
            pend = max(int(row['cadenas_no_vacias']) - (c['traducida'] - c['heredadas']) - c['revisada'] - n, 0) if excluir else max(int(row['cadenas_no_vacias']) - c['traducida'] - c['revisada'], 0)
            w.writerow([row['hoja'], row['cadenas_no_vacias'], c['traducida'], c['revisada'], c['dudosa'], pend, c['heredadas']] + ([n] if excluir else []))

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--root', default=RAIZ); ap.add_argument('--excluir-no-traducibles', action='store_true'); a = ap.parse_args(); escribir(a.root, a.excluir_no_traducibles)
