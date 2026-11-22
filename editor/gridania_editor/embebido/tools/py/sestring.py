"""Port a Python de SeStringTree / SeStringTreeTokenizer / SeStringStandardMacros /
SeStringCompatibilityValidator (vendor/XivSpanish.GameData). Trabaja con bytes/str; los
caracteres de control C0 viajan como chars de str (igual que en C#)."""
import re

START, END, NUL, RUN = 0x02, 0x03, 0x00, 0xFF

# nodos: ('lit', str) ('mac', code, children, lenmarker) ('opq', bytes) ('raw', int) ('run', children, marker)
KIND_NAMES = {0x10:'NewLine',0x20:'Num',0x08:'If',0x09:'Switch',0x28:'Sheet',0x29:'String',0x31:'EnNoun',
 0x32:'Split',0x2B:'Head',0x2D:'HeadAll',0x2F:'Lower',0x12:'Icon',0x1E:'Icon2',0x48:'ColorType',
 0x49:'EdgeColorType',0x13:'Color',0x14:'EdgeColor',0x1A:'Italic',0x1B:'Edge',0x1F:'Hyphen',0x1D:'Nbsp',
 0x24:'Sec',0x22:'Kilo',0x07:'Time',0x06:'ResetTime',0x2C:'Split',0x26:'Float',0x50:'Digit',0x51:'Ordinal',
 0x60:'Sound',0x61:'LevelPos',0x42:'SwitchPlatform',0x41:'SheetSub',0x2E:'Fixed'}
KNOWN_BASE = set(KIND_NAMES.values()) | {'Raw'}

def base_name(payload: bytes) -> str:
    if len(payload) >= 2 and payload[0] == 0x02:
        return KIND_NAMES.get(payload[1], 'Payload%02X' % payload[1])
    return 'Raw'

def read_len(b, idx):
    """-> (length, bodyStart, marker) | None   (TryReadRunLength)"""
    if idx >= len(b): return None
    m = b[idx]
    if 0x01 <= m <= 0xCF: return m - 1, idx + 1, m
    if 0xF0 <= m <= 0xFE:
        mask = m + 1; j = idx + 1; v = 0
        for bit, sh in ((8,24),(4,16),(2,8),(1,0)):
            if mask & bit:
                if j >= len(b): return None
                v |= b[j] << sh; j += 1
        return v, j, m
    return None

def _lead_ok(c, d):
    """UTF-8 canonico (como SeStringTree.LeadAllowsSecond de pgri): sobrelargos, sustitutos y > U+10FFFF NO son literal (van como 'raw' reversibles)"""
    if c in (0xC0, 0xC1) or c >= 0xF5: return False
    if c == 0xE0: return d >= 0xA0
    if c == 0xED: return d <= 0x9F
    if c == 0xF0: return d >= 0x90
    if c == 0xF4: return d <= 0x8F
    return True

def _read_literal(b, pos, end):
    lit = bytearray()
    while pos < end:
        c = b[pos]
        if c == START or c == RUN: break
        if c <= 0x7F: lit.append(c); pos += 1
        elif (c & 0xC0) == 0x80: break
        elif (c & 0xE0) == 0xC0:
            if pos+1 < end and (b[pos+1] & 0xC0) == 0x80 and _lead_ok(c, b[pos+1]): lit += b[pos:pos+2]; pos += 2
            else: break
        elif (c & 0xF0) == 0xE0:
            if pos+2 < end and (b[pos+1] & 0xC0) == 0x80 and (b[pos+2] & 0xC0) == 0x80 and _lead_ok(c, b[pos+1]): lit += b[pos:pos+3]; pos += 3
            else: break
        elif (c & 0xF8) == 0xF0:
            if pos+3 < end and _lead_ok(c, b[pos+1]) and all((b[pos+k] & 0xC0) == 0x80 for k in (1,2,3)): lit += b[pos:pos+4]; pos += 4
            else: break
        else: break
    return lit, pos

def _parse_range(b, pos, end):
    nodes = []
    while pos < end:
        c = b[pos]
        if c == START:
            r = read_len(b, pos + 2) if pos + 1 < end else None
            if r and r[1] + r[0] < end and b[r[1] + r[0]] == END:
                ln, bs, mk = r
                children, _ = _parse_range(b, bs, bs + ln)
                nodes.append(('mac', b[pos+1], children, mk))
                pos = bs + ln + 1
            else:
                nodes.append(('raw', c)); pos += 1
        elif c == RUN:
            r = read_len(b, pos + 1)
            if r and r[1] + r[0] <= end:
                ln, bs, mk = r
                children, _ = _parse_range(b, bs, bs + ln)
                nodes.append(('run', children, mk)); pos = bs + ln
            else:
                nodes.append(('raw', c)); pos += 1
        else:
            lit, np_ = _read_literal(b, pos, end)
            if lit:
                nodes.append(('lit', bytes(lit).decode('utf-8'))); pos = np_
            elif pos < end:
                nodes.append(('raw', b[pos])); pos += 1
    return nodes, pos

def parse(b: bytes):
    """SeStringTree.Parse: corta en el primer NUL."""
    end = b.find(b'\x00'); end = len(b) if end < 0 else end
    return _parse_range(b, 0, end)[0]

def _fits(v, m):
    mask = m + 1; n = bin(mask & 15).count('1')
    return n >= 4 or v < (1 << (8*n))

