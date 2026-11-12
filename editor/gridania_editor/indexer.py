"""Indice SQLite de celdas y clasificacion por color.
ROJO    = celda nueva o con japones cambiado y SIN traduccion vigente.
NARANJA = japones cambiado (hash `h` de la traduccion != hash del ja actual) con traduccion antigua conservada: a revisar.
VERDE   = traducida con hash vigente (origen de la lista blanca, estado traducida/revisada).
BLANCO  = ya existia (mismo japones que el repo importado) pero sin traduccion vigente.

Rendimiento: indexado en UNA transaccion (conexion propia: la base sigue legible durante el indexado), parseo de cada hoja una sola vez,
reparto por hojas en procesos paralelos, indice persistente (firma por hoja: solo se reindexan las hojas que cambian) y columnas
materializadas `clase` y `flujo` (con indices SQL) en vez de funciones Python por fila."""
import collections, concurrent.futures, contextlib, hashlib, json, logging, multiprocessing, os, re, sqlite3, threading, time
from . import clases

log = logging.getLogger('gridania.indexer')

ESTADOS = ('rojo', 'naranja', 'verde', 'blanco')
ORIGENES_VALIDOS = ('fr-ja-retrad', 'reutilizada', 'fr-media', 'sesion', 'previo-ja')
PART_RE = re.compile(r'_part\d\d$')
VERSION_INDEXADOR = 3          # sube si cambia la logica de clasificacion o las columnas: invalida las firmas
ESQUEMA_VERSION = 2            # 1 = sin columnas clase/flujo
COLS = 'hoja,row,sub,col,estado,h,ja,fr,es,es_json,origen,h_es,editada,clase,flujo'
ESQUEMA = '''
CREATE TABLE IF NOT EXISTS celdas (id INTEGER PRIMARY KEY, hoja TEXT NOT NULL, row INTEGER NOT NULL, sub INTEGER, col INTEGER NOT NULL,
  estado TEXT NOT NULL, h TEXT, ja TEXT, fr TEXT, es TEXT, es_json TEXT, origen TEXT, h_es TEXT, editada INTEGER DEFAULT 0,
  clase TEXT NOT NULL DEFAULT 'Otros', flujo TEXT NOT NULL DEFAULT 'sin');
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS hojas_idx (hoja TEXT PRIMARY KEY, firma TEXT NOT NULL, elim INTEGER NOT NULL DEFAULT 0);
'''
INDICES = (('i_estado', 'celdas(estado)'), ('i_hoja', 'celdas(hoja, row, col)'), ('i_hoja_ef', 'celdas(hoja, estado, flujo)'),
           ('i_clase', 'celdas(clase)'), ('i_flujo', 'celdas(flujo)'), ('i_ecf', 'celdas(estado, clase, flujo)'))


class Cancelado(Exception):
    pass


class Ocupada(RuntimeError):
    """la base esta siendo indexada/migrada: las escrituras del usuario se rechazan con un mensaje claro (nunca esperan al cerrojo de SQLite)"""


TRAMO_MIGRACION = 50000       # filas (por rango de id) por transaccion de la migracion de `clase`
MIGRANDO = 'migrando la base de datos'
INDEXANDO = 'indexando'


