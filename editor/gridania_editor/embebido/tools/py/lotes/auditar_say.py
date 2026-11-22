#!/usr/bin/env python3
"""Auditoria GLOBAL de misiones de modo «Decir»/`/say`. SOLO LECTURA sobre traducciones/ y textos/ja/.
Uso: python3 -I tools/py/lotes/auditar_say.py [--raiz /home/claude/gridania] [--salida TSV]
Salida: trabajo/informes/say_global_auditoria.tsv (hoja,row,sub,col,frase_ja,frase_es,tipo_problema,gravedad).
Deteccion (ja): celdas con modo Say/Shout/..., `『X』`, `{0x12:N}X{0x12:M}` (traduccion automatica), `合言葉…「X」`,
`「X」と入力/言う...`, o comando /say|/s|/shout|/yell|/party|/tell... Frase es: «X» precedida de verbo (escribe, di, contrasena...),
texto entre iconos de traduccion automatica, o argumento del comando.
Tipos: discrepancia_frase (1), frase_partida (2), frase_corta / sin_frase_es (3), comillas_internas (4), no_en_lista / distinta_de_lista (5).
Umbrales (3): ja_len>=6 y es_len < RATIO_CORTA*ja_len -> media; ja_len>=12 y 1 palabra -> alta; es_len<=2 con ja_len>=3 -> alta."""
import argparse, json, os, re, sys, unicodedata
from collections import Counter, defaultdict

RATIO_CORTA = 0.7
EXCLUIR = {'Addon', 'AddonTransient', 'LogFilter', 'TextCommand', 'TextCommandParam', 'HowToPage', 'VVDNotebookContents'}  # no son misiones (ejemplos de ayuda/cuaderno)
CMD = r'(?:say|s|shout|sh|yell|y|party|p|tell|t)'
RE_CMD = re.compile(r'(?:(?<=^)|(?<=[\s«»"“(\[「『]))/' + CMD + r'(?![\w/])[ \t]*([^\n«»"”」』<{\x00]*)')
RE_MODO = re.compile(r'(?:Say|Shout|Yell|Party|Tell)」?モード|チャットの会話モード|と入力|合言葉|チャット(?:で|欄)')
RE_JA = [
    ('tecleada', re.compile(r'『([^』]+)』')),
    ('auto', re.compile(r'\{0x12:37\}(.+?)\{0x12:38\}')),
    ('tecleada', re.compile(r'合言葉[^「」『』]{0,6}「([^」]+)」')),
    ('tecleada', re.compile(r'「([^「」{]+)」(?:と|を)(?:入力|言|発言|答|返事|叫|話しかけ|唱)')),
]
RE_AUTO_ES = re.compile(r'<Icon(?:#\d+)?>\d+<MacroEnd(?:#\d+)?>(.*?)<Icon(?:#\d+)?>\d+<MacroEnd(?:#\d+)?>', re.S)
RE_VERBO = re.compile(r'(escrib|teclea|introduc|contrase|clave|respond|pronunci|grit|\busa\b|\bdi\b|\bdic|conteng|contien)', re.I)
RE_TECLEA = re.compile(r'(escrib|teclea|introduc|conteng|contien)', re.I)
MODOS = {'decir', 'gritar', 'grupo', 'susurrar', 'say', 'shout', 'yell', 'party', 'tell', 'mensaje'}
INTERNAS = '«»"“”‹›'


def unir(es):
    return '\x00'.join(es) if isinstance(es, list) else (es or '')


def norm_fuerte(s):
    s = unicodedata.normalize('NFD', s.casefold())
    s = ''.join(c for c in s if unicodedata.category(c)[0] in 'LN')
    return s


def captura_balanceada(txt, ini):
    """txt[ini]=='«'. -> (contenido, fin, anidada) o None si no cierra."""
    d = 0; anid = False
    for i in range(ini, len(txt)):
        c = txt[i]
        if c == '«':
            d += 1
            if d > 1: anid = True
        elif c == '»':
            d -= 1
            if d == 0: return txt[ini + 1:i], i, anid
    return None