def _emit_marker(v, m):
    mask = m + 1; out = [m]
    for bit, sh in ((8,24),(4,16),(2,8),(1,0)):
        if mask & bit: out.append((v >> sh) & 0xFF)
    return bytes(out)

def _enc_len_min(v):
    """codificacion minima del juego: marcador 0xF0|(mascara-1) y SOLO los bytes distintos de cero (los ceros se omiten; nunca hay NUL dentro de la longitud)"""
    if v <= 0xCE: return bytes([v+1])
    mask = 0; out = []
    for bit, sh in ((8, 24), (4, 16), (2, 8), (1, 0)):
        x = (v >> sh) & 0xFF
        if x: mask |= bit; out.append(x)
    return bytes([0xF0 | (mask - 1)]) + bytes(out)

def enc_len(v, orig):
    """como SeStringTree.EncodeRunLength (C#), pero si esa codificacion llevara un byte 0x00 (p. ej. marcador 0xF2 con longitud < 256: el NUL trunca la cadena) se usa la minima"""
    r = _enc_len0(v, orig)
    return _enc_len_min(v) if 0 in r else r

def _enc_len0(v, orig):
    if 0x01 <= orig <= 0xCF:
        if 0 <= v <= 0xCE: return bytes([v+1])
    elif 0xF0 <= orig <= 0xFE and _fits(v, orig):
        return _emit_marker(v, orig)
    if v <= 0xCE: return bytes([v+1])
    if v <= 0xFF: return _emit_marker(v, 0xF0)
    if v <= 0xFFFF: return _emit_marker(v, 0xF2)
    if v <= 0xFFFFFF: return _emit_marker(v, 0xF6)
    return _emit_marker(v, 0xFE)

def _ser(nodes, out):
    for n in nodes:
        k = n[0]
        if k == 'lit': out += n[1].encode('utf-8')
        elif k == 'mac':
            body = bytearray(); _ser(n[2], body)
            out.append(START); out.append(n[1]); out += enc_len(len(body), n[3]); out += body; out.append(END)
        elif k == 'opq': out += n[1]
        elif k == 'raw': out.append(n[1])
        elif k == 'run':
            body = bytearray(); _ser(n[1], body)
            out.append(RUN); out += enc_len(len(body), n[2]); out += body

def serialize(nodes):
    out = bytearray(); _ser(nodes, out); out.append(0); return bytes(out)

def serialize_node(node):
    out = bytearray(); _ser([node], out); return bytes(out)

# ---------------- tokenizer (SeStringTreeTokenizer.Tokenize) ----------------
def _has_text(nodes):
    for n in nodes:
        if n[0] == 'lit' and any(ord(c) >= 0x20 for c in n[1]): return True
        if n[0] == 'run': return True
        if n[0] == 'mac' and _has_text(n[2]): return True
    return False

def tokenize(nodes):
    """-> (text, [(token, bytes)])"""
    sb = []; toks = []; counts = {}
    def emit(name, bts):
        counts[name] = counts.get(name, 0) + 1
        t = '<%s>' % name if counts[name] == 1 else '<%s#%d>' % (name, counts[name])
        sb.append(t); toks.append((t, bytes(bts)))
    def walk(ns):
        for n in ns:
            k = n[0]
            if k == 'lit': sb.append(n[1].replace('<', '<<'))
            elif k == 'mac':
                if _has_text(n[2]):
                    emit(base_name(bytes([2, n[1]])), bytes([0, n[1], n[3]]))
                    walk(n[2]); emit('MacroEnd', b'')
                else:
                    emit(base_name(bytes([2, n[1]])), serialize_node(n))
            elif k == 'opq': emit(base_name(n[1]), n[1])
            elif k == 'raw': emit(base_name(bytes([n[1]])), bytes([n[1]]))
            elif k == 'run':
                emit('Run', bytes([n[2]])); walk(n[1]); emit('RunEnd', b'')
    walk(nodes)
    return ''.join(sb), toks

def tokenize_raw(raw: bytes) -> str:
    return tokenize(parse(raw))[0]

# ---------------- marca «salto -> espacio» (pgri SeStringSuppressedNewLine) ----------------
MARCA = '\ue0f0'   # U+E0F0 JUSTO tras un token <NewLine>/<NewLine#N>: el parcheador descarta ese NewLine (y la marca) y deja un espacio; el juego envuelve solo.
# El token NewLine SIGUE en el target (multiconjunto, orden y numeracion intactos para el validador); solo cambian los bytes escritos. La marca no llega NUNCA al juego.
# REGLA DEL ESPACIO (identica en C#): un NewLine marcado deja un «espacio pendiente»; se escribe UN ' ' justo antes del siguiente caracter literal o token no-NewLine,
# salvo que lo ya escrito termine en espacio o ese caracter sea un espacio; se pierde si lo siguiente es otro NewLine (marcado o no) o el fin de la cadena
# (trozo marcado vacio = nada). No se puede marcar un NewLine duro: dentro de Run, antes del ultimo MacroEnd, al inicio, ni pegado al final de otro NewLine o de un token que no sea de color/estilo (SI vale pegado a color/estilo y como ultimo caracter de la cadena).
NL_TOKEN_RE = re.compile(r'<NewLine(?:#[0-9]+)?>')

