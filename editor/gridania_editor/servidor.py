"""Servidor HTTP local (127.0.0.1) con API JSON y la interfaz (ui/index.html). Protegido con una clave por ejecucion (cabecera X-K) y comprobacion de Host."""
import json, logging, os, secrets, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import indexer

log = logging.getLogger('gridania.http')


def dir_ui():
    base = getattr(sys, '_MEIPASS', None)
    cand = [os.path.join(base, 'gridania_editor', 'ui')] if base else []
    cand.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui'))
    for c in cand:
        if os.path.isdir(c): return c
    return cand[-1]


class Servidor(object):
    def __init__(self, app, puerto=0):
        self.app = app; self.clave = secrets.token_urlsafe(16); self.salir = threading.Event(); self.ui_cargada = threading.Event(); self.fallo = None; self.al_pedir_pagina = None; self.url_navegador = None
        self.t_latido = None; self.t_get = None; self.t_cierre = None; self.n_latidos = 0; self.t_despertar = None; self._lock_bor = threading.Lock()      # time.monotonic() del ultimo latido / GET / / aviso de cierre (sendBeacon)
        servidor = self
        class H(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *a): pass
            def _host_ok(self):
                h = (self.headers.get('Host') or '').split(':')[0]
                return h in ('127.0.0.1', 'localhost')
            def _json(self, obj, codigo=200):
                b = json.dumps(obj, ensure_ascii=False).encode('utf-8')
                self.send_response(codigo); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(b)
            def _err(self, codigo, msg): self._json({'error': app.cfg.redactar(str(msg))}, codigo)
            def _lento(self, ruta, t0):
                dt = time.time() - t0
                if dt > 1.0: log.warning('peticion lenta %s: %.1f s', ruta, dt)
            def _auth(self, q=None):
                if secrets.compare_digest((self.headers.get('X-K') or '').encode('utf-8'), servidor.clave.encode('utf-8')): return True
                return bool(q) and secrets.compare_digest(str(q.get('k') or '').encode('utf-8'), servidor.clave.encode('utf-8'))      # sendBeacon no puede poner cabeceras: la clave va en ?k=
            def do_GET(self):
                if not self._host_ok(): return self._err(403, 'host no permitido')
                u = urllib.parse.urlparse(self.path); q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                if u.path in ('/', '/index.html'):
                    servidor.t_get = time.monotonic()
                    try: html = open(os.path.join(dir_ui(), 'index.html'), encoding='utf-8').read().replace('__CLAVE__', servidor.clave)
                    except OSError: return self._err(500, 'falta ui/index.html')
                    if not servidor.ui_cargada.is_set():
                        servidor.ui_cargada.set()
                        try: servidor.al_pedir_pagina and servidor.al_pedir_pagina()
                        except Exception: log.warning('al_pedir_pagina', exc_info=True)
                    b = html.encode('utf-8'); self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(b); return
                if u.path == '/borradores.js':                      # codigo estatico de la UI (sin secretos)
                    try: b = open(os.path.join(dir_ui(), 'borradores.js'), 'rb').read()
                    except OSError: return self._err(500, 'falta ui/borradores.js')
                    self.send_response(200); self.send_header('Content-Type', 'text/javascript; charset=utf-8'); self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(b); return
                if not u.path.startswith('/api/'): return self._err(404, 'no existe')
                if not self._auth(): return self._err(401, 'clave invalida')
                t0 = time.time()
                try: self._json(servidor.get(u.path, q)); self._lento(u.path, t0)
                except KeyError as x: self._err(404, x)
                except (ValueError, RuntimeError) as x: self._err(400, x)
                except Exception as x: log.error('GET %s', u.path, exc_info=True); self._err(500, '%s: %s' % (type(x).__name__, x))
            def do_POST(self):
                if not self._host_ok(): return self._err(403, 'host no permitido')
                u = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                if not self._auth(q if u.path == '/api/cierre' else None): return self._err(401, 'clave invalida')
                try:
                    n = int(self.headers.get('Content-Length') or 0); cuerpo = json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
                    t0 = time.time(); self._json(servidor.post(u.path, cuerpo)); self._lento(u.path, t0)
                except KeyError as x: self._err(404, x)
                except (ValueError, RuntimeError) as x: self._err(400, x)
                except Exception as x: log.error('POST %s', u.path, exc_info=True); self._err(500, '%s: %s' % (type(x).__name__, x))
        self.httpd = ThreadingHTTPServer(('127.0.0.1', puerto), H)
        self.puerto = self.httpd.server_address[1]
        self.hilo = None

    @property
    def url(self): return 'http://127.0.0.1:%d/' % self.puerto

    def arrancar(self):
        def servir():
            try: self.httpd.serve_forever()
            except BaseException as x:
                # si el servidor HTTP muere la ventana queda inutil y sin esto el proceso seguiria vivo en segundo plano: se registra y se termina
                self.fallo = '%s: %s' % (type(x).__name__, x); log.critical('el servidor HTTP ha terminado: %s', self.fallo, exc_info=True)
                try: sys.stderr and sys.stderr.write('El servidor del editor ha fallado: %s\n' % self.fallo)
                except Exception: pass
                self.salir.set()
        self.hilo = threading.Thread(target=servir, daemon=True, name='http'); self.hilo.start()

    def registrar_latido(self): self.t_latido = time.monotonic(); self.n_latidos += 1

    def reabrir(self):
        """la pagina vuelve de bfcache/suspension: anula un aviso de cierre pendiente. Si el editor ya esta cerrando -> ok False."""
        if self.salir.is_set(): return {'ok': False, 'cerrado': True}
        self.t_cierre = None; self.registrar_latido(); return {'ok': True}

    # borradores del texto sin guardar: UNO POR CELDA (clave hoja|row|sub|col, con h) en datos/borradores.json (NUNCA en traducciones)
    def _ruta_borradores(self): return os.path.join(self.app.cfg.home, 'borradores.json')

    @staticmethod
    def clave_borrador(b):
        sub = b.get('sub'); ver = ''.join(ch for ch in str(b.get('ver') or '') if ch.isalnum())[:16]      # ver: versiones antiguas conservadas de un borrador pendiente de decidir
        return '%s|%d|%s|%d%s' % (str(b['hoja']), int(b['row']), '' if sub is None else int(sub), int(b['col']), '#' + ver if ver else '')

    def _leer_borradores(self):
        try:
            with open(self._ruta_borradores(), encoding='utf-8') as f: d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError): return {}

    def _escribir_borradores(self, d):
        ruta = self._ruta_borradores(); tmp = ruta + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f: json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, ruta)

    def leer_borradores(self):
        with self._lock_bor: d = self._leer_borradores()
        return {'borradores': [v for v in d.values() if isinstance(v, dict) and isinstance(v.get('texto'), str)]}

    MAX_BORRADORES = 10000

    def _h_actual(self, v):
        """h vigente de la celda segun el indice (None si no se sabe)"""
        try:
            r = self.app.base.q('SELECT h FROM celdas WHERE hoja=? AND row=? AND sub IS ? AND col=?', (v['hoja'], v['row'], v['sub'], v['col']))
            return str(r[0]['h']) if r else None
        except Exception: return None

    def _purgar_borradores(self, d, clave, es_version):
        """hace sitio para un borrador nuevo SOLO archivando versiones antiguas (por fecha). NUNCA borra principales (texto sin guardar, «luego», h obsoleto o en conflicto).
        De cada celda con principal en conflicto (h distinto del vigente, o indice sin respuesta) queda siempre su version archivada mas reciente."""
        def sitio(): return len(d) < self.MAX_BORRADORES
        def f(v): return v.get('fecha') if isinstance(v.get('fecha'), (int, float)) else 0
        def celda(k): return k.split('#', 1)[0]
        vers = [k for k, v in d.items() if isinstance(v, dict) and v.get('ver')]
        protegidas = set()
        for c in {celda(k) for k in vers}:
            pr = d.get(c)
            if not isinstance(pr, dict): continue
            h = self._h_actual(pr)
            if h is None or h != str(pr.get('h')):                                  # conflicto (o indice caido: no se purga nada por h)
                protegidas.add(max((k for k in vers if celda(k) == c), key=lambda k: f(d[k])))
        for k in sorted(vers, key=lambda k: f(d[k])):
            if sitio(): break
            if k not in protegidas: del d[k]
        return sitio()

    def guardar_borrador(self, b):
        texto = str(b.get('texto', ''))
        if len(texto) > 2000000: raise ValueError('borrador demasiado grande')
        clave = self.clave_borrador(b)
        reg = {'hoja': str(b['hoja']), 'row': int(b['row']), 'sub': None if b.get('sub') is None else int(b['sub']), 'col': int(b['col']),
               'ver': ''.join(ch for ch in str(b.get('ver') or '') if ch.isalnum())[:16], 'h': str(b.get('h', '')), 'texto': texto, 'base': str(b.get('base', '')), 'fecha': time.time()}
        if b.get('luego') is True and not reg['ver']: reg['luego'] = True                  # «Decidir luego»: sobrevive a recargas
        with self._lock_bor:
            d = self._leer_borradores()
            if clave not in d and len(d) >= self.MAX_BORRADORES and not self._purgar_borradores(d, clave, bool(reg['ver'])): raise ValueError('demasiados borradores')
            d[clave] = reg; self._escribir_borradores(d)
        return {'ok': True}

    def borrar_borrador(self, b):
        clave = self.clave_borrador(b)
        with self._lock_bor:
            d = self._leer_borradores()
            if clave in d:
                del d[clave]
                if d: self._escribir_borradores(d)
                else:
                    try: os.remove(self._ruta_borradores())
                    except OSError: pass
        return {'ok': True}

    def pedir_cierre(self): self.t_cierre = time.monotonic()

    def parar(self):
        self.httpd.shutdown(); self.httpd.server_close()

    # ------------------------------------------------------------ rutas
    def get(self, ruta, q):
        a = self.app
        if ruta == '/api/estado': return a.estado()
        if ruta == '/api/latido': self.registrar_latido(); return {'ok': True}
        if ruta == '/api/hojas': return {'hojas': indexer.hojas_resumen(a.base, q.get('q') or None)}
        if ruta == '/api/celdas':
            est = [e for e in (q.get('estados') or '').split(',') if e in indexer.ESTADOS]
            fl = q.get('flujo') if q.get('flujo') in ('por_hacer', 'hecho', 'sin') else None
            hoja, cl, txt, ed = q.get('hoja') or None, q.get('clase') or None, q.get('q') or None, q.get('editadas') == '1'
            total, filas = indexer.listar(a.base, hoja, est or None, txt, max(0, int(q.get('offset') or 0)), min(500, max(1, int(q.get('limite') or 100))), ed, cl, fl)
            return {'total': total, 'filas': filas, 'contadores': indexer.contadores(a.base, hoja, cl, fl),
                    'contadores_flujo': indexer.contadores_flujo(a.base, hoja, est or None, txt, ed, cl),
                    'contadores_clase': indexer.contadores_clase(a.base, hoja, est or None, txt, ed, fl)}
        if ruta == '/api/misiones': return a.misiones(q.get('q'), q.get('clase') or None, q.get('expansion') or None, q.get('flujo') or None)
        if ruta == '/api/hoja_celdas': return a.hoja_celdas(q['hoja'])
        if ruta == '/api/celda': return a.celda(int(q['id']))
        if ruta == '/api/tarea': return a.tarea.ver(int(q.get('desde') or 0))
        if ruta == '/api/borradores': return self.leer_borradores()
        if ruta == '/api/arranque': return {'arranque': dict(a.arranque, ocupada=a.motivo_base()), 'indice_estado': a.vigencia, 'aviso': a.aviso}
        raise KeyError(ruta)

    def post(self, ruta, b):
        a = self.app
        if ruta == '/api/preview': return a.preview(int(b['id']), b['texto'], b.get('genero', 'masc'), bool(b.get('reflujo', True)))
        if ruta == '/api/guardar': return a.guardar(int(b['id']), b['texto'])
        if ruta == '/api/config': a.cfg.actualizar(b); return a.cfg.publico()
        if ruta == '/api/borrar_token': a.cfg.borrar_token(); return a.cfg.publico()
        if ruta == '/api/sync': a.tarea_sync(); return {'ok': True}
        if ruta == '/api/extraer': a.tarea_extraer(b.get('ruta') or None); return {'ok': True}
        if ruta == '/api/indexar': a.tarea_indexar(bool(b.get('forzar'))); return {'ok': True}
        if ruta == '/api/tarea_cancelar': return a.tarea_cancelar()
        if ruta == '/api/abrir_registros': return a.abrir_registros()
        if ruta == '/api/generar': a.tarea_generar(b.get('destino') or None, b.get('relajar', 'auto'), bool(b.get('validar', True))); return {'ok': True}
        if ruta == '/api/flujo_marcar': return a.flujo_marcar(b)
        if ruta == '/api/flujo_exportar': return a.flujo_exportar(b.get('destino') or None)
        if ruta == '/api/flujo_importar': return a.flujo_importar(b.get('contenido'), b.get('reemplazar'), b.get('ruta'))
        if ruta == '/api/suavizar_previa': return a.suavizar_previa(b)
        if ruta == '/api/suavizar_aplicar': return a.suavizar_aplicar(b)
        if ruta == '/api/sin_saltos_texto': return a.sin_saltos_texto(int(b['id']), b['texto'], bool(b.get('resuavizar')))
        if ruta == '/api/suavizar_deshacer': return a.suavizar_deshacer()
        if ruta == '/api/buscar': return a.buscar(b)
        if ruta == '/api/buscar_exportar': return a.exportar_busqueda(b)
        if ruta == '/api/reemplazar': return a.reemplazar(b)
        if ruta == '/api/exportar': return a.exportar(b.get('destino') or None)
        if ruta == '/api/abrir_navegador':
            if self.url_navegador: self.url_navegador()
            else: import webbrowser; webbrowser.open(self.url)
            return {'ok': True}
        if ruta == '/api/borrador': return self.guardar_borrador(b)
        if ruta == '/api/borrador_borrar': return self.borrar_borrador(b)
        if ruta == '/api/reabrir': return self.reabrir()
        if ruta == '/api/latido': self.registrar_latido(); return {'ok': True}
        if ruta == '/api/cierre': self.pedir_cierre(); return {'ok': True}        # la UI se descarga (cerrar ventana o F5): el vigilante decide pasado el plazo
        if ruta == '/api/salir': self.salir.set(); return {'ok': True}
        raise KeyError(ruta)
