#!/usr/bin/env python3
"""Volcado de todo el texto japones de FFXIV (SqPack 0a0000 -> EXH/EXD).
Uso: python3 -I extract_ja.py <dir con 0a0000.win32.*> <dir salida (textos)>
Solo biblioteca estandar. Salida: <out>/ja/<hoja>.jsonl, <out>/INDEX.csv, <out>/_report.txt
"""
import sys, struct, zlib, os, re, csv, json, collections

MAXBYTES = 50 * 1024 * 1024
LANG = {0: '', 1: 'ja', 2: 'en', 3: 'de', 4: 'fr', 5: 'chs', 6: 'cht', 7: 'ko'}

def crc(s):
    return zlib.crc32(s.lower().encode()) ^ 0xFFFFFFFF

class Pack:
    def __init__(self, D):
        self.D = D
        idx = open(os.path.join(D, '0a0000.win32.index'), 'rb').read()
        hs = struct.unpack_from('<I', idx, 0xC)[0]
        so, ss = struct.unpack_from('<II', idx, hs + 8)
        self.entries = {}
        for o in range(so, so + ss, 16):
            fh, dh, data, _ = struct.unpack_from('<IIII', idx, o)
            self.entries[(dh, fh)] = data
        self.dats = {}

    def dat(self, n):
        if n not in self.dats:
            self.dats[n] = open(os.path.join(self.D, '0a0000.win32.dat%d' % n), 'rb').read()
        return self.dats[n]

    def read(self, path):
        folder, name = path.rsplit('/', 1)
        d = self.entries.get((crc(folder), crc(name)))
        if d is None:
            return None
        buf = self.dat((d >> 1) & 7)
        off = (d & ~0xF) * 8
        hsz, typ, raw, _, _, nblk = struct.unpack_from('<IIIIII', buf, off)
        if typ != 2:
            raise ValueError('tipo de archivo %d' % typ)
        out = bytearray()
        for i in range(nblk):
            boff, csz, usz = struct.unpack_from('<IHH', buf, off + 24 + 8 * i)
            b = off + hsz + boff
            _, _, c, u = struct.unpack_from('<IIII', buf, b)
            if c == 32000:
                out += buf[b + 16:b + 16 + u]
            else:
                out += zlib.decompress(buf[b + 16:b + 16 + c], -15)
        if len(out) != raw:
            raise ValueError('tamano descomprimido %d != %d' % (len(out), raw))
        return bytes(out)

# ---------- SeString <-> marcadores ----------
def _pint(raw, i):
    """entero empaquetado en raw[i]: devuelve (valor, bytes_usados) o None."""
    b = raw[i]
    if b < 0xF0:
        return b - 1, 1
    if b > 0xFE:
        return None
    flags = (b + 1) & 0xF
    v = 0; k = 1
    for bit in (3, 2, 1, 0):
        if flags & (1 << bit):
            if i + k >= len(raw):
                return None
            v |= raw[i + k] << (8 * bit); k += 1
    return v, k

def _pint_enc(v):
    if v < 0xEF:
        return bytes([v + 1])
    mask = 0; bs = bytearray()
    for bit in (3, 2, 1, 0):
        x = (v >> (8 * bit)) & 0xFF
        if x:
            mask |= 1 << bit; bs.append(x)
    return bytes([0xF0 | (mask - 1)]) + bytes(bs)

def se_encode(raw):
    """bytes -> texto con marcadores {0xTT:payloadhex} (codigo) y {0xNN} (byte de control suelto)."""
    out = []; i = 0; n = len(raw)
    while i < n:
        c = raw[i]
        if c == 2 and i + 2 < n:
            pi = _pint(raw, i + 2)
            if pi is not None and pi[0] >= 0:
                ln, used = pi
                st = i + 2 + used
                end = st + ln
                if end < n and raw[end] == 3:
                    out.append('{0x%02X:%s}' % (raw[i + 1], raw[st:end].hex()))
                    i = end + 1
                    continue
        if c < 0x20 and c not in (9, 10):
            out.append('{0x%02X}' % c); i += 1; continue
        j = i
        while j < n and (raw[j] >= 0x20 or raw[j] in (9, 10)):
            j += 1
        out.append(raw[i:j].decode('utf-8', 'replace')); i = j
    return ''.join(out)

