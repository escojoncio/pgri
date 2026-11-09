"""Estado de la aplicacion (sin HTTP): ajustes, base de datos, motor de celdas y tareas en segundo plano."""
import collections, json, os, re, threading, time, traceback
from . import builder, busqueda, celda, config, edits, extractor, github_sync, indexer, repo_env


class Tarea(object):
    def __init__(self, cfg):
        self.cfg = cfg; self.nombre = ''; self.estado = 'libre'; self.log = []; self.resultado = None; self.error = None; self.lock = threading.Lock(); self.t0 = 0

    def escribir(self, linea):
        linea = self.cfg.redactar(str(linea))
        with self.lock:
            self.log.append('%s %s' % (time.strftime('%H:%M:%S'), linea))
            if len(self.log) > 3000: del self.log[:500]

    def iniciar(self, nombre, fn):
        with self.lock:
            if self.estado == 'ejecutando': raise RuntimeError('ya hay una tarea en curso: %s' % self.nombre)
            self.nombre = nombre; self.estado = 'ejecutando'; self.resultado = None; self.error = None; self.log = []; self.t0 = time.time()
        def correr():
            try:
                r = fn(self.escribir)
                with self.lock: self.resultado = r; self.estado = 'ok'
            except Exception as x:
                self.escribir('ERROR: %s: %s' % (type(x).__name__, x))
                if os.environ.get('GRIDANIA_EDITOR_DEBUG'): self.escribir(traceback.format_exc())
                with self.lock: self.error = self.cfg.redactar('%s: %s' % (type(x).__name__, x)); self.estado = 'error'
        threading.Thread(target=correr, daemon=True).start()

    def ver(self, desde=0):
        with self.lock:
            return {'nombre': self.nombre, 'estado': self.estado, 'resultado': self.resultado, 'error': self.error, 'log': self.log[desde:], 'siguiente': len(self.log),
                    'segundos': int(time.time() - self.t0) if self.t0 else 0}


