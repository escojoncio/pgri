"""Estado de la aplicacion (sin HTTP): ajustes, base de datos, motor de celdas y tareas en segundo plano."""
import collections, json, logging, os, re, sqlite3, threading, time, traceback
from . import celda as celda_mod
from . import builder, busqueda, celda, clases, config, edits, extractor, flujo, github_sync, indexer, parche, registro, repo_env

log = logging.getLogger('gridania.app')


class Tarea(object):
    def __init__(self, cfg):
        self.cfg = cfg; self.nombre = ''; self.estado = 'libre'; self.log = []; self.resultado = None; self.error = None; self.lock = threading.Lock(); self.t0 = 0
        self.cancelar_ev = threading.Event(); self.prog = {'fase': '', 'hecho': 0, 'total': 0}; self.cancelable = False

    def escribir(self, linea):
        linea = self.cfg.redactar(str(linea))
        with self.lock:
            self.log.append('%s %s' % (time.strftime('%H:%M:%S'), linea))
            if len(self.log) > 3000: del self.log[:500]

    def avance(self, fase, hecho=0, total=0):
        with self.lock: self.prog = {'fase': fase, 'hecho': hecho, 'total': total}

    def cancelar(self):
        with self.lock:
            if self.estado != 'ejecutando' or not self.cancelable: return False
        self.cancelar_ev.set(); self.escribir('cancelando...'); return True

    def iniciar(self, nombre, fn, cancelable=False):
        with self.lock:
            if self.estado == 'ejecutando': raise RuntimeError('ya hay una tarea en curso: %s' % self.nombre)
            self.nombre = nombre; self.estado = 'ejecutando'; self.resultado = None; self.error = None; self.log = []; self.t0 = time.time()
            self.cancelar_ev.clear(); self.cancelable = cancelable; self.prog = {'fase': '', 'hecho': 0, 'total': 0}
        log.info('tarea %s: inicio', nombre)
        def correr():
            try:
                r = fn(self.escribir)
                with self.lock: self.resultado = r; self.estado = 'ok'
                log.info('tarea %s: ok en %.1f s', nombre, time.time() - self.t0)
            except indexer.Cancelado:
                self.escribir('Cancelado: se conserva el indice anterior.')
                with self.lock: self.error = 'cancelada'; self.estado = 'cancelada'
                log.info('tarea %s: cancelada', nombre)
            except BaseException as x:   # BaseException: un hilo que muere sin marcar el estado dejaria la UI esperando para siempre
                self.escribir('ERROR: %s: %s' % (type(x).__name__, x))
                log.error('tarea %s: error', nombre, exc_info=True)
                if os.environ.get('GRIDANIA_EDITOR_DEBUG'): self.escribir(traceback.format_exc())
                with self.lock: self.error = self.cfg.redactar('%s: %s' % (type(x).__name__, x)); self.estado = 'error'
        threading.Thread(target=correr, daemon=True, name='tarea-' + nombre).start()

    def ver(self, desde=0):
        with self.lock:
            return {'nombre': self.nombre, 'estado': self.estado, 'resultado': self.resultado, 'error': self.error, 'log': self.log[desde:], 'siguiente': len(self.log),
                    'segundos': int(time.time() - self.t0) if self.t0 else 0, 'progreso': dict(self.prog), 'cancelable': self.cancelable}


