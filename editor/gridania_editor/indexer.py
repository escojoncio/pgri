"""Indice SQLite de celdas y clasificacion por color.
ROJO    = celda nueva o con japones cambiado y SIN traduccion vigente.
NARANJA = japones cambiado (hash `h` de la traduccion != hash del ja actual) con traduccion antigua conservada: a revisar.
VERDE   = traducida con hash vigente (origen de la lista blanca, estado traducida/revisada).
BLANCO  = ya existia (mismo japones que el repo importado) pero sin traduccion vigente."""
import json, os, re, sqlite3, threading, time
from . import clases

ESTADOS = ('rojo', 'naranja', 'verde', 'blanco')
ORIGENES_VALIDOS = ('fr-ja-retrad', 'reutilizada', 'fr-media', 'sesion', 'previo-ja')
PART_RE = re.compile(r'_part\d\d$')
ESQUEMA = '''
CREATE TABLE IF NOT EXISTS celdas (id INTEGER PRIMARY KEY, hoja TEXT NOT NULL, row INTEGER NOT NULL, sub INTEGER, col INTEGER NOT NULL,
  estado TEXT NOT NULL, h TEXT, ja TEXT, fr TEXT, es TEXT, es_json TEXT, origen TEXT, h_es TEXT, editada INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS i_estado ON celdas(estado); CREATE INDEX IF NOT EXISTS i_hoja ON celdas(hoja, row, col);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
'''


