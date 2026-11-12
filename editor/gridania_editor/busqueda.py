"""Busqueda global (JP, FR, ES a la vez) sobre un indice EN MEMORIA, y reemplazo sobre el ES.
Modos: subcadena | exacto (campo completo) | palabra (palabra completa) | regex. Opciones: distinguir mayusculas, distinguir tildes.
Las comparaciones sin mayusculas/tildes usan un plegado que conserva la longitud (las posiciones del resaltado valen para el texto original)."""
import csv, re, unicodedata
from . import clases

CAMPOS = ('ja', 'fr', 'es')
MODOS = ('subcadena', 'exacto', 'palabra', 'regex')


class _Tabla(dict):
    def __init__(self, bajar, quitar): self.bajar = bajar; self.quitar = quitar
    def __missing__(self, o):
        c = chr(o)
        if self.quitar:
            d = unicodedata.normalize('NFD', c)
            if len(d) > 1 and all(unicodedata.combining(x) for x in d[1:]): c = d[0]
        if self.bajar and len(c.lower()) == 1: c = c.lower()
        self[o] = ord(c) if len(c) == 1 else o
        return self[o]


_TABLAS = {}


def plegar(s, mayus, tildes):
    """mayus/tildes = distinguir. Conserva la longitud."""
    if mayus and tildes: return s
    k = (not mayus, not tildes)
    if k not in _TABLAS: _TABLAS[k] = _Tabla(*k)
    return s.translate(_TABLAS[k])


class Consulta(object):
    def __init__(self, texto, campos=('ja', 'fr', 'es'), modo='subcadena', mayus=False, tildes=False, estados=None, hoja=None, clase=None, flujo=None):
        if not texto: raise ValueError('escribe algo que buscar')
        if modo not in MODOS: raise ValueError('modo desconocido: %s' % modo)
        self.texto = texto; self.campos = [c for c in campos if c in CAMPOS]; self.modo = modo; self.mayus = bool(mayus); self.tildes = bool(tildes)
        self.estados = set(estados) if estados else None; self.hoja = hoja or None
        self.clase = clase or None; self.flujo = flujo or None
        if not self.campos: raise ValueError('elige al menos un campo (ja, fr, es)')
        try: self.rx = self._compilar()
        except re.error as x: raise ValueError('expresion regular no valida: %s' % x)

    def _compilar(self):
        if self.modo == 'regex':
            pat = plegar(self.texto, True, self.tildes)
            return re.compile(pat, 0 if self.mayus else re.I)
        pat = re.escape(plegar(self.texto, self.mayus, self.tildes))
        if self.modo == 'palabra': pat = r'(?<!\w)' + pat + r'(?!\w)'
        return re.compile(pat)

    def buscar(self, plegado):
        """plegado = texto ya plegado -> match | None"""
        return self.rx.fullmatch(plegado) if self.modo == 'exacto' else self.rx.search(plegado)

    def plegar_texto(self, s):
        if self.modo == 'regex': return plegar(s, True, self.tildes)
        return plegar(s, self.mayus, self.tildes)

    def reemplazar(self, s, nuevo):
        """aplica la sustitucion sobre el texto ORIGINAL usando las posiciones del plegado -> (resultado, n)"""
        f = self.plegar_texto(s); out = []; prev = 0; n = 0
        if self.modo == 'exacto':
            m = self.rx.fullmatch(f); it = [m] if m else []
        else: it = list(self.rx.finditer(f))
        for m in it:
            if m.end() == m.start(): continue
            out.append(s[prev:m.start()])
            out.append(m.expand(nuevo) if self.modo == 'regex' else nuevo)
            prev = m.end(); n += 1
        out.append(s[prev:])
        return ''.join(out), n


def _frag(texto, m, ctx=40):
    a = max(0, m.start() - ctx); b = min(len(texto), m.end() + ctx)
    return {'t': ('...' if a else '') + texto[a:b] + ('...' if b < len(texto) else ''), 'ini': m.start() - a + (3 if a else 0), 'fin': m.end() - a + (3 if a else 0)}


