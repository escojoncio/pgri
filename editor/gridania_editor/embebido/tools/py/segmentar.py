#!/usr/bin/env -S python3 -I
"""Segmentacion de cadenas japonesas para proteger los marcadores (SeString).

Entrada de las funciones: la forma TOKENIZADA de sestring.py (`<NewLine>`, `<NewLine#2>`, `<If>`..., `<<` = `<` literal).
Desde el volcado de textos/ja (`{0xTT:hex}`, o `raw` en hex) se llega a ella con `tokenizar_volcado(text, raw)`.

- "simple": los unicos marcadores son separadores de posicion fija, sin caracteres de control ni `raw`: saltos de linea
  (`<NewLine>`), color (`<ColorType>`, `<EdgeColorType>`: apertura y cierre), icono (`<Icon2>`) y numero (`<Num>`, `<Kilo>`), cada uno con
  su sufijo `#N`. Se parte en trozos de texto puro (sin escapes) y separadores (los tokens tal cual, mismo orden). El traductor solo ve/escribe
  trozos. Siempre len(trozos) == len(separadores)+1; un trozo entre dos separadores adyacentes (o en un extremo) es '' y se CONSERVA
  (1:1 con los separadores); su `es` puede ir vacio (TROZO_VACIO solo exige texto si el trozo japones lleva letras).
  Una macro de color/icono/numero con texto dentro (<MacroEnd>) no es simple.
- "complejo": cualquier otro marcador (If, Italic, Split, Sheet/Run, MacroEnd...), caracteres de control o datos `raw`. No se trocea: el traductor
  recibe la cadena tokenizada entera y se aplica el filtro de tokens (construir_dat.py).
- Compatibilidad: `clasificar(..., solo_nl=True)` aplica la regla anterior (solo NewLine). Las cadenas que solo son simples por la ampliacion
  (color/icono/numero) pueden llevar `es` heredado como cadena tokenizada (ver construir_dat.evaluar_cadena); el hash `h` no cambia.

CLI (entrada para el traductor): python3 -I segmentar.py --sheet <hoja> [--rows A-B] [--textos DIR] [--out f.jsonl]
  -> una linea por cadena: {"hoja","row","sub","col","h","tipo","ja"[,"sep"]}; `ja` = lista de trozos (simple) o cadena tokenizada (complejo);
     `sep` (solo si algun separador no es NewLine) = separadores entre trozos, para que el traductor sepa que hay entre ellos."""
import sys, os, re, json, hashlib, unicodedata, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sestring as S
from extract_ja import se_decode

NL_RE = re.compile(r'<NewLine(?:#[0-9]+)?>\Z')
# separadores admitidos en cadenas simples: NewLine + color (ColorType/EdgeColorType) + icono (Icon2) + numero (Num/Kilo)
SEP_RE = re.compile(r'<(?:NewLine|ColorType|EdgeColorType|Icon2|Num|Kilo)(?:#[0-9]+)?>\Z')
# kana, kanji, hangul, signos CJK y formas de ancho completo/medio ancho (escapes \u: sin literales CJK en el codigo)
CJK_RE = re.compile('[\u1100-\u11ff\u2e80-\u2fdf\u3000-\u303f\u3040-\u30ff\u3100-\u312f\u3190-\u31ff\u3200-\u33ff'
                    '\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff5d\uff5f-\uffef]|[\U00020000-\U0002fa1f]')
MARCADOR_RE = re.compile(r'<[A-Za-z][A-Za-z0-9]*(?:#[0-9]+)?>|\{0x[0-9A-Fa-f]{2}')

def hash_ja(text):
    """sha1 del campo `text` de textos/ja (UTF-8), 12 hex"""
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]

def bytes_ja(text, raw=None):
    """bytes del juego a partir del volcado (`raw` hex es la fuente de verdad si existe)"""
    return bytes.fromhex(raw) if raw else se_decode(text)

def tokenizar_volcado(text, raw=None):
    """volcado de textos/ja -> cadena tokenizada (la misma que ExdPatcher/SeStringTreeTokenizer)"""
    return S.tokenize_raw(bytes_ja(text, raw))

def es_control(c):
    return unicodedata.category(c) in ('Cc', 'Zl', 'Zp') or c in '￹￺￻'

def hay_control(t):
    return any(es_control(c) for c in t)

def es_simbolos(t):
    """True si el texto no lleva letras (solo simbolos, numeros, puntuacion o espaciado)"""
    return not any(unicodedata.category(c).startswith('L') for c in t)

def vacio_permitido(j):
    """True si un trozo `es` vacio es valido para el trozo japones `j`: sin letras (simbolos) o con <=2 letras y todas CJK/kana (particulas o contadores: を, が, 日, 層, 個)"""
    if es_simbolos(j): return True
    letras = [c for c in j if unicodedata.category(c).startswith('L')]
    return len(letras) <= 2 and all(CJK_RE.search(c) for c in letras)

def tiene_cjk(t):
    # OJO: kana/kanji/anchura completa de CJK_RE. Una celda cuyo ja es SOLO signos japoneses («…………。», «……！», «！？») NO tiene letras CJK pero SI se ve en japones
    # si no se traduce (。！？ de anchura completa): no darlas por «no traducibles»; se convierten con tools/py/lotes/traducir_solo_signos.py (ver bitacora, lecciones).
    return CJK_RE.search(t) is not None

