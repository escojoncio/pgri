#!/usr/bin/env -S python3 -I
"""Validacion del translations.dat COMPLETO con el MISMO criterio que construir_dat.evaluar_cadena (suavizado-aware), entrada a entrada y en paralelo por hoja.
validate_blob.py (via plana) no entiende: la marca U+E0F0 (sestring.MARCA: el parcheador descarta el NewLine que la precede y deja un espacio; el resultado esperado es
sestring.aplicar_marcas(target)), la macro <Gender>/<If> con ramas (sestring.has_reserved/split_gender; no se compara re-tokenizado, igual que evaluar_cadena) ni los
NewLine EXTRA admitidos por pgri (sestring.relax_newlines). Por entrada: forma del registro; source == tokenizacion del juego; filtro_tokens (S.validate + multiconjunto/orden con
relax_newlines); filtro_protegidos (sin la marca); source->bytes reproduce el crudo; simulate_phase_a(target) no falla; si no hay macro de genero: re-tokenizado == renumerar(expandir_colores(aplicar_marcas(target)));
si hay <Gender>: ramas validas. Uso: validar_blob_suavizado.py --blob F.dat --game DIR_0a0000 [--jobs 8] [--fallos F.tsv]. Sale 1 si hay fallos."""
import sys, os, re, json, argparse, collections, multiprocessing as mp
AQUI = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, AQUI)
import sestring as S, sestring_flat as F, zst, campos
import construir_dat as C
from sqpack_raw import Pack

ENTS = None; GAME = None

def validar(P, cache, e):
    k = e.get('sourceKey') if isinstance(e.get('sourceKey'), dict) else {}; src, tgt = str(e.get('source', '')), str(e.get('target', ''))
    if list(e.keys()) != ['source', 'target', 'sourceKey', 'status']: return 'REGISTRO', 'claves %s' % list(e.keys())
    if list(k.keys()) != ['sheet', 'rowId', 'field', 'exdPath']: return 'SOURCEKEY', 'claves %s' % list(k.keys())
    if e.get('status') not in ('approved', 'gold'): return 'STATUS', repr(e.get('status'))
    m = re.search(r'_(\d+)(?:_([a-z]+))?\.exd$', k['exdPath'] or '')
    if not m: return 'EXDPATH', k['exdPath']
    sh = k['sheet']; lang = m.group(2) or ''
    h = P.exh(sh)
    if h is None: return 'EXH', sh
    if h.get('variant') != 1 or lang not in h['langs']: return 'EXH_VARIANT_LANG', '%r %s' % (h.get('variant'), h['langs'])
    try: col = campos.field_to_col(h, k['field'], 'ordinal')
    except ValueError as ex: return 'FIELD', str(ex)
    if (sh, lang) not in cache: cache.clear(); cache[(sh, lang)] = P.rows_raw(sh, h, lang)
    rows = cache[(sh, lang)]
    if k['rowId'] not in rows: return 'FILA', str(k['rowId'])
    st, strs = rows[k['rowId']]; raw = strs[col]
    if S.tokenize_raw(raw) != src: return 'SOURCE', 'source != tokenizacion del juego'
    try:
        C.filtro_tokens(src, tgt)
        C.filtro_protegidos(src, tgt.replace(S.MARCA, ''))
    except C.Rechazo as r: return 'RECHAZO_' + r.args[0], str(r.args[1] if len(r.args) > 1 else '')[:200]
    if F.simulate_phase_a(raw, src, src)[0] != raw: return 'SOURCE_BYTES', 'source -> bytes != crudo'
    nb, via, why = F.simulate_phase_a(raw, src, tgt)
    if nb is None: return 'SIMULACION', '%s: %s' % (via, why)
    if S.has_reserved(tgt):
        marked, macros, reason = S.split_gender(tgt)
        if reason is not None or not macros: return 'GENERO', reason or 'sin macros'
    elif S.tokenize_raw(nb) != S.renumerar_newlines(S.expandir_colores_propios(S.aplicar_marcas(tgt))): return 'RETOKENIZADO', 're-tokenizado != target'
    return None

def trabajo(hojas):
    P = Pack(GAME); cache = {}; fallos = []; n = 0
    for sh in hojas:
        for e in ENTS[sh]:
            n += 1
            try: r = validar(P, cache, e)
            except Exception as ex: r = ('EXCEPCION', repr(ex)[:200])
            if r: k = e['sourceKey']; fallos.append((k['sheet'], k['rowId'], k['field'], r[0], r[1]))
    return n, fallos

def main():
    global ENTS, GAME
    ap = argparse.ArgumentParser(); ap.add_argument('--blob', required=True); ap.add_argument('--game', required=True); ap.add_argument('--jobs', type=int, default=8); ap.add_argument('--fallos'); ap.add_argument('--slice', help='i/N: solo los grupos de hojas i, i+N, ... (para lanzar N procesos independientes)')
    a = ap.parse_args(); GAME = a.game
    data = zst.decompress(open(a.blob, 'rb').read()).decode('utf-8')
    ents = [json.loads(l) for l in data.split('\n') if l.strip()]
    ENTS = collections.defaultdict(list)
    for e in ents: ENTS[e['sourceKey']['sheet']].append(e)
    hojas = sorted(ENTS, key=lambda s: -len(ENTS[s])); grupos = [[] for _ in range(a.jobs * 4)]; cargas = [0] * len(grupos)
    for s in hojas:
        i = cargas.index(min(cargas)); grupos[i].append(s); cargas[i] += len(ENTS[s])
    grupos = [g for g in grupos if g]
    tot = 0; fallos = []
    if a.slice:
        i, N = map(int, a.slice.split('/')); grupos = grupos[i::N]
        for g in grupos: n, f = trabajo(g); tot += n; fallos += f
    else:
        with mp.get_context('fork').Pool(a.jobs) as pool:
            for n, f in pool.imap_unordered(trabajo, grupos): tot += n; fallos += f
    c = collections.Counter(f[3] for f in fallos)
    print('%d entradas, %d fallos %s' % (tot, len(fallos), dict(c)))
    if a.fallos:
        with open(a.fallos, 'w', encoding='utf-8') as fo:
            for f in sorted(fallos): fo.write('\t'.join(map(str, f)) + '\n')
    sys.exit(1 if fallos else 0)
if __name__ == '__main__': main()