class Base(object):
    """conexion compartida entre hilos del servidor, serializada con un cerrojo (Base.lock). El indexado y la creacion de indices usan conexiones propias (WAL:
    las lecturas siguen) y NO retienen Base.lock; mientras tanto `ocupada` esta activo y las ediciones se rechazan con Ocupada (las marcas de flujo se aplican al terminar)."""
    MARCA_MIGRACION = 'migracion_clase'

    def __init__(self, ruta):
        self.ruta = ruta; self.lock = threading.RLock(); self._fl = None
        self.ocupada = threading.Event(); self._razones = []; self._rz_lock = threading.Lock(); self._flujo_pend = False
        os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
        self.con = self.conectar(timeout=5)     # la conexion compartida nunca espera mucho a otra escritora (el indexado tiene la suya)
        with self.lock:
            self.con.executescript(ESQUEMA)
            self.migrados = self._migrar_columnas()
            if not self.migrados: self._crear_indices(self.con)    # en una BD antigua los indices (lentos) se crean en migrar_datos, en segundo plano
            self.con.commit()

    def conectar(self, timeout=60):
        c = sqlite3.connect(self.ruta, check_same_thread=False, timeout=timeout)
        c.row_factory = sqlite3.Row
        try:
            c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA synchronous=NORMAL')
        except sqlite3.DatabaseError as x:
            log.warning('WAL no disponible: %s', x)
        return c

    def _migrar_columnas(self):
        """bases antiguas (sin clase/flujo): anade las columnas (instantaneo). Los datos (ediciones, es, estado) no se tocan.
        -> lista de columnas anadidas (hay que rellenarlas con migrar_datos)"""
        cols = {r['name'] for r in self.con.execute('PRAGMA table_info(celdas)')}
        nuevas = []
        marca = self.con.execute('SELECT 1 FROM meta WHERE k=?', (self.MARCA_MIGRACION,)).fetchone()
        if 'clase' not in cols and not marca:      # la marca se escribe ANTES de tocar nada: si el proceso muere a medias, el siguiente arranque rehace el relleno
            self.con.execute('INSERT OR REPLACE INTO meta(k,v) VALUES (?,?)', (self.MARCA_MIGRACION, '1')); self.con.commit()
        if 'clase' not in cols: self.con.execute("ALTER TABLE celdas ADD COLUMN clase TEXT NOT NULL DEFAULT 'Otros'"); nuevas.append('clase')
        elif marca: nuevas.append('clase'); log.warning('migracion anterior interrumpida: se rehace el relleno de clase')
        if 'flujo' not in cols: self.con.execute("ALTER TABLE celdas ADD COLUMN flujo TEXT NOT NULL DEFAULT 'sin'"); nuevas.append('flujo')
        if nuevas: log.info('migracion de editor.db: columnas nuevas %s', nuevas)
        return nuevas

    @staticmethod
    def _crear_indices(con):
        for n, d in INDICES: con.execute('CREATE INDEX IF NOT EXISTS %s ON %s' % (n, d))

    @property
    def motivo(self):
        with self._rz_lock: return self._razones[-1] if self._razones else ''

    def ocupar(self, motivo):
        """cada razon (indexando, migrando...) cuenta aparte: la base queda libre solo cuando se han liberado todas"""
        with self._rz_lock: self._razones.append(motivo); self.ocupada.set()

    def liberar(self, motivo=None):
        with self._rz_lock:
            if motivo is None: self._razones and self._razones.pop()
            elif motivo in self._razones: self._razones.remove(motivo)
            if self._razones: return
            self.ocupada.clear()
        if self._flujo_pend:
            self._flujo_pend = False
            try: self.sincronizar_flujo()
            except Exception: log.warning('flujo pendiente', exc_info=True)

    def migrando(self):
        with self._rz_lock: return MIGRANDO in self._razones

    def esperar_migracion(self, progreso=None, cancelar=None):
        """el indexado espera (con mensaje) a que termine la migracion de la base"""
        avisado = False
        while self.migrando():
            if cancelar is not None and cancelar.is_set(): raise Ocupada('Indexado cancelado mientras se migraba la base de datos.')
            if not avisado and progreso: progreso('esperando a que termine la migracion de la base de datos...'); avisado = True
            time.sleep(0.1)

    def exigir_libre(self):
        if self.ocupada.is_set():
            raise Ocupada('Ahora mismo se esta %s; no se puede editar hasta que termine (unos segundos o minutos). Tus cambios no se han perdido: repite la accion despues.' % (self.motivo or 'indexando'))

    def _indices_aparte(self, solo=None):
        """crea indices en una conexion propia (no retiene Base.lock: las lecturas siguen funcionando)"""
        c = self.conectar()
        try:
            for n, d in INDICES:
                if solo is None or n in solo: c.execute('CREATE INDEX IF NOT EXISTS %s ON %s' % (n, d)); c.commit()
        finally: c.close()

    def migrar_datos(self, avance=None):
        """rellena clase (y luego flujo, al vincular) de una base antigua. Idempotente. El cerrojo se toma por lotes cortos; mientras dura, `ocupada` rechaza ediciones.
        Hasta el final queda en meta una marca: si se interrumpe, el siguiente arranque rehace el relleno."""
        if not self.migrados: return
        self.ocupar(MIGRANDO)
        try:
            if 'clase' in self.migrados:
                t0 = time.time()
                # UPDATE por SQL con una tabla temporal hoja->clase (una entrada por hoja) y por tramos de id: cada tramo toma el cerrojo un instante (la UI sigue
                # leyendo entre tramos) y solo reescribe las filas cuya clase cambia
                with self.lock:
                    hojas = [r['hoja'] for r in self.con.execute('SELECT DISTINCT hoja FROM celdas')]
                    self.con.execute('CREATE TEMP TABLE IF NOT EXISTS tmp_clases (hoja TEXT PRIMARY KEY, clase TEXT NOT NULL)')
                    self.con.execute('DELETE FROM tmp_clases')
                    self.con.executemany('INSERT INTO tmp_clases VALUES (?,?)', [(h, clases.clase_de(h)) for h in hojas])
                    lo, hi = self.con.execute('SELECT MIN(id), MAX(id) FROM celdas').fetchone()
                paso = TRAMO_MIGRACION
                if lo is not None:
                    for ini in range(lo, hi + 1, paso):
                        with self.lock:
                            self.con.execute('UPDATE celdas SET clase=(SELECT t.clase FROM tmp_clases t WHERE t.hoja=celdas.hoja) WHERE id>=? AND id<? AND clase IS NOT '
                                             '(SELECT t.clase FROM tmp_clases t WHERE t.hoja=celdas.hoja)', (ini, ini + paso))
                            self.con.commit()
                        if avance: avance('migrando base de datos', min(ini + paso, hi + 1) - lo, hi + 1 - lo)
                with self.lock: self.con.execute('DROP TABLE IF EXISTS tmp_clases'); self.con.commit()
                log.info('migracion: clase rellenada en %.1f s (%d hojas)', time.time() - t0, len(hojas))
            if avance: avance('creando indices', 0, 0)
            self._indices_aparte()
            if 'clase' in self.migrados:
                with self.lock: self.con.execute('DELETE FROM meta WHERE k=?', (self.MARCA_MIGRACION,)); self.con.commit()
                self.migrados = [c for c in self.migrados if c != 'clase']      # 'flujo' se resuelve en vincular_flujo()
        finally:
            self.liberar(MIGRANDO)

    # ---------------------------------------------------------- flujo materializado
    def vincular_flujo(self, fl):
        """fl = flujo.Flujo: sus marcas se reflejan en la columna `flujo` (al cambiar y ahora, solo si la BD no esta ya al dia)"""
        self._fl = fl; fl.alcambiar = self._flujo_cambia
        with fl.lock: h = self._huella(fl.datos)
        r = self.q("SELECT v FROM meta WHERE k='flujo_huella'")
        if 'flujo' in self.migrados or not r or r[0]['v'] != h: self.sincronizar_flujo()
        self.migrados = [c for c in self.migrados if c != 'flujo']

    @staticmethod
    def _huella(datos):
        return '%d:%s' % (len(datos), hashlib.sha1(json.dumps(sorted(datos.items())).encode('utf-8')).hexdigest()[:16])

    def _flujo_cambia(self, cambios):
        if self.ocupada.is_set(): self._flujo_pend = True; return     # se vuelca a la columna al terminar el indexado/migracion (el fichero de marcas ya esta guardado)
        if cambios is None: return self.sincronizar_flujo()
        with self._fl.lock: h = self._huella(self._fl.datos)
        with self.lock:
            self.con.executemany('UPDATE celdas SET flujo=? WHERE hoja=? AND row=? AND sub IS ? AND col=?', [(e, h_, r, s, c) for (h_, r, s, c), e in cambios])
            self.con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES ('flujo_huella',?)", (h,))
            self.con.commit()

    def sincronizar_flujo(self, con=None):
        """deja la columna `flujo` igual que las marcas del fichero (las marcas de celdas inexistentes se ignoran)"""
        if self._fl is None: return
        if con is None and self.ocupada.is_set(): self._flujo_pend = True; return
        from . import flujo as fmod
        with self._fl.lock: datos = dict(self._fl.datos)
        marcas = []
        for k, v in datos.items():
            try: h, r, s, c = fmod.partir_clave(k)
            except ValueError: continue
            marcas.append((v, h, r, s, c))
        with (self.lock if con is None else contextlib.nullcontext()):   # con = conexion del indexado: no se toma el cerrojo (evita esperar a una edicion bloqueada por la transaccion)
            cx = con or self.con
            cx.execute("UPDATE celdas SET flujo='sin' WHERE flujo!='sin'")
            cx.executemany('UPDATE celdas SET flujo=? WHERE hoja=? AND row=? AND sub IS ? AND col=?', marcas)
            cx.execute("INSERT OR REPLACE INTO meta(k,v) VALUES ('flujo_huella',?)", (self._huella(datos),))
            if con is None: self.con.commit()

    def q(self, sql, args=()):
        with self.lock: return self.con.execute(sql, args).fetchall()

    def x(self, sql, args=(), comprobar=True):
        if comprobar: self.exigir_libre()
        with self.lock:
            try: c = self.con.execute(sql, args); self.con.commit(); return c
            except sqlite3.OperationalError as e:
                if 'locked' in str(e) or 'busy' in str(e): raise Ocupada('La base de datos esta ocupada; repite la accion en unos segundos.')
                raise

    def cerrar(self):
        with self.lock: self.con.close()