NL_TOK_RE = re.compile(r'<NewLine(?:#[0-9]+)?>')
GEN_TOK_RE = re.compile(r'<Gender>|<GenderElse>|<GenderEnd>')   # macro de genero del jugador (pgri SeStringStandardMacros): se escribe tal cual dentro de un trozo
KEEP_TOK_RE = re.compile(NL_TOK_RE.pattern + '|' + GEN_TOK_RE.pattern)

def escapar(t):
    """'<' -> '<<', salvo los tokens <NewLine>/<NewLine#N> escritos en un trozo (NewLine EXTRA admitido por el parcheador) y los delimitadores
    <Gender>/<GenderElse>/<GenderEnd> (macro de genero del jugador): quedan como token"""
    out = []; prev = 0
    for m in KEEP_TOK_RE.finditer(t):
        out.append(t[prev:m.start()].replace('<', '<<')); out.append(m.group(0)); prev = m.end()
    out.append(t[prev:].replace('<', '<<')); return ''.join(out)

def _partir(tok, solo_nl=False):
    """-> (trozos_escapados, separadores) partiendo por los separadores (NewLine, color, icono, numero; solo NewLine con solo_nl);
    ValueError si hay otro marcador"""
    rx = NL_RE if solo_nl else SEP_RE
    atoms = S._atoms(tok); trozos = []; seps = []; prev = 0
    for t, p in atoms:
        if not rx.match(t): raise ValueError('marcador no simple: ' + t)
        trozos.append(tok[prev:p]); seps.append(t); prev = p + len(t)
    trozos.append(tok[prev:])
    return trozos, seps

def clasificar(tok, raw=False, solo_nl=False):
    """-> 'simple' | 'complejo'. solo_nl=True: regla anterior (unico separador NewLine)"""
    if raw: return 'complejo'
    try: tr, seps = _partir(tok, solo_nl)
    except ValueError: return 'complejo'
    if any(hay_control(t) for t in tr): return 'complejo'
    # sin '<' suelto: lo que queda tras quitar '<<' no puede tener '<'
    if any('<' in t.replace('<<', '') for t in tr): return 'complejo'
    if len(set(seps)) != len(seps): return 'complejo'
    if recomponer(seps, [t.replace('<<', '<') for t in tr]) != tok: return 'complejo'
    return 'simple'

def trocear(src):
    """cadena tokenizada simple -> (trozos, separadores). len(separadores) == len(trozos)-1. Trozos sin escapes ('<' literal)."""
    if clasificar(src) != 'simple': raise ValueError('cadena no simple')
    tr, seps = _partir(src)
    return [t.replace('<<', '<') for t in tr], seps

def recomponer(separadores, trozos_es):
    """inversa de trocear: intercala separadores y escapa '<' -> '<<' en los trozos"""
    if len(trozos_es) != len(separadores) + 1:
        raise ValueError('se esperaban %d trozos, hay %d' % (len(separadores) + 1, len(trozos_es)))
    out = []
    for i, t in enumerate(trozos_es):
        out.append(escapar(t))
        if i < len(separadores): out.append(separadores[i])
    return ''.join(out)

def leer_ja(root, hoja, textos='textos'):
    """textos/ja/<hoja>.jsonl (+ _partNN) -> {(row,sub,col): (text, raw|None)}; None si no existe"""
    base = os.path.join(root, textos, 'ja', hoja)
    paths = [base + '.jsonl'] if os.path.exists(base + '.jsonl') else []
    n = 1
    while os.path.exists('%s_part%02d.jsonl' % (base, n)): paths.append('%s_part%02d.jsonl' % (base, n)); n += 1
    if not paths: return None
    res = {}
    for p in paths:
        with open(p, encoding='utf-8') as f:
            for l in f:
                if l.strip():
                    j = json.loads(l); res[(j['row'], j['sub'], j['col'])] = (j['text'], j.get('raw'))
    return res

def preparar(root, hoja, rows=None, textos='textos'):
    """genera los registros de entrada para el traductor"""
    ja = leer_ja(root, hoja, textos)
    if ja is None: raise SystemExit('sin textos/ja/%s.jsonl' % hoja)
    for (row, sub, col), (text, raw) in sorted(ja.items(), key=lambda kv: (kv[0][0], -1 if kv[0][1] is None else kv[0][1], kv[0][2])):
        if rows is not None and row not in rows: continue
        tok = tokenizar_volcado(text, raw)
        simple = clasificar(tok, raw=bool(raw)) == 'simple'
        reg = {'hoja': hoja, 'row': row, 'sub': sub, 'col': col, 'h': hash_ja(text), 'tipo': 'simple' if simple else 'complejo'}
        if simple:
            tr, seps = trocear(tok); reg['ja'] = tr
            if not all(NL_RE.match(x) for x in seps): reg['sep'] = seps
        else: reg['ja'] = tok
        yield reg

def _rango(s):
    ids = set()
    for p in s.split(','):
        if '-' in p: a, b = p.split('-'); ids.update(range(int(a), int(b) + 1))
        else: ids.add(int(p))
    return ids

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', required=True); ap.add_argument('--rows'); ap.add_argument('--out')
    ap.add_argument('--root', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
    a = ap.parse_args()
    out = open(a.out, 'w', encoding='utf-8', newline='\n') if a.out else sys.stdout
    for r in preparar(a.root, a.sheet, _rango(a.rows) if a.rows else None):
        out.write(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n')
if __name__ == '__main__': main()