def frases_es(txt, kinds):
    """-> lista de (kind, frase, flags) segun los kinds ja de la celda, emparejados en orden."""
    out = []
    n_t = sum(1 for k in kinds if k == 'tecleada'); n_a = sum(1 for k in kinds if k == 'auto')
    autos = [m.group(1) for m in RE_AUTO_ES.finditer(txt)]
    cands = []; todas = []; fuertes = []
    i = 0
    while True:
        i = txt.find('«', i)
        if i < 0: break
        cap = captura_balanceada(txt, i)
        if cap is None:
            if RE_VERBO.search(txt[max(0, i - 30):i]): cands.append((txt[i + 1:], True, False))
            break
        cont, fin, anid = cap
        if cont.strip().casefold() not in MODOS and not cont.startswith('<Sheet'):
            todas.append((cont, False, anid))
            if RE_VERBO.search(txt[max(0, i - 30):i]): cands.append((cont, False, anid))
            if RE_TECLEA.search(txt[max(0, i - 30):i]): fuertes.append((cont, False, anid))
        i = fin + 1
    if fuertes: cands = fuertes
    if not cands and todas: cands = todas[-max(1, n_t):]
    return cands, autos


def filas(ruta):
    if not os.path.exists(ruta): return {}
    d = {}
    for l in open(ruta, encoding='utf-8').read().split('\n'):
        l = l.strip()
        if not l: continue
        j = json.loads(l); d[(j['row'], j.get('sub'), j['col'])] = j
    return d


def analizar_hoja(hoja, ja, es):
    """-> lista de apariciones: dict(key, kind, fja, fes, flags, clave(bool))."""
    ap = []
    triggers = {}
    for k, j in ja.items():
        t = j.get('text') or ''
        if not t or t.startswith('TEXT_'): continue
        kinds = []
        for kind, rx in RE_JA:
            for m in rx.finditer(t): kinds.append((kind, m.group(1)))
        cm = RE_CMD.search(t)
        if cm: kinds.append(('cmd', '/' + cm.group(0).split()[0].lstrip('/') + (' ' + cm.group(1).strip() if cm.group(1).strip() else '')))
        kinds = list(dict.fromkeys(kinds))  # una misma frase detectada por dos patrones cuenta una vez
        if kinds and (RE_MODO.search(t) or cm):
            triggers[k] = kinds
    claves = defaultdict(list)  # (kind) ja_frase -> celdas clave
    frases_ja = {f for ks in triggers.values() for kd, f in ks if kd != 'cmd'}
    # Una celda clave puede diferir de la frase citada solo en la puntuacion FINAL ([！？。!?]; la clave ja suele omitir ！).
    # Una celda con ！/？ final que la cita NO lleva es una replica hablada, no la clave (la clave es la forma sin signos).
    # Las lineas habladas con elipsis o alargamientos (海兵魂……！！, 海兵魂ぃぃ！！) NO son claves.
    recorta = lambda x: re.sub(r'[！？。!?]+$', '', x)
    frases_ja_n = {recorta(f) for f in frases_ja}
    for k, j in ja.items():
        t = (j.get('text') or '').strip()
        if k in triggers or not t or len(t) > 40: continue
        if t in frases_ja: claves[k] = t
        elif recorta(t) == t and t in frases_ja_n and t and not re.search(r'[…、。！？]', recorta(t)):
            claves[k] = next(f for f in sorted(frases_ja) if recorta(f) == recorta(t))  # se agrupa con la frase citada
    for k, kinds in triggers.items():
        e = es.get(k)
        txt = unir(e['es']) if e else ''
        cands, autos = frases_es(txt, [kd for kd, _ in kinds])
        nt = sum(1 for kd, _ in kinds if kd == 'tecleada')
        if len(cands) > nt: cands = cands[len(cands) - nt:]
        ci = ai = 0
        for kind, fja in kinds:
            if kind == 'auto':
                fes = autos[ai] if ai < len(autos) else None; ai += 1
                ap.append(dict(key=k, kind='auto', fja=fja, fes=fes, flags=set()))
            elif kind == 'tecleada':
                if ci < len(cands):
                    c, sin_cerrar, anid = cands[ci]; ci += 1
                    fl = set()
                    if anid: fl.add('comillas_internas')
                    if sin_cerrar: fl.add('comilla_sin_cerrar')
                    ap.append(dict(key=k, kind='tecleada', fja=fja, fes=c, flags=fl))
                else:
                    ap.append(dict(key=k, kind='tecleada', fja=fja, fes=None, flags=set()))
            else:  # cmd
                m = RE_CMD.search(txt)
                if m: ap.append(dict(key=k, kind='cmd', fja=fja, fes='/' + m.group(0).split()[0].lstrip('/') + (' ' + m.group(1).strip() if m.group(1).strip() else ''), flags=set()))
                else: ap.append(dict(key=k, kind='cmd', fja=fja, fes=None, flags=set()))
    for k, fj in claves.items():
        e = es.get(k)
        ap.append(dict(key=k, kind='tecleada', fja=fj, fes=unir(e['es']).replace('\x00', '') if e else None, flags=set(), clave=True))
    return ap