def aplicar_marcas(target):
    """Referencia a nivel de CADENA (independiente de detokenize): aplica la marca U+E0F0 a un target tokenizado y devuelve la cadena tokenizada resultante
    (sin NewLine marcados ni marcas; sin renumerar). Sin marca devuelve el target tal cual. Una marca suelta (no tras NewLine) se deja: la rechaza validate."""
    if MARCA not in target: return target
    out = []; ult = ''; pend = False; i = 0
    def soltar(sig):
        nonlocal pend, ult
        if not pend: return
        pend = False
        if sig != ' ' and ult != ' ': out.append(' '); ult = ' '
    while i < len(target):
        c = target[i]
        if c != '<':
            soltar(c); out.append(c); ult = c; i += 1; continue
        if target.startswith('<<', i):
            soltar('<'); out.append('<<'); ult = '<'; i += 2; continue
        m = TOKEN_RE.match(target, i)
        t = m.group(0) if m else _match_propio(target, i)   # los colores propios son un token mas (no NewLine)
        if t is None:
            soltar('<'); out.append(c); ult = c; i += 1; continue
        fin = i + len(t)
        if _bn(t) == 'NewLine':
            if fin < len(target) and target[fin] == MARCA: pend = True; i = fin + 1; continue
            pend = False
        else: soltar('\0')
        out.append(t); ult = '>'; i = fin
    return ''.join(out)

def _match_token_at(text, i, cands):
    best = None
    for c in cands:
        if text.startswith(c, i) and (best is None or len(c) > len(best)): best = c
    return best

def _base_of(tok):
    inner = tok.strip('<>'); h = inner.find('#')
    return inner[:h] if h >= 0 else inner

def detokenize(text, toks):
    """-> (tree, None) | (None, reason)"""
    by = {}
    for t, b in toks:
        if t in by: return None, "duplicate token '%s' in map" % t
        by[t] = b
    used = set(); stack = []; tree = []; cur = tree; lit = []
    nlb = next((b for t, b in toks if _bn(t) == 'NewLine'), None)   # bytes del NewLine del source (para los NewLine EXTRA del target)
    pend = [False]   # espacio pendiente de un NewLine marcado (ver MARCA)
    propio = '<UIColor' in text and any(_bn(t) in PROPIO_BASES for t, _ in _atoms(text)); col_abierto = False   # colores propios del es (ver arriba)
    def flush():
        if lit: cur.append(('lit', ''.join(lit))); lit.clear()
    def soltar(sig):   # tras flush() el buffer esta vacio solo si el ultimo nodo es un token (no es espacio)
        if not pend[0]: return
        pend[0] = False
        if sig != ' ' and not (lit and lit[-1] == ' '): lit.append(' ')
    def marcado(j): return j < len(text) and text[j] == MARCA
    i = 0
    while i < len(text):
        c = text[i]
        if c == MARCA: return None, 'suppression marker U+E0F0 at index %d in target is not attached to a <NewLine>' % i
        if c != '<': soltar(c); lit.append(c); i += 1; continue
        if i + 1 < len(text) and text[i+1] == '<': soltar('<'); lit.append('<'); i += 2; continue
        m = _match_token_at(text, i, by.keys())
        if m is None:
            pr = _match_propio(text, i) if propio else None
            if pr is not None:   # color propio: macros 0x48+0x49 sintetizadas como bytes opacos, solo a nivel superior (como los NewLine extra)
                if stack: return None, "own colour '%s' inside a run or macro bracket in target" % pr
                if any(_bn(t) in COLOR_BASES and len(b) == 3 and b[0] == 0 for t, b in toks): return None, 'source colour macro carries a body: own colours not allowed'
                if (_bn(pr) == 'UIColor') == col_abierto: return None, "own colour '%s' %s in target" % (pr, 'nested' if col_abierto else 'closes without an open')
                bts = bytes_color_propio(pr)
                if bts is None: return None, "own colour code in '%s' is outside the supported range" % pr
                col_abierto = not col_abierto
                soltar('\0'); flush(); cur.append(('opq', bts)); i += len(pr); continue
            mm = NL_TOKEN_RE.match(text, i)
            if mm and nlb is None:   # source SIN NewLine: se sintetiza el payload estandar 02 10 01 03 (<NewLine>, <NewLine#2>.. hasta MAX_NL_SINTETIZADOS), nunca dentro de run/macro (MatchExtraNewLine de pgri)
                m = mm.group(0); nn = 1 if m == '<NewLine>' else _extra_nl(m)
                if nn is None or nn > MAX_NL_SINTETIZADOS: return None, "unmapped or stray '<' at index %d in target" % i
                if stack: return None, "extra '%s' inside a run or macro bracket in target" % m
                if m in used: return None, "token '%s' used more than once in target" % m
                used.add(m)
                if marcado(i + len(m)): pend[0] = True; i += len(m) + 1; continue
                pend[0] = False; flush(); cur.append(('mac', 0x10, [], 1)); i += len(m); continue
            if mm and nlb is not None:   # NewLine extra: se sintetiza con los bytes del NewLine del source
                m = mm.group(0)
                if m in used: return None, "token '%s' used more than once in target" % m
                used.add(m)
                if marcado(i + len(m)):
                    if stack: return None, "extra '%s' inside a run or macro bracket in target" % m
                    pend[0] = True; i += len(m) + 1; continue
                pend[0] = False; flush(); p = parse(nlb + b'\x00'); cur.append(p[0] if len(p) == 1 else ('opq', nlb)); i += len(m); continue
            return None, "unmapped or stray '<' at index %d in target" % i
        if m in used: return None, "token '%s' used more than once in target" % m
        used.add(m); bn = _base_of(m)
        if propio and bn in COLOR_BASES: return None, "plain '%s' in a target that carries own colours" % m
        if bn == 'NewLine':
            if marcado(i + len(m)):
                if stack: return None, "suppressed '%s' inside a run or macro bracket in target" % m
                pend[0] = True; i += len(m) + 1; continue
            pend[0] = False
        else: soltar('\0')
        flush()
        bts = by[m]
        if bn == 'Run':
            stack.append((cur, 'run', bts[0] if bts else 0, 0)); cur = []
        elif bn == 'RunEnd':
            if not stack or stack[-1][1] != 'run': return None, 'unbalanced <RunEnd> without matching <Run>'
            ch = cur; par, _, mk, _ = stack.pop(); cur = par; cur.append(('run', ch, mk))
        elif bn == 'MacroEnd':
            if not stack or stack[-1][1] != 'mac': return None, 'unbalanced <MacroEnd> without matching macro open'
            ch = cur; par, _, mk, code = stack.pop(); cur = par; cur.append(('mac', code, ch, mk))
        elif len(bts) == 3 and bts[0] == 0:
            stack.append((cur, 'mac', bts[2], bts[1])); cur = []
        elif len(bts) >= 2 and bts[0] == 0x02:
            p = parse(bts + b'\x00')
            cur.append(p[0] if len(p) == 1 else ('opq', bts))
        elif len(bts) == 1:
            cur.append(('raw', bts[0]))
        else:
            return None, "token '%s' has no reconstructible bytes" % m
        i += len(m)
    flush()
    if stack: return None, 'unbalanced run/macro open'
    if col_abierto: return None, 'own colour opened but never closed with <UIColorEnd>'
    return tree, None