# ------------------------------------------------------------------ lectura de hojas
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


_KEY_RE = re.compile(r'\{"row":(-?\d+),"sub":(null|-?\d+),"col":(-?\d+),("text":")?')


def _rutas_hoja(raiz, sub, hoja):
    base = os.path.join(raiz, 'textos', sub, *hoja.split('/'))
    paths = [base + '.jsonl'] if os.path.exists(base + '.jsonl') else []
    n = 1
    while os.path.exists('%s_part%02d.jsonl' % (base, n)): paths.append('%s_part%02d.jsonl' % (base, n)); n += 1
    return paths


def _lineas(paths):
    """{(row,sub,col): linea} SIN decodificar el JSON (la ultima gana); el texto se decodifica solo de las filas que hacen falta"""
    res = {}
    for p in paths:
        with open(p, encoding='utf-8') as f:
            for l in f:
                if not l.strip(): continue
                m = _KEY_RE.match(l)
                if m:
                    s = m.group(2); res[(int(m.group(1)), None if s == 'null' else int(s), int(m.group(3)))] = l
                else:
                    j = json.loads(l); res[(j['row'], j['sub'], j['col'])] = l
    return res


def _texto(l):
    """(text, raw) de una linea de textos/*. Camino rapido sin json.loads: linea {"row":..,"col":..,"text":"..."} sin escapes ni raw (un texto sin barras
    invertidas no puede llevar comillas internas: el contenido es exactamente lo que hay entre las comillas)"""
    m = _KEY_RE.match(l)
    if m and m.group(4) and '\\' not in l:
        e = l.rstrip()
        if e.endswith('"}') and '"raw"' not in e: return e[m.end():-2], None
    j = json.loads(l); return j['text'], j.get('raw')