class Indice(object):
    def __init__(self):
        self.filas = []        # dicts: id, hoja, row, sub, col, estado, ja, fr, es
        self.por_id = {}
        self.flujo = None      # objeto flujo.Flujo (opcional) para filtrar por estado de flujo
        self._cache = {}       # (campo, mayus, tildes, regex?) -> lista plegada

    @classmethod
    def desde_base(cls, base):
        i = cls()
        for r in base.q('SELECT id,hoja,row,sub,col,estado,ja,fr,es FROM celdas ORDER BY id'):
            i.anadir(dict(r))
        return i

    def anadir(self, f):
        f['ja'] = f.get('ja') or ''; f['fr'] = f.get('fr') or ''; f['es'] = f.get('es') or ''
        self.por_id[f['id']] = len(self.filas); self.filas.append(f); self._cache.clear()

    def actualizar(self, id_, es, estado):
        f = self.filas[self.por_id[id_]]; f['es'] = es; f['estado'] = estado; self._cache = {k: v for k, v in self._cache.items() if k[0] != 'es'}

    def _plegados(self, campo, q):
        k = (campo, q.modo == 'regex', q.mayus if q.modo != 'regex' else True, q.tildes)
        if k not in self._cache: self._cache[k] = [q.plegar_texto(f[campo]) for f in self.filas]
        return self._cache[k]

    def coincidencias(self, q):
        """generador de (fila, {campo: match}) en orden de id"""
        pl = {c: self._plegados(c, q) for c in q.campos}
        for i, f in enumerate(self.filas):
            if q.hoja and f['hoja'] != q.hoja: continue
            if q.estados and f['estado'] not in q.estados: continue
            if q.clase and clases.clase_de(f['hoja']) != q.clase: continue
            if q.flujo and (self.flujo.estado(f['hoja'], f['row'], f['sub'], f['col']) if self.flujo else 'sin') != q.flujo: continue
            ms = {}
            for c in q.campos:
                t = pl[c][i]
                if not t: continue
                m = q.buscar(t)
                if m is not None and (m.end() > m.start() or q.modo == 'exacto'): ms[c] = m
            if ms: yield f, ms

    def buscar(self, q, offset=0, limite=100):
        """-> dict(total, por_hoja, por_estado, resultados[...])"""
        total = 0; por_hoja = {}; por_estado = {}; res = []
        for f, ms in self.coincidencias(q):
            total += 1; por_hoja[f['hoja']] = por_hoja.get(f['hoja'], 0) + 1; por_estado[f['estado']] = por_estado.get(f['estado'], 0) + 1
            if offset <= total - 1 < offset + limite:
                res.append({'id': f['id'], 'hoja': f['hoja'], 'row': f['row'], 'sub': f['sub'], 'col': f['col'], 'estado': f['estado'],
                            'clase': clases.clase_de(f['hoja']), 'flujo': self.flujo.estado(f['hoja'], f['row'], f['sub'], f['col']) if self.flujo else 'sin',
                            'campos': {c: _frag(f[c], m) for c, m in ms.items()}})
        return {'total': total, 'por_hoja': dict(sorted(por_hoja.items(), key=lambda x: -x[1])), 'por_estado': por_estado, 'resultados': res}

    def exportar(self, q, ruta):
        n = 0
        with open(ruta, 'w', encoding='utf-8', newline='') as fo:
            w = csv.writer(fo, delimiter='\t', lineterminator='\n'); w.writerow(['hoja', 'row', 'sub', 'col', 'estado', 'campo', 'fragmento'])
            for f, ms in self.coincidencias(q):
                n += 1
                for c, m in ms.items():
                    fr = _frag(f[c], m, 60)
                    w.writerow([f['hoja'], f['row'], '' if f['sub'] is None else f['sub'], f['col'], f['estado'], c, fr['t'][:fr['ini']] + '[[' + fr['t'][fr['ini']:fr['fin']] + ']]' + fr['t'][fr['fin']:]])
        return n
