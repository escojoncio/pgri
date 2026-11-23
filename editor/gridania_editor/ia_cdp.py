"""Controla la mini ventana de Gemini por el protocolo de depuracion de Chromium (CDP) para escribir el prompt y enviarlo.
Cliente WebSocket minimo propio (solo stdlib): handshake, trama de texto enmascarada, lectura de tramas. Solo 127.0.0.1."""
import base64, hashlib, json, logging, os, socket, struct, time, urllib.request

log = logging.getLogger('gridania')
GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
JS_EDITOR = ("(()=>{const e=document.querySelector('rich-textarea .ql-editor, div.ql-editor[contenteditable=\"true\"], div[role=\"textbox\"][contenteditable=\"true\"]');"
             "if(!e)return false;e.focus();return true})()")
JS_ENVIAR = ("(()=>{const b=document.querySelector('button.send-button, button[aria-label*=\"Enviar\"], button[aria-label*=\"Send\"]');"
             "if(b&&!b.disabled){b.click();return true}return false})()")


class WS:
    def __init__(self, url, timeout=30):
        assert url.startswith('ws://')
        host, _, ruta = url[5:].partition('/')
        h, _, p = host.partition(':')
        self.s = socket.create_connection((h, int(p or 80)), timeout=timeout)
        clave = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(('GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n' % (ruta, host, clave)).encode())
        cab = b''
        while b'\r\n\r\n' not in cab:
            c = self.s.recv(4096)
            if not c: raise ConnectionError('handshake WebSocket cerrado')
            cab += c
        if b' 101 ' not in cab.split(b'\r\n', 1)[0]: raise ConnectionError('handshake WebSocket rechazado: %r' % cab[:80])
        esperado = base64.b64encode(hashlib.sha1((clave + GUID).encode()).digest())
        if esperado not in cab: raise ConnectionError('Sec-WebSocket-Accept invalido')
        self.buf = cab.split(b'\r\n\r\n', 1)[1]
        self.id = 0

    def _leer(self, n):
        while len(self.buf) < n:
            c = self.s.recv(65536)
            if not c: raise ConnectionError('WebSocket cerrado')
            self.buf += c
        r, self.buf = self.buf[:n], self.buf[n:]
        return r

    def enviar(self, texto):
        d = texto.encode('utf-8'); n = len(d); m = os.urandom(4)
        cab = b'\x81' + (bytes([0x80 | n]) if n < 126 else b'\xfe' + struct.pack('>H', n) if n < 65536 else b'\xff' + struct.pack('>Q', n))
        self.s.sendall(cab + m + bytes(b ^ m[i % 4] for i, b in enumerate(d)))

    def recibir(self):
        partes = []
        while True:
            b0, b1 = self._leer(2)
            n = b1 & 0x7f
            if n == 126: n = struct.unpack('>H', self._leer(2))[0]
            elif n == 127: n = struct.unpack('>Q', self._leer(8))[0]
            if b1 & 0x80: m = self._leer(4); d = bytes(b ^ m[i % 4] for i, b in enumerate(self._leer(n)))
            else: d = self._leer(n)
            op = b0 & 0x0f
            if op == 8: raise ConnectionError('WebSocket cerrado por el navegador')
            if op in (9, 10): continue
            partes.append(d)
            if b0 & 0x80: return b''.join(partes).decode('utf-8')

    def llamar(self, metodo, params=None, espera=30):
        self.id += 1; mi = self.id
        self.enviar(json.dumps({'id': mi, 'method': metodo, 'params': params or {}}))
        fin = time.time() + espera
        while time.time() < fin:
            r = json.loads(self.recibir())
            if r.get('id') == mi:
                if 'error' in r: raise RuntimeError('%s: %s' % (metodo, r['error']))
                return r.get('result', {})
        raise TimeoutError(metodo)

    def cerrar(self):
        try: self.s.close()
        except OSError: pass


def _json(puerto, ruta, espera=2):
    with urllib.request.urlopen('http://127.0.0.1:%d/%s' % (puerto, ruta), timeout=espera) as r: return json.loads(r.read().decode())


def responde(puerto):
    try: _json(puerto, 'json/version', 1); return True
    except Exception: return False


def _pagina(puerto, espera):
    fin = time.time() + espera
    while time.time() < fin:
        try:
            for t in _json(puerto, 'json'):
                if t.get('type') == 'page' and t.get('webSocketDebuggerUrl'): return t
        except Exception: pass
        time.sleep(0.5)
    return None


def escribir_y_enviar(puerto, texto, enviar=True, url=None, espera=60, dormir=time.sleep):
    """escribe `texto` en el cuadro de Gemini (y lo envia). url: si se da, navega antes (chat nuevo). -> True si lo dejo escrito."""
    t = _pagina(puerto, 40)
    if not t: log.warning('IA: no aparece la pagina de Gemini'); return False
    ws = WS(t['webSocketDebuggerUrl'])
    try:
        if url:
            ws.llamar('Page.navigate', {'url': url}); dormir(2.5)
        fin = time.time() + espera; listo = False
        while time.time() < fin:
            r = ws.llamar('Runtime.evaluate', {'expression': JS_EDITOR, 'returnByValue': True})
            if r.get('result', {}).get('value') is True: listo = True; break
            dormir(0.5)
        if not listo: log.warning('IA: no aparece el cuadro de texto de Gemini (sesion no iniciada?)'); return False
        ws.llamar('Input.insertText', {'text': texto})
        if enviar:
            dormir(0.8)
            r = ws.llamar('Runtime.evaluate', {'expression': JS_ENVIAR, 'returnByValue': True})
            if r.get('result', {}).get('value') is not True:
                for tipo in ('keyDown', 'keyUp'):
                    ws.llamar('Input.dispatchKeyEvent', {'type': tipo, 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13, 'text': '\r'})
        return True
    finally: ws.cerrar()