# ---------------- standard macros (Gender) ----------------
G_OPEN, G_ELSE, G_END = '<Gender>', '<GenderElse>', '<GenderEnd>'
M_OPEN, M_CLOSE = '￹', '￺'

def _find_unescaped(text, delim, start):
    pos = start
    while pos < len(text):
        f = text.find(delim, pos)
        if f < 0: return -1
        n = 0; k = f - 1
        while k >= 0 and text[k] == '<': n += 1; k -= 1
        if n % 2 == 0: return f
        pos = f + len(delim)
    return -1

def has_reserved(text):
    return any(_find_unescaped(text, d, 0) >= 0 for d in (G_OPEN, G_ELSE, G_END))

def _decode_branch(t):
    out = []; i = 0
    while i < len(t):
        if t[i] != '<': out.append(t[i]); i += 1; continue
        if i + 1 < len(t) and t[i+1] == '<': out.append('<'); i += 2; continue
        return None, 'gender conditional branches must be literal text; nested payloads are not allowed'
    return ''.join(out), None

def build_gender_macro(female, male):
    return ('mac', 0x08, [('raw', 0xE9), ('lit', '\x05'), ('run', [('lit', female)], 1), ('run', [('lit', male)], 1)], 1)

def split_gender(text):
    """TrySplitGenderMacros -> (marked, macros, reason)"""
    if M_OPEN in text or M_CLOSE in text: return text, [], 'target contains a reserved gender-macro marker character'
    b = []; macros = []; pos = 0
    while pos < len(text):
        o = _find_unescaped(text, G_OPEN, pos)
        if o < 0: b.append(text[pos:]); break
        b.append(text[pos:o])
        fs = o + len(G_OPEN)
        ep = _find_unescaped(text, G_ELSE, fs); npos = _find_unescaped(text, G_OPEN, fs)
        if ep < 0 or (npos >= 0 and npos < ep): return text, [], '%s at index %d has no valid %s' % (G_OPEN, o, G_ELSE)
        ms = ep + len(G_ELSE)
        endp = _find_unescaped(text, G_END, ms); npos = _find_unescaped(text, G_OPEN, ms)
        if endp < 0 or (npos >= 0 and npos < endp): return text, [], '%s at index %d has no valid %s' % (G_OPEN, o, G_END)
        f, r1 = _decode_branch(text[fs:ep]); m, r2 = _decode_branch(text[ms:endp])
        if f is None or m is None: return text, [], r1 or r2
        if not f or not m: return text, [], 'gender conditional requires non-empty female and male branches'
        b.append(M_OPEN + str(len(macros)) + M_CLOSE); macros.append(build_gender_macro(f, m))
        pos = endp + len(G_END)
    return ''.join(b), macros, None

