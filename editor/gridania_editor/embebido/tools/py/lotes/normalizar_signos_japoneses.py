#!/usr/bin/env -S python3 -I
"""Normaliza a UTF-8 espanol/ASCII TODO signo japones / de anchura completa / puntuacion CJK que aparezca en el `es` (norma del propietario 2026-11-05:
el proyecto es UTF-8 y no hay signos de anchura completa en el espanol; ～ -> ~).
Tabla determinista (ver TABLA y normalizar_trozo): ～〜->~  ！->!  ？->?  。->.  、->,  ：->:  ；->;  （）->()  ［］->[]  【】->[]  「」『』〈〉《》->«»  ・->·
＝＋，．－／％＆＃＊＠＄ etc -> ASCII; digitos y letras de anchura completa -> ASCII; U+3000 -> espacio; ー -> repite la vocal anterior (o se suprime); halfwidth katakana .｡､｢｣･ -> ASCII.
Respeta la simbologia 1:1: al convertir ！/？ en un trozo sin apertura ¡/¿ se antepone la apertura al inicio de la oracion. NO toca tokens `<...>` ni `{0x..:..}` (Raw, PUA, URLs fuera de alcance) ni ♪★♥.
Tambien: U+2015 (horizontal bar, solo o en secuencias ――) y U+2500 (─) -> '—' (U+2014), uno a uno.
ALLOWLIST (orden 2026-11-05): en el es solo se admiten ASCII, letras/signos espanoles (aeiouu n ¡ ¿ « » … ª º) y los caracteres NO CJK/anchura completa que aparecen en el FRANCES real (allowlist_fr.txt,
censo de /tmp/gr_fr/fr hecho con extract_lang.py; incluye ※ ■ ● ◆ ☆ “ ” × → – ° º ★ ♪ ♥ ...; se excluye ― porque el propietario manda convertirlo). Fuera de la allowlist: la tabla convierte
― ─ -> —, ‐ -> -, numerales romanos Ⅰ-ⅿ -> letras (NFKC), vocales con macron -> circunfleja como hace el fr (Hôô, dogû, ôkabuto). Criterio fr copiado: † se conserva (decision del propietario; en ES_EXTRA), ⑥⑦ -> '6.' '7.', ・ -> '-', ¥ -> '$', ← -> '<-', θ -> 'Theta', ı -> i, subindices -> digitos. ª se mantiene (ordinal espanol). Carga binaria `<Raw>Ë\\u0001` (id de objeto) protegida; ɗɵܵɡ de ActionTransient exentos Los C0 de ActionTransient son marcadores de control: nunca se sustituyen. --medir informa tambien de los caracteres fuera de la allowlist.
API: normalizar(es) -> mismo tipo (str o lista de str); normalizar_trozo(str). Modos CLI: --medir | --dry-run | --escribir [--hojas H1,H2] [--prefijo P] (flock /tmp/gridania_trad.lock, relee cada hoja
antes de escribir, reemplazo textual por linea: mismo h/origen/estado, formato byte a byte). Uso: python3 -I tools/py/lotes/normalizar_signos_japoneses.py --medir"""
import sys, os, re, json, glob, argparse, collections, unicodedata
AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, '..', '..', '..'))
TOK = re.compile(r'(<[^<>]*>|\{0x[0-9A-Fa-f]{2}:[^}]*\})')
_IF_RE = re.compile(r'<If>')
_ME_RE = re.compile(r'<MacroEnd(#\d+)?>')

_RAWTOK = re.compile(r'<Raw(#\d+)?>')
def _raw_payload(ps):
    """`<Raw>` seguido de texto corto con bytes de control (p. ej. `<Raw>Ë\u0001<MacroEnd>`, id de objeto) es carga binaria: se funde en el token protegido."""
    out = []; i = 0
    while i < len(ps):
        if i % 2 and _RAWTOK.fullmatch(ps[i]) and i + 1 < len(ps) and len(ps[i + 1]) <= 6 and re.search(r'[\x00-\x1f]', ps[i + 1]):
            out.append(ps[i] + ps[i + 1]); out.append(''); i += 2; continue
        out.append(ps[i]); i += 1
    return out

def partes(t):
    """TOK.split(t) pero con cada bloque macro crudo `<If>...<MacroEnd#N>` (literales de rama en bytes, p. ej. «Item» y de CmnDefRelicWeapon050Trade_00221; ya en simbolos españoles, con longitudes calculadas a mano) fundido en UN solo elemento protegido
    (indice impar): su texto no se normaliza ni se cuenta como espanol; no se toca (las longitudes codificadas dependen de sus bytes; ver test_relic050_macro.py)."""
    ps = TOK.split(t)
    ps = _raw_payload(ps)
    if '<If>' not in t: return ps
    out = []; i = 0
    while i < len(ps):
        if i % 2 and ps[i] == '<If>':
            fin = i
            for k in range(i, len(ps), 2):
                if _ME_RE.fullmatch(ps[k]): fin = k
                if k > i and ps[k] == '<If>': break
            out.append(''.join(ps[i:fin + 1])); i = fin + 1
            continue
        out.append(ps[i]); i += 1
    # el indice de paridad se conserva: texto, token(protegido), texto...
    return out