def _leer_trad_lineas(ruta):
    """{(row,sub,col): (dict, es_json)}: es_json = trozo `es` de la linea (sin re-serializar) o None"""
    d = {}
    if os.path.exists(ruta):
        with open(ruta, encoding='utf-8') as f:
            for l in f:
                if not l.strip(): continue
                try: e = json.loads(l)
                except ValueError: continue
                if isinstance(e, dict) and isinstance(e.get('row'), int) and isinstance(e.get('col'), int):
                    a = l.find('"es":'); b = l.rfind(',"estado"')
                    ej = l[a + 5:b] if 0 <= a < b and 'es' in e else None
                    d[(e['row'], e.get('sub'), e['col'])] = (e, ej)
    return d


# ------------------------------------------------------------------ proceso de una hoja (se ejecuta en el proceso principal o en trabajadores)
_CTX = {}


def _init_trabajador(raiz_repo):
    from . import repo_env
    logging.getLogger('gridania').setLevel(logging.WARNING)
    _CTX['R'] = repo_env.cargar(raiz_repo)


def _procesar_hoja(a):
    """a = (hoja, raiz_nuevo, repo_dir, ed_dir, mismo) -> (hoja, filas, contadores, eliminadas). Cada fichero se lee una vez."""
    hoja, raiz_nuevo, repo_dir, ed_dir, mismo = a
    G = _CTX['R'].G
    rj = _rutas_hoja(raiz_nuevo, 'ja', hoja)
    ja = _lineas(rj) if rj else {}
    pv_l = ja if mismo else _lineas(_rutas_hoja(repo_dir, 'ja', hoja))
    fr_l = _lineas(_rutas_hoja(raiz_nuevo, 'fr', hoja))
    sufijo = os.path.join(*hoja.split('/')) + '.jsonl'
    tr = _leer_trad_lineas(os.path.join(repo_dir, 'traducciones', sufijo))
    ed = _leer_trad_lineas(os.path.join(ed_dir, 'traducciones', sufijo))
    tr.update(ed)
    clase = clases.clase_de(hoja)
    cnt = {e: 0 for e in ESTADOS}; filas = []
    tiene_cjk = G.tiene_cjk; hash_ja = G.hash_ja
    for k in sorted(ja, key=lambda k: (k[0], -1 if k[1] is None else k[1], k[2])):
        l = ja[k]; ent = tr.get(k)
        if ent is None:
            if '\\u' in l:
                if not tiene_cjk(json.loads(l)['text']): continue
            elif not tiene_cjk(l): continue
        text, raw = _texto(l)
        if ent is None and not tiene_cjk(text): continue
        t, ej = ent if ent else (None, None)
        h = hash_ja(text)
        if mismo: igual = True
        else:
            pl = pv_l.get(k); igual = pl is not None and _texto(pl)[0] == text
        estado, vig = clasificar(t, h, igual)
        cnt[estado] += 1
        es = t.get('es') if t else None
        fl = fr_l.get(k)
        filas.append((hoja, k[0], k[1], k[2], estado, h, text, _texto(fl)[0] if fl else '', plano(es) if t else '',
                      (ej if ej is not None else json.dumps(es, ensure_ascii=False)) if t else None,
                      t.get('origen') if t else None, t.get('h') if t else None, 1 if k in ed else 0, clase, 'sin'))
    return hoja, filas, cnt, sum(1 for k in tr if k not in ja)


def _lote_hojas(args):
    return [_procesar_hoja(a) for a in args]