def parse_gender_plain(text):
    """SeStringStandardMacros.TryParse (fuente sin payloads) -> (nodes, reason)"""
    nodes = []; lit = []; pos = 0
    while pos < len(text):
        if text[pos] != '<': lit.append(text[pos]); pos += 1; continue
        if pos + 1 < len(text) and text[pos+1] == '<': lit.append('<'); pos += 2; continue
        if not text.startswith(G_OPEN, pos):
            return None, "unsupported or stray '<' at index %d in standard-macro target" % pos
        if lit: nodes.append(('lit', ''.join(lit))); lit = []
        fs = pos + len(G_OPEN)
        ep = _find_unescaped(text, G_ELSE, fs); npos = _find_unescaped(text, G_OPEN, fs)
        if ep < 0 or (0 <= npos < ep): return None, 'no valid GenderElse'
        ms = ep + len(G_ELSE)
        endp = _find_unescaped(text, G_END, ms); npos = _find_unescaped(text, G_OPEN, ms)
        if endp < 0 or (0 <= npos < endp): return None, 'no valid GenderEnd'
        f, r1 = _decode_branch(text[fs:ep]); m, r2 = _decode_branch(text[ms:endp])
        if f is None or m is None: return None, r1 or r2
        if not f or not m: return None, 'gender conditional requires non-empty female and male branches'
        nodes.append(build_gender_macro(f, m)); pos = endp + len(G_END)
    if lit: nodes.append(('lit', ''.join(lit)))
    return nodes, None

def _splice(nodes, macros, cnt):
    i = 0
    while i < len(nodes):
        n = nodes[i]
        if n[0] == 'lit' and M_OPEN in n[1]:
            exp = []; t = n[1]; p = 0; buf = []
            while p < len(t):
                if t[p] != M_OPEN: buf.append(t[p]); p += 1; continue
                q = t.find(M_CLOSE, p)
                idx = int(t[p+1:q])
                if buf: exp.append(('lit', ''.join(buf))); buf = []
                exp.append(macros[idx]); cnt[0] += 1; p = q + 1
            if buf: exp.append(('lit', ''.join(buf)))
            nodes[i:i+1] = exp; i += len(exp); continue
        if n[0] == 'run':
            ch = list(n[1]); _splice(ch, macros, cnt); nodes[i] = ('run', ch, n[2])
        elif n[0] == 'mac':
            ch = list(n[2]); _splice(ch, macros, cnt); nodes[i] = ('mac', n[1], ch, n[3])
        i += 1

def try_translate(vanilla: bytes, source: str, target: str):
    """SeStringTree.TryTranslate -> (bytes_sin_NUL | None, reason)"""
    tree = parse(vanilla)
    text, toks = tokenize(tree)
    if text != source: return None, "tokenized source does not match the row's run-aware tokenized string"
    if has_reserved(target):
        if not toks:
            if MARCA in target: return None, 'NewLine-suppression marker without a source NewLine in a standard-macro target'
            rebuilt, reason = parse_gender_plain(target)
            if rebuilt is None: return None, reason
        else:
            marked, macros, reason = split_gender(target)
            if reason: return None, reason
            rebuilt, reason = detokenize(marked, toks)
            if rebuilt is None: return None, reason
            cnt = [0]; _splice(rebuilt, macros, cnt)
            if cnt[0] != len(macros): return None, 'gender conditional markers were lost'
    else:
        rebuilt, reason = detokenize(target, toks)
        if rebuilt is None: return None, reason
    out = serialize(rebuilt)
    return out[:-1], None

# ---------------- validator ----------------
TOKEN_RE = re.compile(r'<[A-Za-z][A-Za-z0-9]*(?:#[0-9]+)?>')

# ---------------- colores propios del es (docs/colores-propios-es.md; espejo de SeStringOwnColors.cs en pgri) ----------------
# `<UIColor:f201f6>` ... `<UIColorEnd>` en el TARGET (nunca en el source): el es lleva SU color (macros 0x48 ColorType + 0x49 EdgeColorType, borde = codigo+1) donde
# lo pone el frances. Si el target trae alguno, los tokens ColorType/EdgeColorType del source se IGNORAN (no se exigen) y el target no puede llevarlos.
PROPIO_ABRE_RE = re.compile(r'<UIColor:([0-9A-Fa-f]{6})>')
PROPIO_CIERRA = '<UIColorEnd>'
PROPIO_BASES = frozenset(('UIColor', 'UIColorEnd'))
COLOR_BASES = frozenset(('ColorType', 'EdgeColorType'))

def _match_propio(text, i):
    """token de color propio en text[i:] (apertura de 6 hex o cierre) o None"""
    m = PROPIO_ABRE_RE.match(text, i)
    if m: return m.group(0)
    return PROPIO_CIERRA if text.startswith(PROPIO_CIERRA, i) else None

def codigo_color_ok(hx):
    """6 hex `f201yy` con yy en 0x80..0xFE (UIColor 0x0180-0x01FE: ambos codigos, texto y borde = +1, tokenizan como macro hoja, sin NUL)"""
    h = hx.lower()
    return len(h) == 6 and h[:4] == 'f201' and all(c in '0123456789abcdef' for c in h) and 0x80 <= int(h[4:], 16) <= 0xFE

def bytes_color_propio(tok):
    """<UIColor:f201yy> -> 02 48 04 F2 01 yy 03 + 02 49 04 F2 01 yy+1 03 ; <UIColorEnd> -> 02 49 02 01 03 + 02 48 02 01 03 ; None si el codigo no vale"""
    if tok == PROPIO_CIERRA: return bytes.fromhex('0249020103' '0248020103')
    m = PROPIO_ABRE_RE.fullmatch(tok)
    if not m or not codigo_color_ok(m.group(1)): return None
    y = int(m.group(1)[4:], 16)
    return bytes([2, 0x48, 4, 0xF2, 1, y, 3, 2, 0x49, 4, 0xF2, 1, y + 1, 3])

