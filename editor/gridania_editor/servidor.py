"""Servidor HTTP local (127.0.0.1) con API JSON y la interfaz (ui/index.html). Protegido con una clave por ejecucion (cabecera X-K) y comprobacion de Host."""
import json, os, secrets, sys, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import indexer


def dir_ui():
    base = getattr(sys, '_MEIPASS', None)
    cand = [os.path.join(base, 'gridania_editor', 'ui')] if base else []
    cand.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui'))
    for c in cand:
        if os.path.isdir(c): return c
    return cand[-1]


class Servidor(object):
    def __init__(self, app, puerto=0):
        self.app = app; self.clave = secrets.token_urlsafe(16); self.salir = threading.Event()
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
            def _auth(self):
                return self.headers.get('X-K') == servidor.clave
            def do_GET(self):
                if not self._host_ok(): return self._err(403, 'host no permitido')
                u = urllib.parse.urlparse(self.path); q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                if u.path in ('/', '/index.html'):
                    try: html = open(os.path.join(dir_ui(), 'index.html'), encoding='utf-8').read().replace('__CLAVE__', servidor.clave)
                    except OSError: return self._err(500, 'falta ui/index.html')
                    b = html.encode('utf-8'); self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(b); return
                if not u.path.startswith('/api/'): return self._err(404, 'no existe')
                if not self._auth(): return self._err(401, 'clave invalida')
                try: self._json(servidor.get(u.path, q))
                except KeyError as x: self._err(404, x)
                except (ValueError, RuntimeError) as x: self._err(400, x)
                except Exception as x: self._err(500, '%s: %s' % (type(x).__name__, x))
            def do_POST(self):
                if not self._host_ok(): return self._err(403, 'host no permitido')
                if not self._auth(): return self._err(401, 'clave invalida')
                u = urllib.parse.urlparse(self.path)
                try:
                    n = int(self.headers.get('Content-Length') or 0); cuerpo = json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
                    self._json(servidor.post(u.path, cuerpo))
                except KeyError as x: self._err(404, x)
                except (ValueError, RuntimeError) as x: self._err(400, x)
                except Exception as x: self._err(500, '%s: %s' % (type(x).__name__, x))
        self.httpd = ThreadingHTTPServer(('127.0.0.1', puerto), H)
        self.puerto = self.httpd.server_address[1]
        self.hilo = None

    @property
    def url(self): return 'http://127.0.0.1:%d/' % self.puerto

    def arrancar(self):
        self.hilo = threading.Thread(target=self.httpd.serve_forever, daemon=True); self.hilo.start()

    def parar(self):
        self.httpd.shutdown(); self.httpd.server_close()

    # ------------------------------------------------------------ rutas
    def get(self, ruta, q):
        a = self.app
        if ruta == '/api/estado': return a.estado()
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
        raise KeyError(ruta)

    def post(self, ruta, b):
        a = self.app
        if ruta == '/api/preview': return a.preview(int(b['id']), b['texto'], b.get('genero', 'masc'), bool(b.get('reflujo', True)))
        if ruta == '/api/guardar': return a.guardar(int(b['id']), b['texto'])
        if ruta == '/api/config': a.cfg.actualizar(b); return a.cfg.publico()
        if ruta == '/api/borrar_token': a.cfg.borrar_token(); return a.cfg.publico()
        if ruta == '/api/sync': a.tarea_sync(); return {'ok': True}
        if ruta == '/api/extraer': a.tarea_extraer(b.get('ruta') or None); return {'ok': True}
        if ruta == '/api/indexar': a.tarea_indexar(); return {'ok': True}
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
        if ruta == '/api/salir': self.salir.set(); return {'ok': True}
        raise KeyError(ruta)