# ------------------------------------------------------------------ firmas (indice persistente)
def _arbol(base, quitar_part):
    """{hoja: [(nombre, size, mtime_ns)]} de los .jsonl de una carpeta, con un solo recorrido"""
    out = {}
    if not os.path.isdir(base): return out
    for d, _, fs in os.walk(base):
        for f in fs:
            if not f.endswith('.jsonl'): continue
            p = os.path.join(d, f)
            try: st = os.stat(p)
            except OSError: continue
            n = os.path.relpath(p, base)[:-6].replace(os.sep, '/')
            out.setdefault(PART_RE.sub('', n) if quitar_part else n, []).append((n, st.st_size, st.st_mtime_ns))
    return out


def firmas(repo_dir, raiz_nuevo, ed_dir):
    """-> (hojas ordenadas, {hoja: firma}). La firma cambia si cambia size/mtime de cualquiera de los ficheros de la hoja
    (ja, fr, ja previo, traducciones del repo y del usuario). Termina en '!' si algun fichero es demasiado reciente (mtime ~ ahora:
    no se puede garantizar que un cambio posterior en el mismo instante cambie la firma), y entonces nunca se da por vigente."""
    mismo = os.path.abspath(raiz_nuevo) == os.path.abspath(repo_dir)
    ahora = time.time_ns()
    a_ja = _arbol(os.path.join(raiz_nuevo, 'textos', 'ja'), True)
    a_fr = _arbol(os.path.join(raiz_nuevo, 'textos', 'fr'), True)
    a_pv = {} if mismo else _arbol(os.path.join(repo_dir, 'textos', 'ja'), True)
    a_tr = _arbol(os.path.join(repo_dir, 'traducciones'), False)
    a_ed = _arbol(os.path.join(ed_dir, 'traducciones'), False)
    hojas = sorted(set(a_ja) | set(a_tr) | set(a_ed))
    out = {}
    for h in hojas:
        partes = [VERSION_INDEXADOR, mismo, [sorted(a.get(h, ())) for a in (a_ja, a_fr, a_pv, a_tr, a_ed)]]
        racy = any(x[2] > ahora - 2 * 10 ** 9 for a in (a_ja, a_fr, a_pv, a_tr, a_ed) for x in a.get(h, ()))
        out[h] = hashlib.sha1(repr(partes).encode('utf-8')).hexdigest()[:20] + ('!' if racy else '')
    return hojas, out


def _firma_hoja(repo_dir, raiz_nuevo, ed_dir, hoja):
    """firma de UNA hoja (para refirmar tras guardar una edicion)"""
    mismo = os.path.abspath(raiz_nuevo) == os.path.abspath(repo_dir)
    def estat(raiz, sub, quitar):
        base = os.path.join(raiz, *sub); out = []
        h = os.path.join(base, *hoja.split('/'))
        cands = [h + '.jsonl'] + (['%s_part%02d.jsonl' % (h, n) for n in range(1, 100)] if quitar else [])
        for p in cands:
            try: st = os.stat(p)
            except OSError:
                if p != cands[0]: break
                continue
            out.append((os.path.relpath(p, base)[:-6].replace(os.sep, '/'), st.st_size, st.st_mtime_ns))
        return sorted(out)
    partes = [VERSION_INDEXADOR, mismo, [estat(raiz_nuevo, ('textos', 'ja'), True), estat(raiz_nuevo, ('textos', 'fr'), True),
              [] if mismo else estat(repo_dir, ('textos', 'ja'), True), estat(repo_dir, ('traducciones',), False), estat(ed_dir, ('traducciones',), False)]]
    return hashlib.sha1(repr(partes).encode('utf-8')).hexdigest()[:20]


def firma_actual(base, hoja):
    """firma de la hoja segun los ficheros AHORA (llamar ANTES de escribir una edicion); None si no hay contexto de indexado"""
    try:
        c = meta(base, 'contexto')
        return _firma_hoja(c['repo_dir'], c['raiz_nuevo'], c['ed_dir'], hoja) if c else None
    except Exception:
        return None


def refirmar(base, hoja, previa):
    """tras guardar una edicion la BD ya coincide con el fichero de ediciones: actualiza la firma de la hoja (sin reindexar) SOLO si la firma guardada era la vigente
    ANTES de la edicion (`previa`, de firma_actual). Si la hoja ya estaba desactualizada (sus ficheros fuente cambiaron) se deja tal cual para que se reindexe.
    Conserva el sufijo '!' (firma «racy»). Silencioso si no hay contexto."""
    try:
        c = meta(base, 'contexto')
        if not c or previa is None: return
        r = base.q('SELECT firma FROM hojas_idx WHERE hoja=?', (hoja,))
        if not r: return
        guardada = r[0]['firma']; racy = guardada.endswith('!')
        if guardada.rstrip('!') != previa: return
        base.x('UPDATE hojas_idx SET firma=? WHERE hoja=?', (_firma_hoja(c['repo_dir'], c['raiz_nuevo'], c['ed_dir'], hoja) + ('!' if racy else ''), hoja), comprobar=False)
    except Exception as x:
        log.warning('refirmar %s: %s', hoja, x)