def solo_signos(a, b):
    return norm_fuerte(a) == norm_fuerte(b)


def auditar_hoja(hoja, ja, es, listas):
    ap = analizar_hoja(hoja, ja, es)
    res = []
    comp = listas.get('completion', {})
    def add(a, tipo, grav, fes=None):
        k = a['key']
        res.append((hoja, k[0], '' if k[1] is None else k[1], k[2], a['fja'], a['fes'] if fes is None else fes, tipo, grav))
    grupos = defaultdict(list)
    for a in ap: grupos[(a['kind'], a['fja'])].append(a)
    for (kind, fja), lst in grupos.items():
        tec = [a for a in lst if not a.get('clave') and a['fes'] is not None]
        if kind == 'auto':  # el selector de frases automaticas muestra el texto de la hoja Completion (col 3)
            for a in lst:
                if a['fes'] is not None and a['fja'] in comp and comp[a['fja']] != a['fes']:
                    add(a, 'auto_distinta_de_completion', 'alta', a['fes'] + ' != ' + comp[a['fja']])
        if kind == 'tecleada' and hoja in listas['frases']:  # la celda clave aislada manda: la lista debe contenerla (signos incluidos)
            for a in lst:
                if a.get('clave') and a['fes'] and not any(a['fes'].casefold() in f.casefold() for f in listas['frases'][hoja]):
                    add(a, 'clave_no_en_lista', 'alta')
        for a in lst:
            if a['fes'] is None and not a.get('clave'):
                add(a, 'sin_frase_es', 'alta'); continue
            fes = a['fes']
            if fes is None: continue
            if '\x00' in fes or '\n' in fes or '<NewLine' in fes:
                add(a, 'frase_partida', 'alta', fes.replace('\x00', '|').replace('\n', '\\n'))
                a['fes'] = fes = fes.replace('\x00', ' ').replace('\n', ' ')
            if 'comillas_internas' in a['flags'] or (kind != 'cmd' and any(c in fes for c in INTERNAS)):
                add(a, 'comillas_internas', 'alta')
            if 'comilla_sin_cerrar' in a['flags']:
                add(a, 'comilla_sin_cerrar', 'alta')
            if kind != 'cmd':
                jl = len(re.sub(r'[。、！？!?…\s]', '', fja)); el = len(fes.strip())
                nw = len(fes.split())
                if jl >= 3 and el <= 2: add(a, 'frase_corta', 'alta')
                elif jl >= 12 and nw <= 1: add(a, 'frase_corta', 'alta')
                elif jl >= 6 and el < RATIO_CORTA * jl: add(a, 'frase_corta', 'media')
        if len(tec) >= 1:
            canon = Counter(a['fes'] for a in tec).most_common(1)[0][0]
            for a in lst:
                if a['fes'] is None or a['fes'] == canon: continue
                if a.get('clave') and re.sub(r'[¡!¿?.…,;]', '', a['fes']).strip() == re.sub(r'[¡!¿?.…,;]', '', canon).strip():
                    add(a, 'discrepancia_frase', 'baja'); continue
                add(a, 'discrepancia_frase', 'media' if solo_signos(a['fes'], canon) else 'alta')
            if kind != 'cmd':
                if hoja not in listas['hojas']:
                    if hoja not in listas['menu']: add(tec[0], 'no_en_lista', 'baja', canon)
                else:
                    ref = listas['texto'].get(hoja, '').casefold()
                    if canon.casefold() not in ref and canon.strip('¡!¿?.… ').casefold() not in ref:
                        add(tec[0], 'distinta_de_lista', 'baja', canon)
    return res