_MK = re.compile(r'\{0x([0-9A-F]{2}):([0-9a-f]*)\}|\{0x([0-9A-F]{2})\}')
def se_decode(text):
    out = bytearray(); p = 0
    for m in _MK.finditer(text):
        out += text[p:m.start()].encode('utf-8')
        if m.group(1) is not None:
            pl = bytes.fromhex(m.group(2))
            out += bytes([2, int(m.group(1), 16)]) + _pint_enc(len(pl)) + pl + b'\x03'
        else:
            out.append(int(m.group(3), 16))
        p = m.end()
    out += text[p:].encode('utf-8')
    return bytes(out)

# ---------- EXH / EXD ----------
def exh(pk, sheet):
    b = pk.read('exd/%s.exh' % sheet)
    if b is None:
        return None
    if b[:4] != b'EXHF':
        raise ValueError('EXH sin magic')
    dsz, ncol, npage, nlang = struct.unpack_from('>HHHH', b, 6)
    variant = b[0x11]
    cols = [struct.unpack_from('>HH', b, 0x20 + 4 * i) for i in range(ncol)]
    p = 0x20 + 4 * ncol
    pages = [struct.unpack_from('>II', b, p + 8 * i) for i in range(npage)]
    p += 8 * npage
    langs = [LANG.get(b[p + 2 * i], '?%d' % b[p + 2 * i]) for i in range(nlang)]
    return dict(dsz=dsz, cols=cols, pages=pages, langs=langs, variant=variant)

def read_rows(pk, sheet, h, lang, stats):
    """-> dict {(rid, sub|None): {col: (texto, raw_o_None)}}  solo cadenas no vacias"""
    strcols = [i for i, (t, _) in enumerate(h['cols']) if t == 0]
    res = {}
    dsz = h['dsz']
    for start, cnt in h['pages']:
        name = 'exd/%s_%d%s.exd' % (sheet, start, ('_' + lang) if lang else '')
        b = pk.read(name)
        if b is None:
            stats['pages_missing'].append(name); continue
        isz = struct.unpack_from('>I', b, 8)[0]
        for o in range(0x20, 0x20 + isz, 8):
            rid, roff = struct.unpack_from('>II', b, o)
            _, nsub = struct.unpack_from('>IH', b, roff)
            if h['variant'] == 2:
                # subfilas: [u16 id + dsz] x nsub, y despues un unico heap de cadenas
                heap = roff + 6 + nsub * (2 + dsz)
                bases = [(struct.unpack_from('>H', b, roff + 6 + k * (2 + dsz))[0], roff + 6 + k * (2 + dsz) + 2, heap) for k in range(nsub)]
            else:
                bases = [(None, roff + 6, roff + 6 + dsz)]
            for sub, base, heap in bases:
                d = {}
                for ci in strcols:
                    co = h['cols'][ci][1]
                    so = struct.unpack_from('>I', b, base + co)[0]
                    s = heap + so
                    e = b.index(b'\0', s)
                    raw = b[s:e]
                    if not raw:
                        continue
                    t = se_encode(raw)
                    r = None
                    if se_decode(t) != raw:
                        r = raw.hex(); stats['raw_fallback'] += 1
                    d[ci] = (t, r)
                res[(rid, sub)] = d
    return res