def _atoms(text):
    a = []; i = 0
    while i < len(text):
        if text[i] != '<': i += 1; continue
        if i + 1 < len(text) and text[i+1] == '<': i += 2; continue
        m = TOKEN_RE.match(text, i)
        if m: a.append((m.group(0), i)); i += len(m.group(0))
        else:
            p = _match_propio(text, i)
            if p: a.append((p, i)); i += len(p)
            else: i += 1
    return a

def contiene_color_propio(text):
    """chequeo textual barato (espejo de SeStringOwnColors.ContainsOwnColor): las vias planas lo rechazan"""
    return '<UIColor:' in text or PROPIO_CIERRA in text

def tiene_color_propio(text):
    return '<UIColor' in text and any(_bn(t) in PROPIO_BASES for t, _ in _atoms(text))

def filtrar_colores_propios(sa, ta):
    """sa/ta = listas de tokens (source/target). Con colores propios en ta: se quitan de sa los ColorType/EdgeColorType y de ta los propios; si no, identidad."""
    if not any(_bn(t) in PROPIO_BASES for t in ta): return sa, ta
    return [t for t in sa if _bn(t) not in COLOR_BASES], [t for t in ta if _bn(t) not in PROPIO_BASES]

def expandir_colores_propios(target):
    """target con colores propios -> la cadena tokenizada que daran los bytes escritos (<ColorType><EdgeColorType>.. numerados por aparicion, como sestring.tokenize); sin ellos, igual."""
    if '<UIColor' not in target: return target
    cnt = {}
    def nm(b):
        cnt[b] = cnt.get(b, 0) + 1
        return '<%s>' % b if cnt[b] == 1 else '<%s#%d>' % (b, cnt[b])
    out = []; i = 0
    for t, p in _atoms(target):
        if _bn(t) not in PROPIO_BASES: continue
        out.append(target[i:p])
        out.append(nm('ColorType') + nm('EdgeColorType') if _bn(t) == 'UIColor' else nm('EdgeColorType') + nm('ColorType'))
        i = p + len(t)
    out.append(target[i:]); return ''.join(out)

def _ctrl(text):
    return [c for c in text if ord(c) < 0x20 and c not in '\t\n\r\x00']

def has_payloads(text): return bool(_atoms(text)) or bool(_ctrl(text))

def _bn(tok):
    inner = tok[1:-1]; c = inner.find(':')
    if c >= 0: inner = inner[:c]   # <UIColor:f201f6> -> UIColor
    h = inner.find('#'); return inner if h < 0 else inner[:h]

def renumerar_newlines(target, source=None):
    """renombra los tokens NewLine del target. Sin `source`: por orden de aparicion (<NewLine>, <NewLine#2>...), como el tokenizador.
    Con `source` (y mismos tokens no-NewLine en el mismo orden, >= NewLine por hueco): los NewLine del source conservan SU nombre (en orden) y los
    EXTRA (el sobrante de cada hueco) toman N+1, N+2... por orden de aparicion (N = nº de NewLine del source), como exige el parcheador pgri
    (DropExtraNewLines: extras = NewLine numerados por encima del recuento del source; los del source deben quedar en su sitio). El resto intacto."""
    tatoms = [(t, p) for t, p in _atoms(target) if t not in (G_OPEN, G_ELSE, G_END)]   # los delimitadores <Gender>.. son del target (macro de genero), no payloads del source
    propio = any(_bn(t) in PROPIO_BASES for t, _ in tatoms)
    if propio: tatoms = [(t, p) for t, p in tatoms if _bn(t) not in PROPIO_BASES]   # colores propios: invisibles para el reparto de NewLine (el source pierde sus ColorType/EdgeColorType)
    at = [(t, p) for t, p in tatoms if _bn(t) == 'NewLine']
    names = None
    if source is not None:
        sn = [t for t, _ in _atoms(source)]; tn = [t for t, _ in tatoms]
        if propio: sn = [t for t in sn if _bn(t) not in COLOR_BASES]
        sr, sg, _ = _huecos(sn); tr, tg, _ = _huecos(tn); N = sum(sg)
        if N >= 1 and sr == tr and all(b >= a for a, b in zip(sg, tg)):
            nm = lambda k: '<NewLine>' if k == 1 else '<NewLine#%d>' % k
            names = []; gap = 0; j = 0; s_used = 0; ex = 0
            for t, p in tatoms:
                if _bn(t) != 'NewLine': gap += 1; j = 0; continue
                if j < sg[gap]: s_used += 1; names.append(nm(s_used))
                else: ex += 1; names.append(nm(N + ex))
                j += 1
    if names is None: names = ['<NewLine>' if i == 0 else '<NewLine#%d>' % (i + 1) for i in range(len(at))]
    out = []; prev = 0
    for (t, p), nme in zip(at, names): out.append(target[prev:p]); out.append(nme); prev = p + len(t)
    out.append(target[prev:]); return ''.join(out)

def _huecos(names):
    """-> (no_NewLine, [n_NewLine por hueco entre tokens no-NewLine], [profundidad Run por hueco])"""
    rest = []; gaps = [0]; depth = [0]; d = 0
    for t in names:
        b = _bn(t)
        if b == 'NewLine': gaps[-1] += 1; continue
        if b == 'Run': d += 1
        elif b == 'RunEnd': d -= 1
        rest.append(t); gaps.append(0); depth.append(d)
    return rest, gaps, depth