def leer_tsv(p):
    if not os.path.exists(p): return []
    f = [l.split('\t') for l in open(p, encoding='utf-8').read().split('\n') if l.strip()]
    return [dict(zip(f[0], c)) for c in f[1:]]


def cargar_listas(raiz):
    """Listas por NOMBRE de columna (frases_a_escribir: frase_exacta; canonicas: frase_canonica; menu: contrasenas que se eligen en un menu)
    + hoja Completion (texto del selector de traduccion automatica)."""
    hojas, texto, frases = set(), defaultdict(str), defaultdict(list)
    inf = os.path.join(raiz, 'trabajo', 'informes')
    for fn, col in (('frases_a_escribir.tsv', 'frase_exacta'), ('frases_say_canonicas.tsv', 'frase_canonica')):
        for r in leer_tsv(os.path.join(inf, fn)):
            h, f = r.get('hoja', ''), r.get(col, '')
            if not h: continue
            hojas.add(h); texto[h] += ' ' + f; frases[h].append(f)
    menu = {r['hoja'] for r in leer_tsv(os.path.join(inf, 'frases_say_menu.tsv')) if r.get('hoja')}
    comp = {}
    cj, ce = os.path.join(raiz, 'textos', 'ja', 'Completion.jsonl'), os.path.join(raiz, 'traducciones', 'Completion.jsonl')
    if os.path.exists(cj) and os.path.exists(ce):
        jj, ee = filas(cj), filas(ce)
        for (r, sub, c), j in jj.items():
            if c == 3 and (r, sub, c) in ee: comp[j.get('text')] = unir(ee[(r, sub, c)]['es'])
    return {'hojas': hojas, 'texto': dict(texto), 'frases': dict(frases), 'menu': menu, 'completion': comp}


def expansiones(raiz):
    m = {}
    p = os.path.join(raiz, 'trabajo', 'informes', 'expansion_historia.tsv')
    if os.path.exists(p):
        for l in open(p, encoding='utf-8').read().split('\n')[1:]:
            c = l.split('\t')
            if len(c) > 1: m[c[0]] = c[1]
    return m


def exp_de(hoja, m):
    if hoja in m: return m[hoja]
    return hoja.split('/')[0] if '/' in hoja else 'hoja_raiz'


def run(raiz, salida):
    listas = cargar_listas(raiz); exps = expansiones(raiz)
    base_es = os.path.join(raiz, 'traducciones'); base_ja = os.path.join(raiz, 'textos', 'ja')
    todo = []
    for d, _, fs in os.walk(base_es):
        for f in fs:
            if not f.endswith('.jsonl'): continue
            hoja = os.path.relpath(os.path.join(d, f), base_es)[:-6].replace(os.sep, '/')
            if hoja in EXCLUIR: continue
            rj = os.path.join(base_ja, hoja + '.jsonl')
            if not os.path.exists(rj): continue
            ja = filas(rj)
            if not any(RE_MODO.search(j.get('text') or '') or '/' in (j.get('text') or '') or '{0x12:' in (j.get('text') or '') for j in ja.values()): continue
            todo += auditar_hoja(hoja, ja, filas(os.path.join(d, f)), listas)
    todo.sort(key=lambda r: (r[0], r[1], str(r[2]), r[3], r[6]))
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    with open(salida, 'w', encoding='utf-8') as o:
        o.write('hoja\trow\tsub\tcol\tfrase_ja\tfrase_es\ttipo_problema\tgravedad\n')
        for r in todo: o.write('\t'.join('' if x is None else str(x).replace('\t', ' ').replace('\n', '\\n') for x in r) + '\n')
    cnt = Counter((r[6], exp_de(r[0], exps)) for r in todo)
    return todo, cnt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raiz', default=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
    ap.add_argument('--salida')
    a = ap.parse_args()
    salida = a.salida or os.path.join(a.raiz, 'trabajo', 'informes', 'say_global_auditoria.tsv')
    todo, cnt = run(a.raiz, salida)
    por_tipo = Counter(r[6] for r in todo); por_exp = Counter(k[1] for k in cnt.elements())
    print('total', len(todo), '| tipo', dict(por_tipo), '| expansion', dict(por_exp))


if __name__ == '__main__':
    main()
