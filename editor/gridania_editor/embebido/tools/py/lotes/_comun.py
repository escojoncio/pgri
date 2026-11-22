"""Utilidades comunes de tools/py/lotes (importado por los demas scripts; no se ejecuta solo).
Rutas relativas al repo: RAIZ = raiz del repo; se anade tools/py a sys.path (los scripts corren con `python3 -I`)."""
import os, sys, re, json, unicodedata
AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.environ.get('LOTES_RAIZ') or os.path.join(AQUI, '..', '..', '..'))  # LOTES_RAIZ: raiz alternativa (pruebas)
sys.path.insert(0, os.path.join(RAIZ, 'tools', 'py'))
import segmentar as G, construir_dat as C

TAM_MAX = 400          # una cadena de mas de 400 caracteres no entra en lotes (queda aparte)
URL_RE = r'https?://|www\.|^[A-Za-z]:\\|^/[A-Za-z_]|[\\/][\w.-]+\.\w{2,4}$'

def txt(r):
    """texto plano del registro de segmentar.preparar (trozos unidos; cadena tokenizada si es compleja)"""
    return ''.join(r['ja']) if r['tipo'] == 'simple' else r['ja']

def txt_completo(r):
    """como txt pero reinsertando los separadores `sep` (color/icono/numero) entre trozos"""
    if r['tipo'] != 'simple': return r['ja']
    sp = r.get('sep', []); o = []
    for i, t in enumerate(r['ja']):
        o.append(t)
        if i < len(sp): o.append(sp[i])
    return ''.join(o)

def letras_cjk(t):
    return any(unicodedata.category(c).startswith('L') and G.tiene_cjk(c) for c in t)

def _plano(t):
    return re.sub(r'<[^<>]*>|\{0x[0-9A-Fa-f]{2}[^}]*\}', '', t).replace('<<', '<').strip(' 　')

def motivo(r):
    """None si la fila se traduce; 'clave/identificador' o 'URL/ruta/comando' si no tiene letras CJK y lo parece"""
    t = txt(r)
    if letras_cjk(t): return None
    p = _plano(t)
    if C.parece_clave(p): return 'clave/identificador'
    if re.search(URL_RE, p): return 'URL/ruta/comando'
    return None

def extra_sin_cjk(hoja, r):
    """fila sin CJK que parece clave/URL (se anota en excluidas, no se traduce) -> tupla o None"""
    t = txt(r); p = re.sub(r'<[^<>]*>', '', t).replace('<<', '<').strip(' 　')
    if C.parece_clave(p): return (hoja, r['row'], r['sub'], r['col'], 'clave/identificador (sin CJK)', t)
    if re.search(URL_RE, p): return (hoja, r['row'], r['sub'], r['col'], 'URL/ruta/comando (sin CJK)', t)
    return None

def hechas(hoja):
    """claves (row,sub,col) ya presentes en traducciones/<hoja>.jsonl"""
    done = set(); p = os.path.join(RAIZ, 'traducciones', hoja + '.jsonl')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            for l in f:
                if l.strip():
                    j = json.loads(l); done.add((j['row'], j['sub'], j['col']))
    return done

def clave(r): return (r['row'], r['sub'], r['col'])
def orden(r): return (r['hoja'], r['row'], -1 if r['sub'] is None else r['sub'], r['col'])

def escribir_lote(ruta, sel):
    with open(ruta, 'w', encoding='utf-8', newline='\n') as f:
        for r in sel: f.write(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n')

def escribir_excluidas(ruta, excl):
    with open(ruta, 'w', encoding='utf-8', newline='\n') as f:
        for h, r, s, c, m, t in excl:
            f.write('%s\t%d\t%s\t%d\t%s\t%s\n' % (h, r, '' if s is None else s, c, m, json.dumps(t, ensure_ascii=False)))

def leer_lote(ruta):
    with open(ruta, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]

def carpeta_salida(s):
    s = s or '/tmp'; os.makedirs(s, exist_ok=True); return s
