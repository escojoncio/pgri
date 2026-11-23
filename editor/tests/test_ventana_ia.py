from gridania_editor import ventana


def test_lanzar_ia_usa_perfil_propio_y_ventana_pequena(tmp_path):
    llamadas = []
    class P:
        pid = 1
    p = ventana.lanzar_ia(str(tmp_path), buscar=lambda: 'msedge.exe', popen=lambda cmd, **kw: (llamadas.append(cmd), P())[1])
    assert p is not None
    cmd = llamadas[0]
    assert '--app=' + ventana.URL_IA in cmd
    assert '--user-data-dir=%s' % (tmp_path / 'perfil-ia') in cmd
    assert '--window-size=540,860' in cmd
    assert (tmp_path / 'perfil-ia').is_dir()


def test_lanzar_ia_sin_navegador_no_abre_nada(tmp_path):
    assert ventana.lanzar_ia(str(tmp_path), buscar=lambda: None, popen=lambda *a, **k: 1 / 0) is None


import base64, hashlib, json, socket, struct, threading
from gridania_editor import ia_cdp


def _servidor_cdp(recibidos):
    """CDP falso: handshake WebSocket, responde a cada comando; el editor 'existe' y el boton enviar tambien."""
    srv = socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(1)
    def leer(c, n):
        b = b''
        while len(b) < n: b += c.recv(n - len(b))
        return b
    def run():
        c, _ = srv.accept(); cab = b''
        while b'\r\n\r\n' not in cab: cab += c.recv(4096)
        clave = [l.split(b': ')[1] for l in cab.split(b'\r\n') if l.lower().startswith(b'sec-websocket-key')][0]
        acc = base64.b64encode(hashlib.sha1(clave + ia_cdp.GUID.encode()).digest())
        c.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + acc + b'\r\n\r\n')
        while True:
            try: b0, b1 = leer(c, 2)
            except Exception: return
            n = b1 & 0x7f
            if n == 126: n = struct.unpack('>H', leer(c, 2))[0]
            m = leer(c, 4); d = bytes(x ^ m[i % 4] for i, x in enumerate(leer(c, n)))
            msg = json.loads(d); recibidos.append(msg)
            r = json.dumps({'id': msg['id'], 'result': {'result': {'value': True}}}).encode()
            c.sendall(b'\x81' + (bytes([len(r)]) if len(r) < 126 else b'\x7e' + struct.pack('>H', len(r))) + r)
    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1]


def test_ws_y_escribir_y_enviar(monkeypatch):
    recibidos = []; puerto = _servidor_cdp(recibidos)
    monkeypatch.setattr(ia_cdp, '_pagina', lambda p, e: {'webSocketDebuggerUrl': 'ws://127.0.0.1:%d/devtools/page/x' % puerto})
    texto = 'Traduce esto al castellano:\n\n' + 'こんにちは ' * 40         # > 125 bytes: trama con longitud extendida
    assert ia_cdp.escribir_y_enviar(1, texto, True, dormir=lambda s: None) is True
    ins = [m for m in recibidos if m['method'] == 'Input.insertText']
    assert ins and ins[0]['params']['text'] == texto
    assert any(m['method'] == 'Runtime.evaluate' and 'send-button' in m['params']['expression'] for m in recibidos)


# ---- modo «una linea (como el frances)»
import re, types
from gridania_editor import celda as celda_mod


def _motor_falso():
    m = celda_mod.Motor.__new__(celda_mod.Motor)
    m.R = types.SimpleNamespace(S=types.SimpleNamespace(MARCA=''), G=types.SimpleNamespace(NL_RE=re.compile(r'<NewLine(?:#[0-9]+)?>\Z')))
    return m


def test_palabras_no_parte_tokens():
    m = _motor_falso()
    assert m._palabras('uno <If(1 2)>dos<MacroEnd> tres') == ['uno', '<If(1 2)>dos<MacroEnd>', 'tres']


def test_unida_reparte_y_marca_los_newline():
    m = _motor_falso()
    c = types.SimpleNamespace(seps=['<NewLine>', '<NewLine#2>'], ch=['aaaa', 'bbbb', 'cccc'])
    es = m._unida(c, 'uno dos tres cuatro cinco seis')
    assert len(es) == 3 and all(x.strip('') for x in es)
    assert es[0][0] != '' and es[1][0] == '' and es[2][0] == ''
    assert ' '.join(x.strip('') for x in es) == 'uno dos tres cuatro cinco seis'


def test_unida_pocas_palabras_da_error_claro():
    m = _motor_falso()
    c = types.SimpleNamespace(seps=['<NewLine>', '<NewLine>'], ch=['a', 'b', 'c'])
    try: m._unida(c, 'solo dos'); assert False
    except ValueError as x: assert 'al menos una palabra' in str(x)


def test_comprobaciones_ignoran_la_marca():
    m = _motor_falso(); vistos = []
    m.R.AG = types.SimpleNamespace(revisar_fila=lambda e, ch, seps, tok, text: vistos.append(e['es']) or [])
    m.R.LAT = types.SimpleNamespace(detectar=lambda es, text: [])
    m.R.SIMB = types.SimpleNamespace(objetivas_puerta=lambda ch, es: [])
    m._glosario = lambda *a: None; m._say = lambda *a: None
    c = types.SimpleNamespace(row=1, sub=None, col=0, h='x', tipo='simple', ch=['a', 'b'], seps=['<NewLine>'], tok='', text='')
    m._comprobaciones(c, ['hola', 'mundo'], [], [])
    assert vistos == [['hola', 'mundo']]
