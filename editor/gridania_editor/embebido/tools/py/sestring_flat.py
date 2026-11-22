"""Port del camino 'plano' (SeStringParser/SeStringTokenizer) usado por ExdPatcher ANTES del arbol,
y simulacion de la Fase A de ExdPatcher.Patch para una columna con source no vacio."""
import sestring as S

def _read_run_len(b, i):
    r = S.read_len(b, i)
    return (r[0], r[1]) if r else None

def parse_flat(b: bytes):
    segs = []; i = 0; n = len(b)
    while i < n:
        c = b[i]
        if c == 2:
            st = i; i += 1
            while i < n and b[i] != 3: i += 1
            if i < n: i += 1
            segs.append(('pay', b[st:i]))
        elif c == 0xFF:
            st = i; r = _read_run_len(b, i + 1)
            if r and r[1] + r[0] <= n: i = r[1] + r[0]
            else: i = st + 1
            segs.append(('pay', b[st:i]))
        elif c == 0: break
        else:
            lit = bytearray()
            while i < n and b[i] != 2 and b[i] != 0:
                x = b[i]
                if x <= 0x7F: lit.append(x); i += 1
                elif (x & 0xC0) == 0x80: break
                elif (x & 0xE0) == 0xC0:
                    if i+1 < n and (b[i+1] & 0xC0) == 0x80: lit += b[i:i+2]; i += 2
                    else: break
                elif (x & 0xF0) == 0xE0:
                    if i+2 < n and (b[i+1] & 0xC0) == 0x80 and (b[i+2] & 0xC0) == 0x80: lit += b[i:i+3]; i += 3
                    else: break
                elif (x & 0xF8) == 0xF0:
                    if i+3 < n and all((b[i+k] & 0xC0) == 0x80 for k in (1,2,3)): lit += b[i:i+4]; i += 4
                    else: break
                else: break
            if lit: segs.append(('lit', bytes(lit).decode('utf-8')))
            if i < n and b[i] != 2 and b[i] != 0 and b[i] != 0xFF:
                segs.append(('pay', bytes([b[i]]))); i += 1
    return segs

def ser_flat(segs):
    return b''.join(s[1].encode('utf-8') if s[0] == 'lit' else s[1] for s in segs)

def tokenize_flat(segs):
    sb = []; toks = []; counts = {}
    for s in segs:
        if s[0] == 'lit': sb.append(s[1].replace('<', '<<'))
        else:
            bn = S.base_name(s[1]); counts[bn] = counts.get(bn, 0) + 1
            t = '<%s>' % bn if counts[bn] == 1 else '<%s#%d>' % (bn, counts[bn])
            sb.append(t); toks.append((t, s[1]))
    return ''.join(sb), toks

def _known_body(body):
    h = body.find('#'); bn = body if h < 0 else body[:h]
    if h >= 0 and (h == len(body) - 1 or not body[h+1:].isdigit() or not body[h+1:].isascii()): return False
    return bn in S.KNOWN_BASE or (len(bn) == 9 and bn.startswith('Payload') and all(c in '0123456789abcdefABCDEF' for c in bn[7:]))

def find_refs(text):
    refs = []; i = 0
    while i < len(text):
        if text[i] != '<': i += 1; continue
        if i + 1 < len(text) and text[i+1] == '<': i += 2; continue
        c = text.find('>', i + 1)
        if c < 0: i += 1; continue
        if _known_body(text[i+1:c]): refs.append(text[i:c+1]); i = c
        i += 1
    return refs

def unsafe_ctrl(text):
    return [c for c in text if (c <= '\x08' or c in '\x0b\x0c' or '\x0e' <= c <= '\x1f') and c != '\0']

def try_replace(segs, source, target):
    if not source: return None, 'source is empty'
    if S.has_reserved(target): return None, 'target contains standard macros requiring run-aware translation'
    if S.MARCA in target: return None, 'target contains NewLine-suppression markers requiring run-aware translation'   # pgri: la marca U+E0F0 solo la entiende la via run-aware
    if S.contiene_color_propio(target): return None, 'target contains own colours requiring run-aware translation'   # colores propios (<UIColor:..>): solo la via run-aware
    if sorted(find_refs(source)) != sorted(find_refs(target)): return None, 'target token references do not match source'
    if unsafe_ctrl(source) != unsafe_ctrl(target): return None, 'target control references do not match source'
    idx = -1
    for i, s in enumerate(segs):
        if s[0] == 'lit' and source in s[1]: idx = i
    if idx < 0: return None, 'source spans multiple literal segments'
    new = list(segs); new[idx] = ('lit', segs[idx][1].replace(source, target)); return new, None

def try_replace_tokenized(segs, source, target):
    if not source: return None, 'source is empty'
    if S.has_reserved(target): return None, 'target contains standard macros requiring run-aware translation'
    if S.MARCA in target: return None, 'target contains NewLine-suppression markers requiring run-aware translation'
    if S.contiene_color_propio(target): return None, 'target contains own colours requiring run-aware translation'
    text, toks = tokenize_flat(segs)
    if text != source: return None, "tokenized source does not match the row's tokenized string"
    if unsafe_ctrl(source) != unsafe_ctrl(target): return None, 'target control references do not match source'
    by = dict(toks); used = set(); out = []; lit = []; i = 0
    while i < len(target):
        c = target[i]
        if c != '<': lit.append(c); i += 1; continue
        if i + 1 < len(target) and target[i+1] == '<': lit.append('<'); i += 2; continue
        m = S._match_token_at(target, i, by.keys())
        if m is None: return None, "unmapped or stray '<' at index %d in target" % i
        if lit: out.append(('lit', ''.join(lit))); lit = []
        if m in used: return None, "token '%s' used more than once in target" % m
        used.add(m); out.append(('pay', by[m])); i += len(m)
    if lit: out.append(('lit', ''.join(lit)))
    if len(used) != len(by): return None, 'target uses %d of %d source tokens' % (len(used), len(by))
    return out, None

def run_patch_coherent(vanilla, patched):
    if 0xFF not in vanilla or patched == vanilla: return True
    try: return S.validate(S.tokenize_raw(vanilla), S.tokenize_raw(patched)) == []
    except Exception: return False

def simulate_phase_a(vanilla: bytes, source: str, target: str):
    """Orden de ExdPatcher.Patch (Fase A, columna con source): flat TryReplace -> flat
    TryReplaceTokenized -> SeStringTree.TryTranslate. -> (bytes|None, via, motivo)"""
    segs = parse_flat(vanilla)
    ns, r1 = try_replace(segs, source, target)
    if ns is not None:
        nb = ser_flat(ns)
        return (nb, 'flat-replace', None) if run_patch_coherent(vanilla, nb) else (None, 'flat-replace', 'stale run length')
    ns, r2 = try_replace_tokenized(segs, source, target)
    if ns is not None:
        nb = ser_flat(ns)
        return (nb, 'flat-tokenized', None) if run_patch_coherent(vanilla, nb) else (None, 'flat-tokenized', 'stale run length')
    rb, r3 = S.try_translate(vanilla, source, target)
    if rb is not None: return rb, 'tree', None
    return None, 'miss', '%s | %s | %s' % (r1, r2, r3)