class Aplicacion(object):
    def __init__(self, home=None, repo_override=None, diferir=False):
        """diferir=True: no migra la BD ni vincula el flujo aqui (lo hace arrancar_fondo() en un hilo, para que la ventana salga ya)"""
        self.cfg = config.Config(home, repo_override)
        self._base = None; self._base_ev = threading.Event()      # con diferir=True la BD se abre en el hilo de arranque (puede bloquearse: OneDrive, disco lento)
        self.tarea = Tarea(self.cfg)
        self.flujo = flujo.Flujo(os.path.join(self.cfg.home, 'flujo.json'))   # estados Por hacer / Hecho: solo en la carpeta de datos del editor
        self._R = None; self._motor = None; self._indice = None
        self.lock = threading.RLock()
        self.aviso = ''                                  # mensaje visible en la UI (p. ej. fallback a navegador)
        self.arranque = {'listo': True, 'fase': '', 'hecho': 0, 'total': 0}
        self._fondo = False; self.vigencia = None                             # estado del indice persistente: {'vigente', 'hojas_cambiadas', 'motivo'}
        if diferir: self.arranque['listo'] = False
        else: self._preparar_base()

    @property
    def base(self):
        if self._base is None and not self._base_ev.wait(30): raise RuntimeError('La base de datos se esta preparando; espera unos segundos.')
        if self._base is None: raise RuntimeError('La base de datos no esta disponible; mira el registro (Ayuda > Abrir carpeta de datos y registros).')
        return self._base

    def abrir_base(self):
        """abre editor.db (con diferir=True lo hace el hilo de arranque; puede tardar). Idempotente."""
        if self._base is None:
            self.arranque.update(fase='abriendo la base de datos')
            try:
                with registro.fase('apertura de la base'): self._base = indexer.Base(self.cfg.db_ruta)
            finally: self._base_ev.set()
        return self._base

    def motivo_base(self):
        return self._base.motivo if self._base is not None else ''

    def _preparar_base(self):
        def av(fase, hecho=0, total=0): self.arranque.update(fase=fase, hecho=hecho, total=total)
        self.abrir_base()
        with registro.fase('migracion de la base'): self.base.migrar_datos(av)
        with registro.fase('flujo -> columna'): self.base.vincular_flujo(self.flujo)

    def arrancar_fondo(self, ui_cargada=None, tras_ui=None):
        """IDEMPOTENTE. Migracion de editor.db antigua + flujo (hilo 'arranque': la UI muestra «Cargando...» con la fase y el editor sigue usable) y, en OTRO hilo de baja
        prioridad, la comprobacion de si el indice sigue vigente: espera a que la UI haya cargado (maximo 60 s) para no competir con la ventana por el disco.
        `tras_ui` (migracion de la carpeta antigua, copytree) corre en ese mismo hilo, DESPUES de ui_cargada; si copia algo se recargan ajustes y flujo."""
        with self.lock:
            if self._fondo: return
            self._fondo = True
        def f():
            try: self._preparar_base()
            except BaseException:
                log.error('arranque en segundo plano', exc_info=True)
                self.aviso = 'Error preparando la base de datos; mira el registro (Ayuda > Abrir carpeta de datos y registros).'
            finally:
                self.arranque.update(listo=True, fase='', hecho=0, total=0)
        def v():
            if ui_cargada is not None:
                with registro.fase('espera de la UI para comprobar la vigencia'): ui_cargada.wait(60)
            if tras_ui is not None:
                try:
                    with registro.fase('migracion de la carpeta antigua'): copiados = tras_ui()
                    if copiados:
                        self.cfg.recargar(); self.flujo.recargar()
                        while not self.arranque.get('listo'): time.sleep(0.2)
                        if self._base is not None: self._base.vincular_flujo(self.flujo)
                except BaseException: log.error('migracion de la carpeta antigua', exc_info=True)
            while not self.arranque.get('listo'): time.sleep(0.2)
            try:
                with registro.fase('vigencia del indice'): self.refrescar_vigencia()
            except BaseException: log.error('vigencia', exc_info=True)
        threading.Thread(target=f, daemon=True, name='arranque').start()
        threading.Thread(target=v, daemon=True, name='vigencia').start()

    def refrescar_vigencia(self):
        try:
            if not repo_env.hay_repo(self.cfg.repo_dir): self.vigencia = {'vigente': False, 'hojas_cambiadas': 0, 'motivo': 'sin_repo'}; return self.vigencia
            self.vigencia = indexer.estado_indice(None, self.base, self.cfg.repo_dir, self.raiz_textos(), self.cfg.ediciones_dir)
        except Exception as x:
            log.warning('vigencia: %s', x); self.vigencia = None
        return self.vigencia

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
        try:
            if self._base is None: raise sqlite3.Error('base aun no abierta')
            indice = indexer.meta(self.base); contadores = indexer.contadores(self.base)
        except sqlite3.Error as x:      # /api/estado responde SIEMPRE (con arranque.fase y progreso) aunque la BD este ocupada
            log.warning('estado: base no disponible: %s', x); indice = None; contadores = {e: 0 for e in indexer.ESTADOS}
        return {'config': self.cfg.publico(), 'sync': self._leer('sync_info.json'), 'juego': j, 'indice': indice, 'contadores': contadores,
                'ediciones': edits.contar(self.cfg.ediciones_dir), 'repo_ok': repo_env.hay_repo(self.cfg.repo_dir), 'tarea': self.tarea.ver(10 ** 9),
                'version_recomendada': self._recomendada(), 'clases': clases.CLASES, 'flujo': self.flujo.totales(),
                'arranque': dict(self.arranque, ocupada=self.motivo_base()), 'indice_estado': self.vigencia, 'aviso': self.aviso, 'registro': registro.ruta_log(self.cfg.home)}

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
             'clase': clases.clase_de(c.hoja), 'flujo': self.flujo.estado(c.hoja, c.row, c.sub, c.col), 'parche': self.flujo.etiqueta(c.hoja, c.row, c.sub, c.col),
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

    HABLANTE_RE = celda_mod.HABLANTE_RE

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
        return {'ok': r['ok'], 'errores': [list(x) for x in r['errores']], 'avisos': [list(x) for x in r['avisos']], 'vista': r['vista'], 'variantes': r.get('variantes'), 'suavizado': r.get('suavizado'), 'texto': r['texto']}

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
        self.base.exigir_libre()
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
            if self._indice is None: self._indice = busqueda.Indice.desde_base(self.base)   # perezoso y sin filas en RAM: recorre SQLite al buscar
            return self._indice

    @staticmethod
    def consulta(b):
        return busqueda.Consulta(b.get('texto', ''), b.get('campos') or ('ja', 'fr', 'es'), b.get('modo', 'subcadena'), b.get('mayus', False), b.get('tildes', False), b.get('estados'), b.get('hoja'), b.get('clase'), b.get('flujo'))

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
        if b.get('aplicar'): self.base.exigir_libre()
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
                edits.guardar(self.base, self.cfg.ediciones_dir, m.R, c, r['es'], comprobar=False)
                self.indice().actualizar(f['id'], edits_plano(r['es']), 'verde')
            cambios.append(item)
        return {'aplicado': bool(b.get('aplicar')), 'cambios': cambios[:300], 'n_cambios': len(cambios), 'rechazadas': rechazadas[:300], 'n_rechazadas': len(rechazadas), 'sin_cambio': sin_cambio}

    # ------------------------------------------------------------ flujo de trabajo (Por hacer / Hecho)
    def _idx_flujo(self):
        return self.indice()

    def _celdas_de(self, b):
        """seleccion de celdas del cuerpo: ids | tabla (filtro del panel izquierdo) | busqueda (consulta global) -> [(hoja,row,sub,col)]"""
        if b.get('ids') is not None:
            cs = []
            for i in b['ids']:
                r = indexer.obtener(self.base, int(i))
                if r: cs.append((r['hoja'], r['row'], r['sub'], r['col']))
        elif b.get('tabla') is not None:
            t = b['tabla']
            cs = indexer.celdas_filtradas(self.base, t.get('hoja') or None, [e for e in (t.get('estados') or []) if e in indexer.ESTADOS] or None, t.get('q') or None, bool(t.get('editadas')), t.get('clase') or None, t.get('flujo') or None)
        elif b.get('busqueda') is not None:
            q = self.consulta(b['busqueda'])
            cs = [(f['hoja'], f['row'], f['sub'], f['col']) for f, _ in self._idx_flujo().coincidencias(q)]
        else: raise ValueError('indica ids, tabla o busqueda')
        return cs

    def flujo_marcar(self, b):
        """b['estado'] = por_hacer|hecho|sin y UNO de: ids (celdas), tabla (filtro del panel izquierdo: marca TODOS los resultados filtrados) o busqueda (consulta global: todos sus resultados)"""
        estado = b.get('estado')
        if estado not in flujo.ESTADOS: raise ValueError('estado desconocido')
        cs = self._celdas_de(b)
        n = self.flujo.poner(cs, estado)
        return {'marcadas': len(cs), 'cambiadas': n, 'totales': self.flujo.totales()}

    # ------------------------------------------------------------ suavizado de saltos en bloque (con deshacer)
    MAX_SUAVIZAR = 3000

    MODOS_SUAVIZAR = ('suavizar', 'sin_saltos', 'sin_saltos_suavizar')

    def _suavizar_candidatas(self, b):
        """celdas verdes con traduccion cuyo texto cambia -> (cambios, sin_cambio, omitidas, no_admite, truncado). Sin escribir nada.
        b['modo']: suavizar (reflujo/espaciado) | sin_saltos (quita los saltos de presentacion) | sin_saltos_suavizar (quita todo y re-suaviza)"""
        modo = b.get('modo') or 'suavizar'
        if modo not in self.MODOS_SUAVIZAR: raise ValueError('modo desconocido')
        cs = self._celdas_de(b); trunc = len(cs) > self.MAX_SUAVIZAR; cs = cs[:self.MAX_SUAVIZAR]
        m = self.motor(); cambios = []; sin = 0; omitidas = 0; no_admite = 0; descartadas = 0
        for hoja, row, sub, col in cs:
            r = self.base.q('SELECT * FROM celdas WHERE hoja=? AND row=? AND sub IS ? AND col=?', (hoja, row, sub, col))
            if not r or not r[0]['es_json'] or r[0]['estado'] != 'verde': omitidas += 1; continue
            reg = dict(r[0])
            try:
                c = m.contexto(hoja, row, sub, col)
                es0 = json.loads(reg['es_json']); es1 = es0
                if modo != 'suavizar':
                    es1 = m.sin_saltos(c, es0)
                    if es1 is None:
                        if m._unir(' '.join(es0) if isinstance(es0, list) else es0) != (' '.join(es0) if isinstance(es0, list) else es0): no_admite += 1
                        else: sin += 1
                        continue
                antes = m.es_a_texto(c, es0)
                ev = m.evaluar(c, m.es_a_texto(c, es1), 'masc', modo != 'sin_saltos')
            except Exception: omitidas += 1; continue
            if ev['errores'] or ev['es'] is None: omitidas += 1; continue
            if json.dumps(ev['es'], ensure_ascii=False) == json.dumps(es0, ensure_ascii=False): sin += 1; continue
            if not self._solo_saltos(es0, ev['es']): descartadas += 1; continue   # cambiaria algo mas que saltos/espacios (p. ej. normalizacion de signos)
            cambios.append({'id': reg['id'], 'hoja': hoja, 'row': row, 'sub': sub, 'col': col, 'antes': antes, 'despues': ev['texto'], 'es_antes': es0, 'es_despues': ev['es']})
        return cambios, sin, omitidas, no_admite, trunc, descartadas

    @staticmethod
    def _solo_saltos(a, b):
        """True si a y b (str o lista de trozos) tienen el mismo n. de trozos y la misma secuencia plana de palabras (uniendo trozos)"""
        la = a if isinstance(a, list) else [a]; lb = b if isinstance(b, list) else [b]
        if len(la) != len(lb) or isinstance(a, list) != isinstance(b, list): return False
        quitar = lambda l: [w for x in l if isinstance(x, str) for w in re.sub(r'<NewLine(?:#\d+)?>', ' ', x).split()]   # secuencia PLANA de palabras: acepta mover palabras entre trozos vecinos, no fusionar/partir/reordenar
        if quitar(la) != quitar(lb) or [not isinstance(x, str) for x in la] != [not isinstance(x, str) for x in lb]: return False
        def macros(x):   # multiconjunto de macros (todo <...> salvo NewLine) del trozo: ninguna macro puede cambiar de trozo ni partirse
            return sorted(t for t in re.findall(r'<[^<>]*>', x) if not re.fullmatch(r'<NewLine(?:#\d+)?>', t)) if isinstance(x, str) else None
        if [macros(x) for x in la] != [macros(x) for x in lb]: return False
        return [bool(quitar([x])) if isinstance(x, str) else None for x in la] == [bool(quitar([x])) if isinstance(x, str) else None for x in lb]   # trozo vacio <-> no vacio

    def sin_saltos_texto(self, id_, texto, resuavizar=False):
        """celda actual: aplica «eliminar saltos» (y opcionalmente re-suaviza) al TEXTO del editor sin guardar -> {texto, cambia, motivo}"""
        reg = indexer.obtener(self.base, id_)
        m = self.motor(); c = m.contexto(reg['hoja'], reg['row'], reg['sub'], reg['col'])
        try: es0 = m.texto_a_es(c, texto)
        except ValueError as x: return {'texto': texto, 'cambia': False, 'motivo': 'estructura: %s' % x}
        es1 = m.sin_saltos(c, es0)
        if es1 is None:
            quedan = m._unir(' '.join(es0) if isinstance(es0, list) else es0) != (' '.join(es0) if isinstance(es0, list) else es0)
            return {'texto': texto, 'cambia': False, 'motivo': 'esta celda no admite quitar los saltos sin romper el formato; no se toca' if quedan else 'no habia saltos que quitar'}
        t = m.es_a_texto(c, es1)
        if resuavizar:
            ev = m.evaluar(c, t, 'masc', True)
            if not ev['errores'] and ev['es'] is not None: t = ev['texto']
        return {'texto': t, 'cambia': t != texto, 'motivo': ''}

    def suavizar_previa(self, b):
        cambios, sin, omitidas, no_admite, trunc, desc = self._suavizar_candidatas(b)
        return {'n_cambios': len(cambios), 'sin_cambio': sin, 'omitidas': omitidas, 'no_admite': no_admite, 'descartadas_por_texto': desc, 'truncado': trunc, 'maximo': self.MAX_SUAVIZAR,
                'cambios': [{k: v for k, v in x.items() if not k.startswith('es_')} for x in cambios[:100]]}

    def _ruta_deshacer(self): return os.path.join(self.cfg.home, 'suavizado_deshacer.json')

    def suavizar_aplicar(self, b):
        self.base.exigir_libre()
        cambios, sin, omitidas, no_admite, trunc, desc = self._suavizar_candidatas(b)
        m = self.motor(); items = []; por_id = {}
        for x in cambios:
            c = m.contexto(x['hoja'], x['row'], x['sub'], x['col']); items.append((c, x['es_despues'])); por_id[c.k, c.hoja] = x
        hechos, fallos = edits.guardar_lote(self.base, self.cfg.ediciones_dir, m.R, items)
        reg = []
        for h in hechos:
            c = h['c']; x = por_id[c.k, c.hoja]
            if self._indice is not None: self._indice.actualizar(x['id'], edits_plano(x['es_despues']), 'verde')
            reg.append({'hoja': c.hoja, 'row': c.row, 'sub': c.sub, 'col': c.col, 'previa': h['previa'], 'db': h['db'], 'es_despues': x['es_despues']})
        if reg:
            lote = (self._leer('suavizado_deshacer.json') or [])[-19:]
            lote.append({'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'celdas': reg})
            with open(self._ruta_deshacer(), 'w', encoding='utf-8') as f: json.dump(lote, f, ensure_ascii=False)
        return {'aplicadas': len(reg), 'sin_cambio': sin, 'omitidas': omitidas + len(fallos), 'no_admite': no_admite, 'descartadas_por_texto': desc, 'truncado': trunc}

    def suavizar_deshacer(self):
        """restaura el ultimo lote: devuelve cada celda a su texto, origen y fila de ediciones anteriores. Las celdas cambiadas despues de la tanda NO se tocan y se reportan"""
        self.base.exigir_libre()
        lote = self._leer('suavizado_deshacer.json') or []
        if not lote: raise ValueError('no hay nada que deshacer')
        ult = lote.pop(); ok = []; cambiadas = []; incompatibles = 0
        for x in (ult.get('celdas') or []) if isinstance(ult, dict) else []:
            if not isinstance(x, dict) or 'es_despues' not in x or not isinstance(x.get('db'), dict) or not all(k in x for k in ('hoja', 'row', 'sub', 'col')):
                incompatibles += 1; continue   # formato antiguo: se salta y no queda pegada en el fichero
            r = self.base.q('SELECT id,es_json FROM celdas WHERE hoja=? AND row=? AND sub IS ? AND col=?', (x['hoja'], x['row'], x['sub'], x['col']))
            try: actual = json.loads(r[0]['es_json']) if r and r[0]['es_json'] else None
            except ValueError: actual = None
            if actual != x['es_despues']: cambiadas.append({k: x[k] for k in ('hoja', 'row', 'sub', 'col')}); continue
            ok.append(x)
        edits.restaurar_lote(self.base, self.cfg.ediciones_dir, ok)
        if self._indice is not None:
            for x in ok:
                r = self.base.q('SELECT id,es FROM celdas WHERE hoja=? AND row=? AND sub IS ? AND col=?', (x['hoja'], x['row'], x['sub'], x['col']))
                if r: self._indice.actualizar(r[0]['id'], r[0]['es'] or '', 'verde' if x['db']['estado'] == 'verde' else x['db']['estado'])
        with open(self._ruta_deshacer(), 'w', encoding='utf-8') as f: json.dump(lote, f, ensure_ascii=False)
        return {'restauradas': len(ok), 'cambiadas_despues': len(cambiadas), 'cambiadas': cambiadas[:50], 'incompatibles': incompatibles, 'fecha': ult.get('fecha') if isinstance(ult, dict) else None, 'quedan': len(lote)}

    # ------------------------------------------------------------ modo contexto: misiones / escenas / hojas
    def _orden_expansion(self):
        """{hoja: (n. de expansion, posicion)} de trabajo/informes/expansion_historia.tsv (si existe); el orden de expansion es el de primera aparicion"""
        ruta = os.path.join(self.cfg.repo_dir, 'trabajo', 'informes', 'expansion_historia.tsv')
        if getattr(self, '_exp_cache', (None,))[0] == ruta and os.path.exists(ruta) and self._exp_cache[1] == os.path.getmtime(ruta): return self._exp_cache[2]
        d = {}; exps = {}
        try:
            import csv
            with open(ruta, encoding='utf-8', newline='') as f:
                for i, r in enumerate(csv.DictReader(f, delimiter='\t')):
                    e = r.get('expansion') or ''; exps.setdefault(e, len(exps)); d[r['hoja']] = (e, exps[e], i)
            self._exp_cache = (ruta, os.path.getmtime(ruta), d)
        except (OSError, KeyError): d = {}
        return d

    def misiones(self, q=None, clase=None, expansion=None, solo_flujo=None, limite=3000):
        """lista de hojas (misiones/escenas/hojas) con contador de celdas, de Por hacer y de Hecho, ordenada por expansion (si hay tabla) y luego por nombre"""
        orden = self._orden_expansion()
        res = []; ql = (q or '').lower()
        for r in indexer.hojas_resumen_flujo(self.base):   # UNA consulta agregada (color y flujo por hoja); solo cuentan celdas que existen en el indice
            h = r['hoja']
            if clase and clases.clase_de(h) != clase: continue
            if ql and ql not in h.lower(): continue
            e = orden.get(h)
            if expansion and (not e or e[0] != expansion): continue
            x = {'hoja': h, 'total': r['total'], 'rojo': r['rojo'], 'naranja': r['naranja'], 'verde': r['verde'], 'blanco': r['blanco'],
                 'por_hacer': r['por_hacer'], 'hecho': r['hecho'], 'expansion': e[0] if e else '', 'clase': clases.clase_de(h), '_o': (e[1], e[2]) if e else (999, 0)}
            if solo_flujo == 'por_hacer' and not x['por_hacer']: continue
            if solo_flujo == 'hecho' and x['hecho'] < x['total']: continue
            res.append(x)
        res.sort(key=lambda x: (x['_o'], x['hoja']))
        for x in res: del x['_o']
        exps = sorted({v[0] for v in orden.values()}, key=lambda e: next(v[1] for v in orden.values() if v[0] == e)) if orden else []
        return {'total': len(res), 'misiones': res[:limite], 'expansiones': exps}

    def hoja_celdas(self, hoja, limite=4000):
        """todas las celdas de una hoja en el orden de traduccion (fila, sub, col) con hablante, para leerla como conversacion continua"""
        rs = self.base.q('SELECT id,row,sub,col,estado,substr(ja,1,400) ja,substr(fr,1,400) fr,substr(es,1,400) es,editada FROM celdas WHERE hoja=? ORDER BY row, COALESCE(sub,-1), col LIMIT ?', (hoja, limite))
        out = []
        for r in rs:
            d = dict(r); t = (d['es'] or d['ja'] or '')
            m = celda.HABLANTE_RE.match(d['es'] or '') or celda.HABLANTE_RE.match(d['ja'] or '')
            d['hablante'] = m.group(1) if m else None
            d['flujo'] = self.flujo.estado(hoja, d['row'], d['sub'], d['col'])
            out.append(d)
        return {'hoja': hoja, 'celdas': out, 'truncado': len(out) >= limite}

    def _ruta_segura(self, p):
        """acepta solo rutas absolutas sin '..' dentro de la carpeta de datos del editor o de la carpeta elegida con el dialogo (carpeta_dat); -> ruta real"""
        if not isinstance(p, str) or not p or '\x00' in p: raise ValueError('ruta no valida')
        if '..' in re.split(r'[\\/]', p): raise ValueError('ruta no permitida: contiene ..')
        if not os.path.isabs(p): raise ValueError('ruta no permitida: debe ser absoluta')
        real = os.path.realpath(p); nc = os.path.normcase
        raices = [os.path.realpath(self.cfg.home)] + ([os.path.realpath(self.cfg['carpeta_dat'])] if self.cfg['carpeta_dat'] else [])
        if not any(nc(real) == nc(r) or nc(real).startswith(nc(r).rstrip(os.sep) + os.sep) for r in raices): raise ValueError('ruta fuera de la carpeta de datos del editor o de la carpeta elegida')
        return real

    def flujo_exportar(self, destino=None):
        destino = self._ruta_segura(destino or self.cfg['carpeta_dat'] or self.cfg.sub('exportado'))
        os.makedirs(destino, exist_ok=True)
        ruta = os.path.join(destino, 'flujo_%s.tsv' % time.strftime('%Y%m%d-%H%M%S'))
        return {'ruta': ruta, 'filas': self.flujo.exportar_tsv(ruta)}

    def flujo_importar(self, contenido=None, reemplazar=False, ruta=None):
        """contenido = texto TSV (el fichero elegido en la UI) o ruta a un TSV"""
        if contenido is not None: n, ign = self.flujo.importar_texto(contenido, bool(reemplazar))
        elif ruta and os.path.isfile(self._ruta_segura(ruta)): n, ign = self.flujo.importar_tsv(self._ruta_segura(ruta), bool(reemplazar))
        else: raise ValueError('indica el contenido o un fichero existente')
        return {'importadas': n, 'ignoradas': ign, 'totales': self.flujo.totales()}

    # ------------------------------------------------------------ tareas
    def _indexar(self, log, forzar=False):
        R = self.R(); self.olvidar_motor(); self._indice = None
        t = self.tarea
        meta = indexer.indexar(R, self.base, self.cfg.repo_dir, self.raiz_textos(), self.cfg.ediciones_dir, log, forzar=forzar, cancelar=t.cancelar_ev, avance=t.avance)
        self.vigencia = {'vigente': True, 'hojas_cambiadas': 0, 'motivo': 'ok'}
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

    def _version_base(self, raiz):
        """version del juego del textos anterior (info.json de la extraccion previa o, si no hay, la recomendada del repo)"""
        return extractor.version_de_info(self.cfg.juego_dir) if os.path.abspath(raiz) == os.path.abspath(self.cfg.juego_dir) else self._recomendada()

    def _informe_parche(self, R, raiz_anterior, textos_nuevos, info, log):
        """compara el textos/ja anterior con la extraccion nueva (aun sin cambiar) y guarda datos/parches/<version>.json. Solo lectura de traducciones. -> dict"""
        raiz_nuevo = os.path.dirname(textos_nuevos)
        version = info.get('version') or time.strftime('sin-version-%Y%m%d-%H%M%S')
        log('comparando con la version anterior (%s)...' % (self._version_base(raiz_anterior) or 'repo'))
        hojas = parche.comparar(raiz_anterior, raiz_nuevo, self.cfg.repo_dir, self.cfg.ediciones_dir, R.G.tiene_cjk, R.G.hash_ja, log)
        inf, escrito = parche.guardar_informe(self.cfg.parches_dir, parche.crear_informe(version, self._version_base(raiz_anterior), hojas))
        log('novedades %s: %s%s' % (version, json.dumps(inf['conteos']), '' if escrito else ' (ya importado: se conserva el informe)'))
        return {'informe': inf, 'escrito': escrito}

    def tarea_extraer(self, ruta=None):
        """«Importar parche»: extrae el juego a un temporal, compara con la extraccion anterior (o el repo), guarda el informe de novedades, cambia textos/ de forma atomica
        (con copia de la anterior), deja lo nuevo/cambiado en «Por hacer» y reindexa. Nada de esto escribe traducciones/ ni ediciones/ ni el es."""
        cfg = self.cfg
        if ruta: cfg.actualizar({'ruta_juego': ruta})
        game = cfg['ruta_juego']
        extractor.comprobar_ruta(game)
        def fn(log):
            R = self.R(); ctx = {}
            anterior = self.raiz_textos()
            info = extractor.extraer(R, game, cfg.juego_dir, ('ja', 'fr'), log, antes_de_cambiar=lambda tn, inf: ctx.update(self._informe_parche(R, anterior, tn, inf, log)),
                                     copias_dir=cfg.copias_dir)
            inf = ctx.get('informe')
            if inf and ctx.get('escrito'):
                info['flujo'] = parche.marcar_flujo(self.flujo, inf); log('flujo: %s' % json.dumps(info['flujo']))
            if inf: info['parche'] = {'version': inf['version'], 'conteos': inf['conteos'], 'ya_importado': not ctx.get('escrito')}
            log('reindexando contra el juego extraido...'); info['indice'] = self._indexar(log)
            return info
        self.tarea.iniciar('extraer', fn)

    # ------------------------------------------------------------ novedades del parche
    def parches(self):
        return {'parches': parche.listar_informes(self.cfg.parches_dir)}

    def _informe(self, version):
        v = version or (parche.listar_informes(self.cfg.parches_dir) or [{}])[0].get('version')
        inf = parche.leer_informe(self.cfg.parches_dir, v) if v else None
        if not inf: raise KeyError('no hay informe de novedades' + (' para %s' % v if v else ': importa un parche primero'))
        return inf

    def parche_hojas(self, version=None, tipo=None, q=None):
        """hojas con novedades en el orden de traduccion (expansion y luego nombre, como el modo mision). tipo: nuevas|cambiadas|borradas|movidas|None (cualquiera)"""
        inf = self._informe(version); orden = self._orden_expansion(); ql = (q or '').lower(); res = []
        pend = {}
        for r in indexer.hojas_resumen_flujo(self.base): pend[r['hoja']] = (r['por_hacer'], r['hecho'])
        for hoja, d in inf['hojas'].items():
            if ql and ql not in hoja.lower(): continue
            if tipo in parche.TIPOS and not d.get(tipo): continue
            e = orden.get(hoja)
            res.append({'hoja': hoja, **{t: len(d[t]) for t in parche.TIPOS}, 'movidas_pend': sum(1 for m in d['movidas'] if not m.get('aceptada')), 'expansion': e[0] if e else '',
                        'clase': clases.clase_de(hoja), 'por_hacer': pend.get(hoja, (0, 0))[0], 'hecho': pend.get(hoja, (0, 0))[1], '_o': (e[1], e[2]) if e else (999, 0)})
        res.sort(key=lambda x: (x['_o'], x['hoja']))
        for x in res: del x['_o']
        return {'version': inf['version'], 'base_version': inf.get('base_version'), 'fecha': inf.get('fecha'), 'conteos': inf['conteos'], 'total': len(res), 'hojas': res}

    def parche_hoja(self, version, hoja, filtro=None):
        """la hoja como conversacion (hoja_celdas) con cada celda marcada `novedad` = nueva|cambiada (+ ja_anterior); filtro nuevas|cambiadas deja solo esas celdas MAS la anterior y
        la siguiente como contexto (`contexto`: True). Incluye las borradas (con su es) y las movidas de la hoja."""
        inf = self._informe(version); d = inf['hojas'].get(hoja) or {'nuevas': [], 'cambiadas': [], 'borradas': [], 'movidas': []}
        nov = {(r, s, c): ('nueva', None) for r, s, c in d['nuevas']}
        nov.update({(r, s, c): ('cambiada', ja) for r, s, c, ja in d['cambiadas']})
        celdas = self.hoja_celdas(hoja)['celdas']; filtro = filtro if filtro in ('nuevas', 'cambiadas') else None
        for x in celdas:
            n = nov.get((x['row'], x['sub'], x['col']))
            x['novedad'] = n[0] if n else None
            if n and n[1] is not None: x['ja_anterior'] = n[1][:400]
            x['etiqueta'] = self.flujo.etiqueta(hoja, x['row'], x['sub'], x['col'])
        if filtro:
            quiere = 'nueva' if filtro == 'nuevas' else 'cambiada'
            idx = [i for i, x in enumerate(celdas) if x['novedad'] == quiere]; mant = {}
            for i in idx:
                for j in (i - 1, i, i + 1):
                    if 0 <= j < len(celdas): mant[j] = (j == i)
            celdas = [dict(celdas[j], contexto=not mant[j]) for j in sorted(mant)]
        return {'version': inf['version'], 'hoja': hoja, 'celdas': celdas, 'borradas': [{'row': r, 'sub': s, 'col': c, 'ja': ja, 'es': es} for r, s, c, ja, es in d['borradas']],
                'movidas': d['movidas']}

    def parche_movidas(self, version=None, hoja=None, limite=2000):
        """vista previa de las traducciones que se podrian arrastrar (no aplica nada): ja, es de la borrada, destino y si el destino ya esta traducido"""
        inf = self._informe(version); out = []; tot = 0
        for h, d in sorted(inf['hojas'].items()):
            if hoja and h != hoja: continue
            for m in d['movidas']:
                tot += 1
                if len(out) >= limite: continue
                r = self.base.q('SELECT estado FROM celdas WHERE hoja=? AND row=? AND sub IS ? AND col=?', (h, m['a'][0], m['a'][1], m['a'][2]))
                out.append({'hoja': h, 'de': m['de'], 'a': m['a'], 'ja': m['ja'][:400], 'es': indexer.plano(m['es'])[:400], 'aceptada': bool(m.get('aceptada')),
                            'estado_destino': r[0]['estado'] if r else None})
        return {'version': inf['version'], 'total': tot, 'movidas': out}

    def parche_arrastrar(self, version=None, hoja=None, destinos=None):
        """ACEPTAR por lote: escribe en ediciones/ (origen sesion, con las mismas puertas que al guardar) la traduccion de la fila borrada en la fila movida. Solo las movidas
        del lote (hoja = una hoja; destinos = [[hoja,row,sub,col]]; ninguno = todas las pendientes). Nunca se llama solo desde la importacion."""
        self.base.exigir_libre()
        inf = self._informe(version); sel = {tuple(x) for x in destinos} if destinos else None
        m_ = self.motor(); items = []; omitidas = []; refs = []
        for h, d in inf['hojas'].items():
            if hoja and h != hoja: continue
            for m in d['movidas']:
                a = tuple(m['a'])
                if m.get('aceptada') or (sel is not None and (h,) + a not in sel): continue
                r = self.base.q('SELECT estado FROM celdas WHERE hoja=? AND row=? AND sub IS ? AND col=?', (h, a[0], a[1], a[2]))
                if not r: omitidas.append({'hoja': h, 'a': list(a), 'motivo': 'la celda no esta en el indice'}); continue
                if r[0]['estado'] == 'verde': omitidas.append({'hoja': h, 'a': list(a), 'motivo': 'el destino ya esta traducido'}); continue
                items.append((m_.contexto(h, a[0], a[1], a[2]), m['es'])); refs.append((h, m))
        hechos, fallos = edits.guardar_lote(self.base, self.cfg.ediciones_dir, m_.R, items) if items else ([], [])
        mal = {(c.hoja,) + c.k for c, _ in fallos}
        for h, m in refs:
            if (h,) + tuple(m['a']) not in mal: m['aceptada'] = True
        if hechos:
            with self.lock: self._indice = None
            ruta = os.path.join(self.cfg.parches_dir, extractor.version_segura(inf['version']) + '.json'); tmp = ruta + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f: json.dump(inf, f, ensure_ascii=False, separators=(',', ':'))
            os.replace(tmp, ruta)
        return {'aplicadas': len(hechos), 'fallos': [{'hoja': c.hoja, 'a': [c.row, c.sub, c.col], 'motivo': t} for c, t in fallos], 'omitidas': omitidas}

    def tarea_indexar(self, forzar=False):
        self.tarea.iniciar('indexar', lambda log: self._indexar(log, bool(forzar)), cancelable=True)

    def tarea_cancelar(self):
        return {'cancelada': self.tarea.cancelar()}

    def abrir_registros(self):
        return {'ruta': registro.abrir_carpeta(self.cfg.home)}

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