ESPECIAL = {
    '～': '~', '〜': '~', '！': '!', '？': '?', '。': '.', '、': ',', '，': ',', '．': '.', '：': ':', '；': ';', '（': '(', '）': ')', '［': '[', '］': ']', '｛': '{', '｝': '}',
    '【': '[', '】': ']', '〔': '[', '〕': ']', '「': '«', '」': '»', '『': '«', '』': '»', '〈': '«', '〉': '»', '《': '«', '》': '»', '＜': '‹', '＞': '›',
    '＝': '=', '＋': '+', '－': '-', '／': '/', '％': '%', '＆': '&', '＃': '#', '＊': '*', '＠': '@', '＄': '$', '￥': '¥', '￡': '£', '￠': '¢', '＼': '/', '＾': '^', '＿': '_', '｀': '`', '｜': '|',
    '＂': '"', '＇': "'", '　': ' ', '・': '-', '·': '-', '¥': '$', '←': '<-', 'θ': 'Theta', 'Ë': 'E', 'ı': 'i', '⑥': '6.', '⑦': '7.', '₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4', '₅': '5', '₆': '6', '₇': '7', '₈': '8', '₉': '9', '･': '-', '〃': '"', '〆': '', '〇': 'O', '々': '', '〒': '', '〓': '',
    '\u2015': '\u2014', '\u2500': '\u2014', '\u2010': '-', 'ō': 'ô', 'Ō': 'Ô', 'ū': 'û', 'Ū': 'Û', 'ā': 'â', 'Ā': 'Â', 'ē': 'ê', 'Ē': 'Ê', 'ī': 'î', 'Ī': 'Î', '｡': '.', '､': ',', '｢': '«', '｣': '»', '～': '~', '￣': '~', '￤': '|', '￦': '₩', '￢': '¬', '￨': '|', '￩': '<', '￪': '^', '￫': '>', '￬': 'v',
}
VOCAL = {'a': 'a', 'e': 'e', 'i': 'i', 'o': 'o', 'u': 'u', 'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'A': 'a', 'E': 'e', 'I': 'i', 'O': 'o', 'U': 'u'}

def _mapa(c):
    if c in ESPECIAL: return ESPECIAL[c]
    o = ord(c)
    if 0x2160 <= o <= 0x217F: return unicodedata.normalize('NFKC', c)    # numerales romanos
    if 0xFF01 <= o <= 0xFF5E: return chr(o - 0xFEE0)    # letras, digitos y signos ASCII de anchura completa
    return None

def _sin_tokens(t, f):
    return ''.join(p if (i % 2) else f(p) for i, p in enumerate(partes(t)))

# PUNTOS SUSPENSIVOS (orden del propietario 2026-11-08): SIEMPRE tres puntos ASCII `...`, nunca U+2026 (…) ni U+2025 (‥) ni mas de tres. Toda racha de [.…‥] con algun … o ‥ -> `...`; `.{4,}` -> `...`.
ELIPSIS = re.compile(r'[.…‥]*[…‥][.…‥]*|\.{4,}')

def _conv(p):
    out = []
    for c in p:
        if c == 'ー' or c == 'ｰ':
            ant = out[-1] if out else ''
            out.append(VOCAL.get(ant, '')); continue
        m = _mapa(c); out.append(c if m is None else m)
    return ELIPSIS.sub('...', ''.join(out)) if ('…' in p or '‥' in p or '....' in p) else ''.join(out)

def _aperturas(orig, nuevo):
    """tras convertir ！/？ de un trozo: si el trozo no tiene ningun ¡ (o ¿) se antepone la apertura al inicio de la oracion de cada ! (o ?) convertida"""
    for fw, op, cl in (('！', '¡', '!'), ('？', '¿', '?')):
        if fw not in orig or op in nuevo: continue
        # inicio de la oracion del primer cierre convertido
        m = re.search(r'(?<![!?])[%s]' % cl, nuevo)
        if not m: continue
        i = m.start(); ini = 0
        for mm in re.finditer(r'[.!?…\n](?=\s|[«"¡¿(]|$)', nuevo[:i]): ini = mm.end()
        while ini < i and nuevo[ini] in ' \n': ini += 1
        nuevo = nuevo[:ini] + op + nuevo[ini:]
    return nuevo

def normalizar_trozo(t):
    if not isinstance(t, str) or t.isascii(): return t
    out = ''.join(p if (i % 2) else _conv(p) for i, p in enumerate(partes(t)))
    if out == t: return t
    sin = _sin_tokens(t, lambda x: x)
    return _aperturas(sin, out) if ('！' in sin or '？' in sin) else out

def normalizar(es):
    """str o lista de str -> mismo tipo; idempotente; sin cambios devuelve el mismo objeto"""
    if isinstance(es, list):
        n = [normalizar_trozo(x) for x in es]; return es if n == es else n
    return normalizar_trozo(es)

def _raros(t):
    s = _sin_tokens(t, lambda x: x); out = []
    for c in s:
        if c in '♪★♥': continue
        o = ord(c)
        if c in '…‥': out.append(c); continue
        if unicodedata.east_asian_width(c) in 'WFH' or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF: out.append(c)
    return out

ES_EXTRA = set('áéíóúüñÁÉÍÓÚÜÑ¡¿«»ªº♪★♥†')   # sin … (2026-11-08: ERROR)
def _cargar_allow():
    try: return set(open(os.path.join(AQUI, 'allowlist_fr.txt'), encoding='utf-8').read().strip('\n')) | ES_EXTRA
    except OSError: return set(ES_EXTRA)
ALLOW = _cargar_allow()
CTRL_AT = set('ɗɵܵɡ')    # marcadores de control de ActionTransient (nunca se sustituyen)

def fuera_allowlist(t):
    """caracteres del es (sin tokens) fuera de ASCII/allowlist; ignora C0/C1 y PUA"""
    out = []
    for c in ''.join(partes(t)[0::2]):
        o = ord(c)
        if o < 0xA0 or 0xE000 <= o <= 0xF8FF or c in ALLOW or c in CTRL_AT or c == '\n': continue
        out.append(c)
    return out

def celdas(prefijo='', hojas=None):
    for f in sorted(glob.glob(RAIZ + '/traducciones/**/*.jsonl', recursive=True)):
        rel = f[len(RAIZ) + len('/traducciones/'):-6]
        if hojas and rel not in hojas: continue
        if prefijo and not rel.startswith(prefijo): continue
        yield rel, f

def _flock():
    import fcntl
    fh = open('/tmp/gridania_trad.lock', 'a'); fcntl.flock(fh, fcntl.LOCK_EX); return fh

def procesar_hoja(f, escribir):
    """-> (celdas_cambiadas, residuo[(row,sub,col,chars)]). Relee y escribe con el flock tomado por el llamador."""
    with open(f, encoding='utf-8', newline='') as fh: txt = fh.read()
    lineas = txt.split('\n'); cam = 0; res = []; sal = []
    for l in lineas:
        if l and not l.isascii():
            try: d = json.loads(l)
            except Exception: sal.append(l); continue
            es = d.get('es'); ne = normalizar(es)
            if ne != es:
                # reemplazo textual de la serializacion de `es`: mismo formato que el resto de la linea
                ant = json.dumps(es, ensure_ascii=False, separators=(',', ':')); nue = json.dumps(ne, ensure_ascii=False, separators=(',', ':'))
                if l.count('"es":' + ant) == 1: l2 = l.replace('"es":' + ant, '"es":' + nue)
                else: d['es'] = ne; l2 = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
                l = l2; cam += 1
            r = _raros(' '.join(ne) if isinstance(ne, list) else (ne or ''))
            if r: res.append((d['row'], d.get('sub'), d['col'], ''.join(sorted(set(r)))))
        sal.append(l)
    if escribir and cam:
        tmp = f + '.tmp_norm'
        with open(tmp, 'w', encoding='utf-8', newline='') as fh: fh.write('\n'.join(sal))
        os.replace(tmp, f)
    return cam, res

def main():
    ap = argparse.ArgumentParser(); g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--medir', action='store_true'); g.add_argument('--dry-run', action='store_true'); g.add_argument('--escribir', action='store_true')
    ap.add_argument('--hojas', default=''); ap.add_argument('--prefijo', default=''); ap.add_argument('--tsv', help='escribe aqui el residuo (hoja,row,sub,col,chars)')
    a = ap.parse_args(); hs = set(a.hojas.split(',')) if a.hojas else None
    cam = 0; resid = []; cnt = collections.Counter(); fuera = collections.Counter(); fh = _flock() if a.escribir else None
    try:
        for rel, f in celdas(a.prefijo, hs):
            if a.medir:
                for l in open(f, encoding='utf-8'):
                    if l.strip() and not l.isascii():
                        d = json.loads(l); es = d.get('es'); t = ' '.join(es) if isinstance(es, list) else (es or '')
                        r = set(_raros(t))
                        for c in r: cnt[c] += 1
                        for c in set(fuera_allowlist(t)): fuera[c] += 1
                        if r: cam += 1; resid.append((rel, d['row'], d.get('sub'), d['col'], ''.join(sorted(r))))
            else:
                c, r = procesar_hoja(f, a.escribir); cam += c
                for x in r: resid.append((rel,) + x)
    finally:
        if fh: fh.close()
    if a.medir: print('celdas con signos japoneses:', cam, dict(cnt)); print('celdas por caracter fuera de la allowlist:', dict(fuera))
    else: print(('escritas' if a.escribir else 'cambiarian'), cam, 'celdas; residuo', len(resid))
    if a.tsv:
        with open(a.tsv, 'w', encoding='utf-8', newline='\n') as o:
            o.write('hoja\trow\tsub\tcol\tcaracteres\n')
            for r in resid: o.write('\t'.join('' if x is None else str(x) for x in r) + '\n')
    return 0

if __name__ == '__main__': sys.exit(main())