def _extra_nl(tok):
    """<NewLine#N> con N>=2 -> N; si no None (TryParseExtraNewLineToken de pgri)"""
    m = re.fullmatch(r'<NewLine#([0-9]+)>', tok)
    return int(m.group(1)) if m and int(m.group(1)) >= 2 else None

MAX_NL_SINTETIZADOS = 3   # SeStringCompatibilityValidator.MaxSynthesizedNewLines

def relax_newlines(source, target):
    """Emulacion EXACTA de SeStringCompatibilityValidator.DropExtraNewLines (pgri). Source SIN NewLine: extras = <NewLine>, <NewLine#2>.. (numeracion por
    aparicion, hasta MAX_NL_SINTETIZADOS=3, una vez cada uno), mismas restricciones (fuera de Run, tras el ultimo MacroEnd); pgri sintetiza 02 10 01 03.
    Si el source tiene >=1 NewLine, un token NewLine del target que no
    esta en el source, con N > nº de NewLine del source y que aparece una sola vez, es EXTRA y se descarta de la comparacion; es rechazo si cae dentro de
    un <Run> o antes del ultimo <MacroEnd> del target. El target debe venir con la numeracion de `renumerar_newlines(target, source)`.
    -> lista de tokens efectivos del target (sin los extra) o None si no hay extra admitido (o alguno es inadmisible: entonces falla la comparacion)."""
    sa, ta = filtrar_colores_propios([t for t, _ in _atoms(source)], [t for t, _ in _atoms(target)])
    n_src = sum(1 for t in sa if _bn(t) == 'NewLine')
    stoks = set(sa)
    last_me = max([k for k, t in enumerate(ta) if _bn(t) == 'MacroEnd'], default=-1)
    kept = []; seen = set(); depth = 0; dropped = False
    for k, t in enumerate(ta):
        b = _bn(t)
        if b == 'Run': depth += 1
        elif b == 'RunEnd' and depth > 0: depth -= 1
        n = _extra_nl(t) if b == 'NewLine' else None
        if n_src == 0 and t == '<NewLine>': n = 1   # source sin NewLine: pgri sintetiza 02 10 01 03; extras <NewLine>,<NewLine#2>.. (IsSynthesizableNewLineToken)
        ok = n is not None and (n > n_src if n_src else n <= MAX_NL_SINTETIZADOS)
        if b == 'NewLine' and t not in stoks and ok and t not in seen:
            seen.add(t)
            if depth > 0 or k < last_me: return None
            dropped = True; continue
        kept.append(t)
    return kept if dropped else None

ESTILO_BASE = frozenset(('ColorType', 'EdgeColorType', 'Color', 'EdgeColor', 'Italic', 'Edge', 'UIColor', 'UIColorEnd'))   # tokens de color/estilo: hojas que no escriben texto (pgri IsStyleBase)

def _check_marcas(target, ta, viol):
    """Emulacion de SeStringCompatibilityValidator.CheckSuppressedNewLines (pgri): la marca U+E0F0 solo vale JUSTO tras un NewLine «blando»:
    no dentro de Run ni antes del ultimo MacroEnd (ExtraPayload); no al inicio, ni pegado al final de otro NewLine o de un token que no sea de color/estilo,
    ni una marca suelta (StrayDelimiter). SI vale pegado a un token de color/estilo (ESTILO_BASE) y como ULTIMO caracter de la cadena (el espacio pendiente se descarta)."""
    if MARCA not in target: return
    last_me = max([k for k, (t, _) in enumerate(ta) if _bn(t) == 'MacroEnd'], default=-1)
    unidas = set(); depth = 0
    for k, (t, p) in enumerate(ta):
        b = _bn(t)
        if b == 'Run': depth += 1
        elif b == 'RunEnd' and depth > 0: depth -= 1
        fin = p + len(t)
        if b != 'NewLine' or fin >= len(target) or target[fin] != MARCA: continue
        unidas.add(fin)
        if depth > 0:   # 2026-11-05: ya NO se exige estar tras el ultimo MacroEnd; la profundidad real (Run/macro) la juzga el tokenizador (`stack`)
            viol.append(('ExtraPayload', '%s marcado como suprimido dentro de un Run' % t)); continue
        pegado = k > 0 and ta[k-1][1] + len(ta[k-1][0]) == p and _bn(ta[k-1][0]) not in ESTILO_BASE
        if p == 0 or pegado:
            viol.append(('StrayDelimiter', '%s marcado como suprimido pero es un salto duro (inicio, o pegado a un NewLine u otro token que no es de color/estilo)' % t))
    for q, ch in enumerate(target):
        if ch == MARCA and q not in unidas: viol.append(('StrayDelimiter', 'marca U+E0F0 en %d que no sigue a un <NewLine>' % q))