def estado_indice(R, base, repo_dir, raiz_nuevo, ed_dir):
    """-> {'vigente': bool, 'hojas_cambiadas': n, 'motivo': str} comparando firmas (solo stat, rapido). No modifica nada."""
    try:
        m = meta(base)
        if not m or not base.q('SELECT 1 FROM celdas LIMIT 1'): return {'vigente': False, 'hojas_cambiadas': 0, 'motivo': 'sin_indice'}
        hojas, nuevas = firmas(repo_dir, raiz_nuevo, ed_dir)
        guardadas = {r['hoja']: r['firma'] for r in base.q('SELECT hoja, firma FROM hojas_idx')}
        if not guardadas: return {'vigente': False, 'hojas_cambiadas': len(hojas), 'motivo': 'sin_firmas'}
        cambiadas = [h for h in hojas if guardadas.get(h) != nuevas[h] or nuevas[h].endswith('!')]
        sobran = [h for h in guardadas if h not in nuevas]
        n = len(cambiadas) + len(sobran)
        return {'vigente': n == 0, 'hojas_cambiadas': n, 'motivo': 'cambios' if n else 'ok'}
    except Exception as x:
        log.warning('estado_indice: %s', x)
        return {'vigente': False, 'hojas_cambiadas': 0, 'motivo': 'error'}


# ------------------------------------------------------------------ indexado
def _procesos_por_defecto(n_hojas):
    try: n = int(os.environ.get('GRIDANIA_EDITOR_PROCESOS') or 0)
    except ValueError: n = 0
    if n > 0: return n
    return max(1, min(os.cpu_count() or 1, 8))


def _esperar(fut, cancelar, limite=900):
    """fut.result() en tramos cortos: permite cancelar (Cancelado) sin esperar al lote en curso"""
    t0 = time.time()
    while True:
        try: return fut.result(timeout=0.25)
        except concurrent.futures.TimeoutError:
            if cancelar is not None and cancelar.is_set(): raise Cancelado('indexado cancelado')
            if time.time() - t0 > limite: raise


PIDS_TRABAJADORES = set()   # pids de los procesos trabajadores de la ultima ejecucion paralela (diagnostico y pruebas)


