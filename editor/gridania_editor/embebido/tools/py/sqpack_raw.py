"""Lector SqPack/EXD mínimo (solo lectura) que entrega los BYTES CRUDOS de cada cadena.
Basado en scripts/ffxiv_text.py (index1 + dat deflate)."""
import struct, zlib, os

# Codigos del byte de idioma del EXH. Verificado con la instalacion: 0 (neutra), 1 ja, 2 en, 3 de, 4 fr; el 5 aparece
# en todas las hojas con idioma (chs en Lumina); 6 no aparece; 7 y 8 aparecen pero el C# del repo no fija su valor
# numerico (solo los nombres en LanguageCodes.cs; el enum esta en Lumina, ausente) -> no se asignan, se devuelven como '?N'.
LANG = {0:'',1:'ja',2:'en',3:'de',4:'fr',5:'chs'}

class Pack:
    def __init__(self, d):
        self.d = d
        idx = open(os.path.join(d, '0a0000.win32.index'), 'rb').read()
        hs = struct.unpack_from('<I', idx, 0xC)[0]
        so, ss = struct.unpack_from('<II', idx, hs + 8)
        self.entries = {}
        for o in range(so, so + ss, 16):
            fh, dh, data, _ = struct.unpack_from('<IIII', idx, o)
            self.entries[(dh, fh)] = data
        self.dats = {}
    @staticmethod
    def crc(s): return zlib.crc32(s.lower().encode()) ^ 0xFFFFFFFF
    def _dat(self, n):
        if n not in self.dats: self.dats[n] = open(os.path.join(self.d, '0a0000.win32.dat%d' % n), 'rb').read()
        return self.dats[n]
    def read(self, path):
        folder, name = path.rsplit('/', 1)
        dd = self.entries.get((self.crc(folder), self.crc(name)))
        if dd is None: return None
        n = (dd >> 1) & 7; off = (dd & ~0xF) * 8
        buf = self._dat(n)
        hsz, typ, raw, _, _, nblk = struct.unpack_from('<IIIIII', buf, off)
        assert typ == 2, typ
        out = bytearray()
        for i in range(nblk):
            boff, csz, usz = struct.unpack_from('<IHH', buf, off + 24 + 8 * i)
            b = off + hsz + boff
            _, _, c, u = struct.unpack_from('<IIII', buf, b)
            out += buf[b+16:b+16+u] if c == 32000 else zlib.decompress(buf[b+16:b+16+c], -15)
        assert len(out) == raw
        return bytes(out)
    def exh(self, sheet):
        b = self.read('exd/%s.exh' % sheet.lower())
        if b is None: return None
        assert b[:4] == b'EXHF'
        dsz, ncol, npage, nlang = struct.unpack_from('>HHHH', b, 6)
        variant = b[0x11] if len(b) > 0x11 else None
        cols = [struct.unpack_from('>HH', b, 0x20 + 4 * i) for i in range(ncol)]
        p = 0x20 + 4 * ncol
        pages = [struct.unpack_from('>II', b, p + 8 * i) for i in range(npage)]
        p += 8 * npage
        langs = [LANG.get(b[p + 2 * i], '?%d' % b[p + 2 * i]) for i in range(nlang)]
        return dict(dsz=dsz, cols=cols, pages=pages, langs=langs, variant=variant)
    def missing_pages(self, sheet, h, lang):
        """-> rutas de paginas EXD que el EXH lista y que no existen en la instalacion"""
        out = []
        for start, cnt in h['pages']:
            p = 'exd/%s_%d%s.exd' % (sheet.lower(), start, ('_' + lang) if lang else '')
            if self.read(p) is None: out.append(p)
        return out
    def rows_raw(self, sheet, h, lang):
        """-> {rowId: (pageStart, {colIndex: bytes_crudos_sin_NUL})} para columnas String (type 0)"""
        res = {}
        for start, cnt in h['pages']:
            b = self.read('exd/%s_%d%s.exd' % (sheet.lower(), start, ('_' + lang) if lang else ''))
            if b is None: continue
            isz = struct.unpack_from('>I', b, 8)[0]
            for o in range(0x20, 0x20 + isz, 8):
                rid, roff = struct.unpack_from('>II', b, o)
                dsize, sub = struct.unpack_from('>IH', b, roff)
                base = roff + 6
                strs = {}
                for ci, (t, co) in enumerate(h['cols']):
                    if t == 0:
                        so = struct.unpack_from('>I', b, base + co)[0]
                        s = base + h['dsz'] + so
                        strs[ci] = b[s:b.index(b'\0', s)]
                res[rid] = (start, strs)
        return res