def _check_colores_propios(ta, viol):
    """Emulacion de CheckOwnColors (pgri): colores propios del es = pares <UIColor:f201yy>..<UIColorEnd> sin anidar, codigo en rango, sin ColorType/EdgeColorType
    sueltos en el target y sin Run/MacroEnd (solo cadenas planas)."""
    if not any(_bn(t) in PROPIO_BASES for t, _ in ta): return
    abierto = False
    for t, p in ta:
        b = _bn(t)
        if b == 'UIColor':
            if abierto: viol.append(('InvalidOwnColor', '%s anidado dentro de otro color propio (indice %d)' % (t, p)))
            elif bytes_color_propio(t) is None: viol.append(('InvalidOwnColor', '%s: codigo fuera de rango (f201 + 80..fe)' % t))
            abierto = True
        elif b == 'UIColorEnd':
            if not abierto: viol.append(('InvalidOwnColor', '<UIColorEnd> sin <UIColor:..> abierto (indice %d)' % p))
            abierto = False
        elif b in COLOR_BASES: viol.append(('InvalidOwnColor', '%s: el target con colores propios no puede llevar ColorType/EdgeColorType del source' % t))
        elif b in ('Run', 'RunEnd', 'MacroEnd'): viol.append(('InvalidOwnColor', '%s: colores propios solo en cadenas planas (sin Run/MacroEnd)' % t))
    if abierto: viol.append(('InvalidOwnColor', '<UIColor:..> sin cerrar con <UIColorEnd>'))

def _check_common(source, target, viol):
    sa, ta = _atoms(source), _atoms(target)
    _check_marcas(target, ta, viol)
    _check_colores_propios(ta, viol)
    sal, tal = filtrar_colores_propios([t for t, _ in sa], [t for t, _ in ta])   # con colores propios: se comparan sin los ColorType/EdgeColorType del source ni los propios
    ef = relax_newlines(source, target)
    tn_eff = ef if ef is not None else tal   # tokens del target a comparar (sin NewLine extra si la relajacion aplica)
    starts = {p for _, p in ta}
    i = 0
    while i < len(target):  # stray
        if target[i] != '<': i += 1; continue
        if i + 1 < len(target) and target[i+1] == '<': i += 2; continue
        if i in starts:
            i += len(next(t for t, p in ta if p == i)); continue
        viol.append(('StrayDelimiter', "stray '<' at %d" % i)); i += 1
    cnt = {}
    for t in sal: cnt[t] = cnt.get(t, 0) + 1
    for t in tn_eff: cnt[t] = cnt.get(t, 0) - 1
    for t, d in cnt.items():
        if d == 0: continue
        b = _bn(t)
        if b in ('Run', 'RunEnd'): kind = 'UnbalancedRun'
        elif b == 'MacroEnd': kind = 'UnbalancedMacro'
        else: kind = 'MissingPayload' if d > 0 else 'ExtraPayload'
        viol.append((kind, '%s: %+d' % (t, d)))
    depth = 0; last = None
    for t in tn_eff:  # run nesting
        if _bn(t) == 'Run': depth += 1; last = t
        elif _bn(t) == 'RunEnd':
            depth -= 1
            if depth < 0: viol.append(('UnbalancedRun', t + ' sin <Run>')); depth = 0
    if depth > 0: viol.append(('UnbalancedRun', last + ' sin cerrar'))
    if not any(k in ('MissingPayload','ExtraPayload','UnbalancedRun','UnbalancedMacro') for k, _ in viol):
        for k in range(min(len(sal), len(tn_eff))):
            if sal[k] != tn_eff[k]:
                viol.append(('ReorderedPayloads', 'token #%d: %s vs %s' % (k+1, sal[k], tn_eff[k]))); break
    sc, tc = _ctrl(source), _ctrl(target)
    if sc != tc:
        from collections import Counter
        miss = Counter(sc) - Counter(tc); extra = Counter(tc) - Counter(sc)
        if miss or extra:
            parts = []
            if miss: parts.append('lost from target: [%s]' % ' '.join('0x%02X' % ord(c) for c in miss.elements()))
            if extra: parts.append('invented in target: [%s]' % ' '.join('0x%02X' % ord(c) for c in extra.elements()))
            viol.append(('ControlCharMismatch', '; '.join(parts)))
        else: viol.append(('ControlCharMismatch', 'raw control bytes are reordered'))
    legacy = next((t for t, _ in sa if _bn(t).startswith('PayloadFF')), None)
    if legacy:
        def lits(txt, at):
            s = txt; 
            for t, p in sorted(at, key=lambda x: -x[1]): s = s[:p] + s[p+len(t):]
            return s
        if lits(source, sa) != lits(target, ta): viol.append(('StaleRunLength', legacy))

def validate(source, target):
    """-> lista de (Kind, mensaje); vacía = compatible"""
    viol = []
    if has_reserved(target):
        if has_payloads(source):
            stripped, macros, reason = split_gender(target)
            if reason or not macros:
                return [('InvalidStandardMacro', reason or 'invalid standard target macro')]
            without = re.sub('%s[^%s]*%s' % (M_OPEN, M_CLOSE, M_CLOSE), '', stripped)
            _check_common(source, without, viol); return viol
        nodes, reason = parse_gender_plain(target)
        if nodes is None: return [('InvalidStandardMacro', reason)]
        if MARCA in target: viol.append(('StrayDelimiter', 'marca U+E0F0 sin <NewLine> al que seguir (fuente sin payloads)'))
        sc, tc = _ctrl(source), _ctrl(target)
        if sc != tc: viol.append(('ControlCharMismatch', 'control bytes differ'))
        return viol
    _check_common(source, target, viol)
    return viol