def _generar(R, args, procesos, umbral, progreso, cancelar=None):
    """generador de resultados de _procesar_hoja EN ORDEN. Procesos paralelos si hay trabajo suficiente (spawn: seguro con hilos y en Windows)."""
    hechos = 0; PIDS_TRABAJADORES.clear()
    if procesos > 1 and len(args) >= umbral:
        ex = None
        try:
            # ProcessPoolExecutor (no multiprocessing.Pool): si un trabajador muere al arrancar el ejecutor queda ROTO y falla, en vez de relanzar procesos sin fin
            ex = concurrent.futures.ProcessPoolExecutor(procesos, mp_context=multiprocessing.get_context('spawn'), initializer=_init_trabajador, initargs=(R.raiz,))
            tam = max(1, min(40, len(args) // (procesos * 8) or 1))
            lotes = iter([args[i:i + tam] for i in range(0, len(args), tam)])
            progreso('indexando en %d procesos' % procesos)
            pend = collections.deque()
            def mas():
                l = next(lotes, None)
                if l is not None: pend.append(ex.submit(_lote_hojas, l))
            for _ in range(procesos * 3): mas()     # ventana deslizante: los resultados no se acumulan en memoria
            while pend:
                lote = _esperar(pend.popleft(), cancelar)
                PIDS_TRABAJADORES.update(getattr(ex, '_processes', None) or {})
                mas()
                for r in lote: hechos += 1; yield r
            return
        except (OSError, ImportError, RuntimeError, EOFError) as x:   # incluye BrokenProcessPool y TimeoutError
            log.warning('indexado paralelo fallo (%s: %s); se sigue con un solo proceso', type(x).__name__, x)
            progreso('paralelo no disponible (%s); un solo proceso' % type(x).__name__)
        finally:
            if ex is not None:
                for pr in list((getattr(ex, '_processes', None) or {}).values()):
                    try: pr.terminate()
                    except Exception: pass
                ex.shutdown(wait=False, cancel_futures=True)
    _CTX['R'] = R
    for a in args[hechos:]: yield _procesar_hoja(a)


def indexar(R, base, repo_dir, raiz_ja_nuevo, ediciones_dir, progreso=print, forzar=False, cancelar=None, avance=None, procesos=None, umbral_paralelo=300):
    """Actualiza la tabla `celdas`. raiz_ja_nuevo = carpeta con textos/ja (juego extraido, o repo_dir si no hay extraccion).
    Incremental: solo se reindexan las hojas cuya firma cambio (forzar=True: todo). Una sola transaccion; cancelar (Event) revierte y deja el indice anterior.
    avance(fase, hecho, total) = progreso real para la UI."""
    t0 = time.time(); tiempos = {}
    previo = repo_dir
    mismo = os.path.abspath(raiz_ja_nuevo) == os.path.abspath(previo)
    avance = avance or (lambda *a: None)
    def chequear():
        if cancelar is not None and cancelar.is_set(): raise Cancelado('indexado cancelado')
    avance('buscando ficheros', 0, 0)
    hojas, nuevas = firmas(repo_dir, raiz_ja_nuevo, ediciones_dir)
    tiempos['firmas'] = round(time.time() - t0, 2)
    guardadas = {r['hoja']: r['firma'] for r in base.q('SELECT hoja, firma FROM hojas_idx')}
    con_datos = bool(base.q('SELECT 1 FROM celdas LIMIT 1')) and meta(base) is not None
    if forzar or not con_datos: cambiadas = list(hojas); sobran = [r['hoja'] for r in base.q('SELECT DISTINCT hoja FROM celdas')]
    else:
        cambiadas = [h for h in hojas if guardadas.get(h) != nuevas[h] or nuevas[h].endswith('!')]
        sobran = [h for h in guardadas if h not in nuevas]
    if con_datos and not forzar and not cambiadas and not sobran:
        m = meta(base)
        progreso('indice vigente: no hay cambios en el repo, el juego ni las ediciones (%d hojas)' % len(hojas))
        log.info('indexar: indice vigente, %d hojas, firmas %.2fs', len(hojas), tiempos['firmas'])
        return dict(m, sin_cambios=True)
    completo = len(cambiadas) > len(hojas) * 0.5 or not con_datos
    progreso('%s: %d hojas a indexar de %d' % ('indexado completo' if completo else 'indexado incremental', len(cambiadas), len(hojas)))
    base.esperar_migracion(progreso, cancelar)
    base.ocupar(INDEXANDO)       # ediciones rechazadas con mensaje (Ocupada); NO se retiene Base.lock: la UI y /api/estado siguen respondiendo
    w = None
    n = 0
    try:
        w = base.conectar()
        w.execute('BEGIN IMMEDIATE')
        if completo:
            w.execute('DELETE FROM celdas'); w.execute('DELETE FROM hojas_idx')
            for nombre, _ in INDICES: w.execute('DROP INDEX IF EXISTS %s' % nombre)
            ids_viejos = {}
            siguiente = 1
        else:
            ids_viejos = {}
            for h in cambiadas:
                ids_viejos[h] = [r[0] for r in w.execute('SELECT id FROM celdas WHERE hoja=? ORDER BY id', (h,))]
            siguiente = (w.execute('SELECT COALESCE(MAX(id),0) FROM celdas').fetchone()[0]) + 1
            for h in sobran + cambiadas:
                w.execute('DELETE FROM celdas WHERE hoja=?', (h,)); w.execute('DELETE FROM hojas_idx WHERE hoja=?', (h,))
        tiempos['preparar'] = round(time.time() - t0, 2)
        args = [(h, raiz_ja_nuevo, repo_dir, ediciones_dir, mismo) for h in cambiadas]
        proc = procesos if procesos is not None else _procesos_por_defecto(len(args))
        t1 = time.time(); ins = 'INSERT INTO celdas(id,%s) VALUES (?%s)' % (COLS, ',?' * 15)
        for i, (hoja, filas, cnt, elim) in enumerate(_generar(R, args, proc, umbral_paralelo, progreso, cancelar)):
            chequear()
            viejos = ids_viejos.get(hoja, ())
            rows = []
            for j, f in enumerate(filas):
                if j < len(viejos): rid = viejos[j]
                else: rid = siguiente; siguiente += 1
                rows.append((rid,) + f)
            if rows: w.executemany(ins, rows)
            w.execute('INSERT OR REPLACE INTO hojas_idx(hoja, firma, elim) VALUES (?,?,?)', (hoja, nuevas[hoja], elim))
            n += len(filas)
            if i % 100 == 0:
                progreso('indexando %d/%d (%s) celdas=%d' % (i, len(cambiadas), hoja, n)); avance('indexando hojas', i, len(cambiadas))
        tiempos['hojas'] = round(time.time() - t1, 2)
        chequear()
        t2 = time.time()
        if completo: avance('creando indices', 0, 0); Base._crear_indices(w)
        tiempos['indices'] = round(time.time() - t2, 2)
        t3 = time.time()
        base.sincronizar_flujo(w) if base._fl is not None else None
        tiempos['flujo'] = round(time.time() - t3, 2)
        cnt = {e: 0 for e in ESTADOS}
        for e, c in w.execute('SELECT estado, COUNT(*) FROM celdas GROUP BY estado'): cnt[e] = c
        total = sum(cnt.values()); elim = w.execute('SELECT COALESCE(SUM(elim),0) FROM hojas_idx').fetchone()[0]
        tiempos['total'] = round(time.time() - t0, 2)
        meta_ = {'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'celdas': total, 'eliminadas_del_juego': elim, 'contadores': cnt,
                 'fuente': 'juego' if not mismo else 'repo', 'hojas_reindexadas': len(cambiadas), 'incremental': not completo, 'segundos': tiempos['total'], 'tiempos': tiempos}
        w.execute('INSERT OR REPLACE INTO meta(k,v) VALUES (?,?)', ('indexado', json.dumps(meta_)))
        w.execute('INSERT OR REPLACE INTO meta(k,v) VALUES (?,?)', ('contexto', json.dumps({'repo_dir': repo_dir, 'raiz_nuevo': raiz_ja_nuevo, 'ed_dir': ediciones_dir})))
        w.execute('INSERT OR REPLACE INTO meta(k,v) VALUES (?,?)', ('esquema', str(ESQUEMA_VERSION)))
        avance('confirmando', 0, 0)
        w.commit()
    except BaseException:
        try: w and w.rollback()
        except sqlite3.Error: pass
        raise
    finally:
        try: w and w.close()
        finally: base.liberar(INDEXANDO)
    log.info('indexar: %s', json.dumps(tiempos))
    progreso('indice listo: %s (%.1f s)' % (json.dumps(cnt), tiempos['total']))
    return meta_


def meta(base, k='indexado'):
    r = base.q('SELECT v FROM meta WHERE k=?', (k,))
    return json.loads(r[0]['v']) if r else None


# ------------------------------------------------------------------ consultas
def _donde(hoja=None, estados=None, q=None, solo_editadas=False, clase=None, flujo=None):
    w = []; a = []
    if hoja: w.append('hoja=?'); a.append(hoja)
    if clase: w.append('clase=?'); a.append(clase)
    if flujo: w.append('flujo=?'); a.append(flujo)
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
    for r in base.q('SELECT flujo f, COUNT(*) n FROM celdas' + cond + ' GROUP BY f', a): d[r['f']] = r['n']
    return d


def contadores_clase(base, hoja=None, estados=None, q=None, solo_editadas=False, flujo=None):
    cond, a = _donde(hoja, estados, q, solo_editadas, None, flujo)
    d = {c: 0 for c in clases.CLASES}
    for r in base.q('SELECT clase c, COUNT(*) n FROM celdas' + cond + ' GROUP BY c', a): d[r['c']] = r['n']
    return d


def hojas_resumen(base, q=None):
    sql = 'SELECT hoja, estado, COUNT(*) n FROM celdas' + (" WHERE hoja LIKE ? ESCAPE '\\'" if q else '') + ' GROUP BY hoja, estado'
    res = {}
    for r in base.q(sql, (('%' + _esc(q) + '%',) if q else ())):
        res.setdefault(r['hoja'], {e: 0 for e in ESTADOS})[r['estado']] = r['n']
    return [dict(hoja=h, **c, total=sum(c.values())) for h, c in sorted(res.items())]


def hojas_resumen_flujo(base):
    """UNA consulta agregada: por hoja, celdas por color y por estado de flujo (solo celdas que existen en el indice)"""
    res = {}
    for r in base.q('SELECT hoja, estado, flujo, COUNT(*) n FROM celdas GROUP BY hoja, estado, flujo'):
        x = res.setdefault(r['hoja'], dict({e: 0 for e in ESTADOS}, por_hacer=0, hecho=0))
        x[r['estado']] += r['n']
        if r['flujo'] in ('por_hacer', 'hecho'): x[r['flujo']] += r['n']
    return [dict(hoja=h, **c, total=sum(c[e] for e in ESTADOS)) for h, c in sorted(res.items())]


def _esc(s):
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def listar(base, hoja=None, estados=None, q=None, offset=0, limite=100, solo_editadas=False, clase=None, flujo=None):
    cond, a = _donde(hoja, estados, q, solo_editadas, clase, flujo)
    total = base.q('SELECT COUNT(*) n FROM celdas' + cond, a)[0]['n']
    filas = base.q('SELECT id,hoja,row,sub,col,estado,substr(ja,1,120) ja,substr(es,1,120) es,origen,editada,clase,flujo FROM celdas' + cond + ' ORDER BY id LIMIT ? OFFSET ?', a + [limite, offset])
    return total, [dict(r) for r in filas]


def celdas_filtradas(base, hoja=None, estados=None, q=None, solo_editadas=False, clase=None, flujo=None):
    """todas las celdas (hoja,row,sub,col) que cumplen el filtro (para marcar en bloque)"""
    cond, a = _donde(hoja, estados, q, solo_editadas, clase, flujo)
    return [(r['hoja'], r['row'], r['sub'], r['col']) for r in base.q('SELECT hoja,row,sub,col FROM celdas' + cond + ' ORDER BY id', a)]


def obtener(base, id_):
    r = base.q('SELECT * FROM celdas WHERE id=?', (id_,))
    return dict(r[0]) if r else None