class Aplicacion(object):
    def __init__(self, home=None, repo_override=None):
        self.cfg = config.Config(home, repo_override)
        self.base = indexer.Base(self.cfg.db_ruta)
        self.tarea = Tarea(self.cfg)
        self._R = None; self._motor = None; self._indice = None
        self.lock = threading.RLock()

    # ------------------------------------------------------------ infraestructura
    def R(self, forzar=False):
        with self.lock:
            if self._R is None or forzar: self._R = repo_env.cargar(self.cfg.repo_dir, forzar=forzar); self._motor = None
            return self._R

    def raiz_textos(self):
        j = self.cfg.juego_dir
        return j if os.path.exists(os.path.join(j, 'info.json')) and os.path.isdir(os.path.join(j, 'textos', 'ja')) else self.cfg.repo_dir

    def motor(self):
        with self.lock:
            if self._motor is None: self._motor = celda.Motor(self.R(), self.raiz_textos(), self.cfg.repo_dir, self.base)
            return self._motor

    def olvidar_motor(self):
        with self.lock: self._motor = None

    def _leer(self, nombre):
        try: return json.load(open(os.path.join(self.cfg.home, nombre), encoding='utf-8'))
        except (OSError, ValueError): return None

    # ------------------------------------------------------------ consultas
    def estado(self):
        j = None
        try: j = json.load(open(os.path.join(self.cfg.juego_dir, 'info.json'), encoding='utf-8'))
        except (OSError, ValueError): pass
        if j: j = {k: v for k, v in j.items() if k != 'no_leidas'}
        return {'config': self.cfg.publico(), 'sync': self._leer('sync_info.json'), 'juego': j, 'indice': indexer.meta(self.base), 'contadores': indexer.contadores(self.base),
                'ediciones': edits.contar(self.cfg.ediciones_dir), 'repo_ok': repo_env.hay_repo(self.cfg.repo_dir), 'tarea': self.tarea.ver(10 ** 9),
                'version_recomendada': self._recomendada()}

    def _recomendada(self):
        try: return open(os.path.join(self.cfg.repo_dir, 'data', 'recommended-game-version.txt'), encoding='utf-8').read().strip()
        except OSError: return ''

    def celda(self, id_):
        reg = indexer.obtener(self.base, id_)
        if not reg: raise KeyError('celda desconocida')
        m = self.motor(); R = m.R
        c = m.contexto(reg['hoja'], reg['row'], reg['sub'], reg['col'])
        es = json.loads(reg['es_json']) if reg['es_json'] else None
        d = {'id': id_, 'hoja': c.hoja, 'row': c.row, 'sub': c.sub, 'col': c.col, 'estado': reg['estado'], 'origen': reg['origen'], 'editada': bool(reg['editada']),
             'h': c.h, 'h_es': reg['h_es'], 'tipo': c.tipo, 'ja': self._legible(c.tok), 'fr': self._legible(c.fr_tok) if c.fr_tok else '', 'ntrozos': len(c.ch) if c.ch else 1,
             'perfil': {'tipo': c.pf.tipo, 'seguro': c.pf.seguro, 'duro': c.pf.duro, 'lineas': c.pf.lineas}, 'reflujo': bool(c.reflujo_W)}
        d['vista_ja'] = self._vista_fuente(m, c, c.tok); d['vista_fr'] = self._vista_fuente(m, c, c.fr_tok) if c.fr_tok else None
        d['hablante'] = self._hablante(c, reg, es, m)
        d['contexto'] = self._contexto(reg)
        d['ja_previo'] = ''
        if reg['estado'] in ('naranja', 'rojo') and os.path.abspath(self.raiz_textos()) != os.path.abspath(self.cfg.repo_dir):
            try:
                pv = R.G.leer_ja(self.cfg.repo_dir, c.hoja) or {}
                if c.k in pv: d['ja_previo'] = self._legible(R.S.tokenize_raw(R.G.bytes_ja(*pv[c.k])))
            except Exception: pass
        if es is not None:
            d['es_texto'] = m.es_a_texto(c, es); d['sin_traduccion'] = False
        else:
            d['es_texto'] = self.plantilla(c); d['sin_traduccion'] = True
        d['evaluacion'] = self._resumen(m.evaluar(c, d['es_texto'], 'masc', False)) if es is not None else None
        return d

    @staticmethod
    def _vista_fuente(m, c, tok):
        """JP/FR con las mismas macros resueltas que la vista del ES (colores, saltos), sin envolver: se ve la estructura original"""
        try: return m.vista(c, tok, 'masc', False)
        except Exception: return None

    HABLANTE_RE = re.compile(r'^\(-(.+?)-\)')

    def _hablante(self, c, reg, es, m):
        """nombre del hablante: prefijo (-Nombre-) del ja / fr / es y, si no, el rotulo de la clave de la fila (col 0)"""
        out = {}
        for k, t in (('ja', c.tok), ('fr', c.fr_tok or ''), ('es', reg['es'] or '')):
            x = self.HABLANTE_RE.match(t or '')
            if x: out[k] = x.group(1)
        if c.clave and c.col != 0: out['clave'] = c.clave[:80]
        return out or None

    def _contexto(self, reg):
        """filas anterior y siguiente de la misma hoja"""
        out = {}
        for nombre, cmp_, orden in (('anterior', '<', 'DESC'), ('siguiente', '>', 'ASC')):
            r = self.base.q('SELECT id,row,sub,col,estado,ja,fr,es FROM celdas WHERE hoja=? AND id%s? ORDER BY id %s LIMIT 1' % (cmp_, orden), (reg['hoja'], reg['id']))
            out[nombre] = {k: (self._legible(r[0][k]) if k in ('ja', 'fr', 'es') and r[0][k] else r[0][k]) for k in r[0].keys()} if r else None
        return out

    @staticmethod
    def _legible(tok):
        return celda.NL_RE.sub('\n', tok) if tok else ''

    def plantilla(self, c):
        """texto inicial de una celda sin traduccion: simple = estructura vacia (saltos y separadores del original); compleja = el original tokenizado"""
        if c.tipo == 'simple':
            return celda.NL_RE.sub('\n', self.R().G.recomponer(c.seps, [''] * (len(c.seps) + 1)))
        return c.tok

    @staticmethod
    def _resumen(r):
        return {'ok': r['ok'], 'errores': [list(x) for x in r['errores']], 'avisos': [list(x) for x in r['avisos']], 'vista': r['vista'], 'texto': r['texto']}

    def preview(self, id_, texto, genero='masc', reflujo=True):
        reg = indexer.obtener(self.base, id_)
        m = self.motor(); c = m.contexto(reg['hoja'], reg['row'], reg['sub'], reg['col'])
        r = self._resumen(m.evaluar(c, texto, genero, reflujo))
        r['vista_ja'] = self._vista_fuente_g(m, c, c.tok, genero); r['vista_fr'] = self._vista_fuente_g(m, c, c.fr_tok, genero) if c.fr_tok else None
        return r

    @staticmethod
    def _vista_fuente_g(m, c, tok, genero):
        try: return m.vista(c, tok, genero, False)
        except Exception: return None

    def guardar(self, id_, texto):
        reg = indexer.obtener(self.base, id_)
        if not reg: raise KeyError('celda desconocida')
        m = self.motor(); c = m.contexto(reg['hoja'], reg['row'], reg['sub'], reg['col'])
        r = m.evaluar(c, texto, 'masc', True)
        if r['errores'] or r['es'] is None:
            return {'guardado': False, 'evaluacion': self._resumen(r)}
        edits.guardar(self.base, self.cfg.ediciones_dir, m.R, c, r['es'])
        if self._indice is not None: self._indice.actualizar(id_, edits_plano(r['es']), 'verde')
        return {'guardado': True, 'evaluacion': self._resumen(r)}

    # ------------------------------------------------------------ busqueda global
    def indice(self):
        with self.lock:
            if self._indice is None: self._indice = busqueda.Indice.desde_base(self.base)
            return self._indice

    @staticmethod
    def consulta(b):
        return busqueda.Consulta(b.get('texto', ''), b.get('campos') or ('ja', 'fr', 'es'), b.get('modo', 'subcadena'), b.get('mayus', False), b.get('tildes', False), b.get('estados'), b.get('hoja'))

    def buscar(self, b):
        return self.indice().buscar(self.consulta(b), int(b.get('offset') or 0), min(500, int(b.get('limite') or 100)))

    def exportar_busqueda(self, b):
        destino = b.get('destino') or self.cfg['carpeta_dat'] or self.cfg.sub('exportado')
        os.makedirs(destino, exist_ok=True)
        ruta = os.path.join(destino, 'busqueda_%s.tsv' % time.strftime('%Y%m%d-%H%M%S'))
        n = self.indice().exportar(self.consulta(b), ruta)
        return {'ruta': ruta, 'celdas': n}

    def reemplazar(self, b):
        """Reemplazo SOLO en el ES de las celdas encontradas (ids = seleccion; sin ids = todas). aplicar=False: vista previa. Cada cambio pasa por la misma evaluacion y puertas que al guardar."""
        q = self.consulta(dict(b, campos=['es'])); nuevo = b.get('reemplazo', '')
        ids = b.get('ids')
        sel = set(int(i) for i in ids) if ids else None
        m = self.motor(); cambios = []; rechazadas = []; sin_cambio = 0
        for f, _ in list(self.indice().coincidencias(q)):
            if sel is not None and f['id'] not in sel: continue
            reg = indexer.obtener(self.base, f['id'])
            if not reg or not reg['es_json']: continue
            c = m.contexto(reg['hoja'], reg['row'], reg['sub'], reg['col'])
            antes = m.es_a_texto(c, json.loads(reg['es_json']))
            despues, n = q.reemplazar(antes, nuevo)
            if not n or despues == antes: sin_cambio += 1; continue
            r = m.evaluar(c, despues, 'masc', True)
            item = {'id': f['id'], 'hoja': c.hoja, 'row': c.row, 'col': c.col, 'antes': antes, 'despues': r['texto'] if r['es'] is not None else despues, 'n': n,
                    'errores': [list(x) for x in r['errores']], 'avisos': [list(x) for x in r['avisos']]}
            if r['errores'] or r['es'] is None: rechazadas.append(item); continue
            if b.get('aplicar'):
                edits.guardar(self.base, self.cfg.ediciones_dir, m.R, c, r['es'])
                self.indice().actualizar(f['id'], edits_plano(r['es']), 'verde')
            cambios.append(item)
        return {'aplicado': bool(b.get('aplicar')), 'cambios': cambios[:300], 'n_cambios': len(cambios), 'rechazadas': rechazadas[:300], 'n_rechazadas': len(rechazadas), 'sin_cambio': sin_cambio}

    # ------------------------------------------------------------ tareas
    def _indexar(self, log):
        R = self.R(); self.olvidar_motor(); self._indice = None
        meta = indexer.indexar(R, self.base, self.cfg.repo_dir, self.raiz_textos(), self.cfg.ediciones_dir, log)
        log('cargando el indice de busqueda en memoria...'); self.indice()
        return meta

    def tarea_sync(self):
        cfg = self.cfg
        if not cfg['repo'] or '/' not in cfg['repo']: raise ValueError('indica el repositorio como propietario/nombre')
        def fn(log):
            t = github_sync.Transporte(cfg['token'])
            info = github_sync.sincronizar(t, cfg['repo'], cfg['rama'], cfg.home, cfg.repo_dir, log)
            self.R(forzar=True)
            log('reindexando...'); info['indice'] = self._indexar(log)
            return info
        self.tarea.iniciar('sync', fn)

    def tarea_extraer(self, ruta=None):
        cfg = self.cfg
        if ruta: cfg.actualizar({'ruta_juego': ruta})
        game = cfg['ruta_juego']
        extractor.comprobar_ruta(game)
        def fn(log):
            R = self.R()
            info = extractor.extraer(R, game, cfg.juego_dir, ('ja', 'fr'), log)
            log('reindexando contra el juego extraido...'); info['indice'] = self._indexar(log)
            return info
        self.tarea.iniciar('extraer', fn)

    def tarea_indexar(self):
        self.tarea.iniciar('indexar', lambda log: self._indexar(log))

    def tarea_generar(self, destino=None, relajar='auto', validar=True):
        cfg = self.cfg
        if destino: cfg.actualizar({'carpeta_dat': destino})
        destino = cfg['carpeta_dat']
        if not destino: raise ValueError('elige la carpeta de destino del .dat en Ajustes')
        extractor.comprobar_ruta(cfg['ruta_juego'])
        def fn(log):
            return builder.generar(self.R(), cfg, destino, self.raiz_textos(), log, relajar, validar)
        self.tarea.iniciar('generar', fn)

    def exportar(self, destino=None):
        destino = destino or self.cfg['carpeta_dat'] or self.cfg.sub('exportado')
        return edits.exportar(self.cfg.ediciones_dir, destino)


def edits_plano(es):
    return indexer.plano(es)