def write_sheet(out_root, sheet, rows, lang_dir='ja'):
    """escribe jsonl (partiendo si >50MB). Devuelve [(ruta_rel, bytes)]"""
    keys = sorted(rows, key=lambda k: (k[0], -1 if k[1] is None else k[1]))
    lines = []
    for k in keys:
        for ci in sorted(rows[k]):
            t, r = rows[k][ci]
            o = {'row': k[0], 'sub': k[1], 'col': ci, 'text': t}
            if r is not None:
                o['raw'] = r
            lines.append((k[0], json.dumps(o, ensure_ascii=False, separators=(',', ':')) + '\n'))
    total = sum(len(l.encode('utf-8')) for _, l in lines)
    parts = []
    if total <= MAXBYTES:
        parts.append(lines)
    else:
        cur = []; sz = 0; lastrow = None
        for rid, l in lines:
            bl = len(l.encode('utf-8'))
            if sz + bl > MAXBYTES and cur and rid != lastrow:
                parts.append(cur); cur = []; sz = 0
            cur.append((rid, l)); sz += bl; lastrow = rid
        if cur:
            parts.append(cur)
    res = []
    for pi, part in enumerate(parts):
        rel = lang_dir + '/' + sheet + ('' if len(parts) == 1 else '_part%02d' % (pi + 1)) + '.jsonl'
        path = os.path.join(out_root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(''.join(l for _, l in part))
        res.append((rel, os.path.getsize(path), part[0][0], part[-1][0]))
    return res, len(lines)

def main():
    D, OUT = sys.argv[1], sys.argv[2]
    os.makedirs(OUT, exist_ok=True)
    pk = Pack(D)
    exl = pk.read('exd/root.exl').decode().splitlines()
    sheets = [l.split(',')[0] for l in exl[1:] if l.strip()]
    stats = dict(pages_missing=[], raw_fallback=0)
    index = []; unread = []; nread = 0; nstr_sheets = 0; collisions = collections.Counter()
    for s in sheets:
        collisions[s.lower()] += 1
    for si, sheet in enumerate(sheets):
        try:
            h = exh(pk, sheet)
            if h is None:
                unread.append((sheet, 'sin EXH en el pack')); continue
            strcols = [i for i, (t, _) in enumerate(h['cols']) if t == 0]
            lang = 'ja' if 'ja' in h['langs'] else ('' if h['langs'] == [''] else None)
            if lang is None:
                unread.append((sheet, 'sin pagina ja (idiomas EXH: %s)' % h['langs'])); continue
            nread += 1
            if not strcols:
                continue
            nstr_sheets += 1
            rows = read_rows(pk, sheet, h, lang, stats)
            parts, nstrings = write_sheet(OUT, sheet, rows) if any(rows.values()) else ([], 0)
            if not parts:
                index.append((sheet, '', len(rows), len(strcols), 0, 0, lang or 'neutral'))
            for rel, sz, r0, r1 in parts:
                index.append((sheet, rel, len(rows), len(strcols), nstrings, sz, lang or 'neutral'))
        except Exception as e:
            nread -= 0
            unread.append((sheet, '%s: %s' % (type(e).__name__, e)))
        if si % 500 == 0:
            print(si, len(sheets), flush=True)
    index.sort(key=lambda r: (r[0], r[1]))
    with open(os.path.join(OUT, 'INDEX.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['hoja', 'archivo', 'filas', 'columnas_string', 'cadenas_no_vacias', 'bytes', 'pagina_idioma'])
        w.writerows(index)
    with open(os.path.join(OUT, '_report.txt'), 'w', encoding='utf-8') as f:
        f.write('hojas root.exl: %d\nhojas leidas (con pagina ja o neutra): %d\nhojas con columnas string: %d\n' % (len(sheets), nread, nstr_sheets))
        f.write('raw_fallback: %d\npaginas ausentes: %d\n' % (stats['raw_fallback'], len(stats['pages_missing'])))
        for p in stats['pages_missing'][:200]: f.write('  falta %s\n' % p)
        f.write('colisiones de mayusculas: %s\n' % [k for k, v in collisions.items() if v > 1])
        f.write('no leidas: %d\n' % len(unread))
        for s, r in unread: f.write('  %s\t%s\n' % (s, r))
    print(open(os.path.join(OUT, '_report.txt')).read()[:3000])

if __name__ == '__main__':
    main()