class Base(object):
    """conexion compartida entre hilos del servidor, serializada con un cerrojo"""
    def __init__(self, ruta):
        self.ruta = ruta; self.lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
        self.con = sqlite3.connect(ruta, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        with self.lock: self.con.executescript(ESQUEMA); self.con.commit()
        self.con.create_function('clase', 1, clases.clase_de, deterministic=True)
        self.registrar_flujo(lambda hoja, row, sub, col: 'sin')

    def registrar_flujo(self, fn):
        """fn(hoja,row,sub,col) -> 'por_hacer' | 'hecho' | 'sin'; disponible en SQL como flujo(hoja,row,sub,col)"""
        with self.lock: self.con.create_function('flujo', 4, fn)

    def q(self, sql, args=()):
        with self.lock: return self.con.execute(sql, args).fetchall()

    def x(self, sql, args=()):
        with self.lock:
            c = self.con.execute(sql, args); self.con.commit(); return c

    def cerrar(self):
        with self.lock: self.con.close()


def listar_jsonl(base, quitar_part=False):
    out = set()
    if not os.path.isdir(base): return out
    for d, _, fs in os.walk(base):
        for f in fs:
            if f.endswith('.jsonl'):
                h = os.path.relpath(os.path.join(d, f), base)[:-6].replace(os.sep, '/')
                out.add(PART_RE.sub('', h) if quitar_part else h)
    return out


def leer_trad(ruta):
    """{(row,sub,col): linea} (la ultima gana)"""
    d = {}
    if os.path.exists(ruta):
        with open(ruta, encoding='utf-8') as f:
            for l in f:
                if not l.strip(): continue
                try: e = json.loads(l)
                except ValueError: continue
                if isinstance(e, dict) and isinstance(e.get('row'), int) and isinstance(e.get('col'), int): d[(e['row'], e.get('sub'), e['col'])] = e
    return d


def plano(es):
    if isinstance(es, list): return ' '.join(x for x in es if isinstance(x, str))
    return es if isinstance(es, str) else ''


def clasificar(t, h_nuevo, ja_igual_al_previo):
    """t = linea de traduccion o None; -> (estado, vigente)"""
    vigente = bool(t) and t.get('origen') in ORIGENES_VALIDOS and t.get('estado') in ('traducida', 'revisada') and bool(plano(t.get('es')).strip())
    if vigente:
        return ('verde' if t.get('h') == h_nuevo else 'naranja'), True
    return ('blanco' if ja_igual_al_previo else 'rojo'), False


def indexar(R, base, repo_dir, raiz_ja_nuevo, ediciones_dir, progreso=print):
    """Reconstruye la tabla `celdas`. raiz_ja_nuevo = carpeta con textos/ja (juego extraido, o repo_dir si no hay extraccion)."""
    G = R.G
    previo = repo_dir
    nuevas = listar_jsonl(os.path.join(raiz_ja_nuevo, 'textos', 'ja'), True)
    trads = listar_jsonl(os.path.join(repo_dir, 'traducciones')) | listar_jsonl(os.path.join(ediciones_dir, 'traducciones'))
    hojas = sorted(nuevas | trads)
    base.x('DELETE FROM celdas')
    cnt = {e: 0 for e in ESTADOS}; eliminadas = 0; n = 0
    for i, hoja in enumerate(hojas):
        ja = G.leer_ja(raiz_ja_nuevo, hoja) or {}
        ja_prev = ja if os.path.abspath(raiz_ja_nuevo) == os.path.abspath(previo) else (G.leer_ja(previo, hoja) or {})
        frs = R.NC.leer_fr(raiz_ja_nuevo, hoja)
        tr = leer_trad(os.path.join(repo_dir, 'traducciones', *hoja.split('/')) + '.jsonl')
        ed = leer_trad(os.path.join(ediciones_dir, 'traducciones', *hoja.split('/')) + '.jsonl')
        tr.update(ed)
        filas = []
        for k in sorted(ja, key=lambda k: (k[0], -1 if k[1] is None else k[1], k[2])):
            text, raw = ja[k]; t = tr.get(k)
            if t is None and not G.tiene_cjk(text): continue
            h = G.hash_ja(text)
            pv = ja_prev.get(k)
            estado, vig = clasificar(t, h, pv is not None and pv[0] == text)
            cnt[estado] += 1
            es = t.get('es') if t else None
            filas.append((hoja, k[0], k[1], k[2], estado, h, text, frs.get(k, ''), plano(es) if vig or t else '', json.dumps(es, ensure_ascii=False) if t else None,
                          t.get('origen') if t else None, t.get('h') if t else None, 1 if k in ed else 0))
        eliminadas += sum(1 for k in tr if k not in ja)
        if filas:
            with base.lock:
                base.con.executemany('INSERT INTO celdas(hoja,row,sub,col,estado,h,ja,fr,es,es_json,origen,h_es,editada) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', filas); base.con.commit()
        n += len(filas)
        if i % 100 == 0: progreso('indexando %d/%d (%s) celdas=%d' % (i, len(hojas), hoja, n))
    meta = {'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'celdas': n, 'eliminadas_del_juego': eliminadas, 'contadores': cnt,
            'fuente': 'juego' if os.path.abspath(raiz_ja_nuevo) != os.path.abspath(previo) else 'repo'}
    base.x('INSERT OR REPLACE INTO meta(k,v) VALUES (?,?)', ('indexado', json.dumps(meta)))
    progreso('indice listo: %s' % json.dumps(cnt))
    return meta


def meta(base, k='indexado'):
    r = base.q('SELECT v FROM meta WHERE k=?', (k,))
    return json.loads(r[0]['v']) if r else None


def _donde(hoja=None, estados=None, q=None, solo_editadas=False, clase=None, flujo=None):
    w = []; a = []
    if hoja: w.append('hoja=?'); a.append(hoja)
    if clase: w.append('clase(hoja)=?'); a.append(clase)
    if flujo: w.append('flujo(hoja,row,sub,col)=?'); a.append(flujo)
    if estados: w.append('estado IN (%s)' % ','.join('?' * len(estados))); a += list(estados)
    if q:
        w.append("(ja LIKE ? ESCAPE '\\' OR es LIKE ? ESCAPE '\\')"); a += ['%' + _esc(q) + '%'] * 2
    if solo_editadas: w.append('editada=1')
    return ((' WHERE ' + ' AND '.join(w)) if w else ''), a


def contadores(base, hoja=None, clase=None, flujo=None):
    cond, a = _donde(hoja, clase=clase, flujo=flujo)
    d = {e: 0 for e in ESTADOS}
    for r in base.q('SELECT estado, COUNT(*) n FROM celdas' + cond + ' GROUP BY estado', a): d[r['estado']] = r['n']
    return d


def contadores_flujo(base, hoja=None, estados=None, q=None, solo_editadas=False, clase=None):
    """celdas por estado de flujo con los demas filtros aplicados (sin filtrar por flujo)"""
    cond, a = _donde(hoja, estados, q, solo_editadas, clase)
    d = {'por_hacer': 0, 'hecho': 0, 'sin': 0}
    for r in base.q('SELECT flujo(hoja,row,sub,col) f, COUNT(*) n FROM celdas' + cond + ' GROUP BY f', a): d[r['f']] = r['n']
    return d


def contadores_clase(base, hoja=None, estados=None, q=None, solo_editadas=False, flujo=None):
    cond, a = _donde(hoja, estados, q, solo_editadas, None, flujo)
    d = {c: 0 for c in clases.CLASES}
    for r in base.q('SELECT clase(hoja) c, COUNT(*) n FROM celdas' + cond + ' GROUP BY c', a): d[r['c']] = r['n']
    return d


def hojas_resumen(base, q=None):
    sql = 'SELECT hoja, estado, COUNT(*) n FROM celdas' + (" WHERE hoja LIKE ? ESCAPE '\\'" if q else '') + ' GROUP BY hoja, estado'
    res = {}
    for r in base.q(sql, (('%' + _esc(q) + '%',) if q else ())):
        res.setdefault(r['hoja'], {e: 0 for e in ESTADOS})[r['estado']] = r['n']
    return [dict(hoja=h, **c, total=sum(c.values())) for h, c in sorted(res.items())]


def _esc(s):
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def listar(base, hoja=None, estados=None, q=None, offset=0, limite=100, solo_editadas=False, clase=None, flujo=None):
    cond, a = _donde(hoja, estados, q, solo_editadas, clase, flujo)
    total = base.q('SELECT COUNT(*) n FROM celdas' + cond, a)[0]['n']
    filas = base.q('SELECT id,hoja,row,sub,col,estado,substr(ja,1,120) ja,substr(es,1,120) es,origen,editada,clase(hoja) clase,flujo(hoja,row,sub,col) flujo FROM celdas' + cond + ' ORDER BY id LIMIT ? OFFSET ?', a + [limite, offset])
    return total, [dict(r) for r in filas]


def celdas_filtradas(base, hoja=None, estados=None, q=None, solo_editadas=False, clase=None, flujo=None):
    """todas las celdas (hoja,row,sub,col) que cumplen el filtro (para marcar en bloque)"""
    cond, a = _donde(hoja, estados, q, solo_editadas, clase, flujo)
    return [(r['hoja'], r['row'], r['sub'], r['col']) for r in base.q('SELECT hoja,row,sub,col FROM celdas' + cond + ' ORDER BY id', a)]


def obtener(base, id_):
    r = base.q('SELECT * FROM celdas WHERE id=?', (id_,))
    return dict(r[0]) if r else None
