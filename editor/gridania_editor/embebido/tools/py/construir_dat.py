#!/usr/bin/env -S python3 -I
"""traducciones/**/*.jsonl -> translations.dat, con proteccion total de marcadores.
Por cada linea {"row","sub","col","es","estado","h"}:
  japones = textos/ja/<hoja>.jsonl (row,sub,col)  ->  source = tokenizacion de los bytes del juego (extract_text/sestring)
  target  = recomponer(separadores, es)  (cadena simple: `es` es lista de trozos; separadores = NewLine, ColorType, EdgeColorType, Icon2, Num, Kilo)  |  es  (cadena compleja: tokenizada;
            tambien se admite para filas que solo son simples por color/icono/numero, ya traducidas asi)
Pasa el FILTRO (rechazos en revisar.csv) y se escribe con netjson.entry_line + build_blob.escribir_blob (formato validado).
FILTRO: estado (dudosa no entra), fila inexistente, hash h obsoleto, tipo de `es` (lista/cadena), nº de trozos, trozo vacio,
marcador escrito en un trozo, caracteres de control, CJK sin traducir, target vacio, '<' mal escapado, multiconjunto y ORDEN de tokens
distintos del source, literales protegidos (comandos de chat, URLs, macros `<<t>`, {n} %s %d; texto tras <Raw>; literal de
<Sheet|SheetSub|Fixed><Run>; glifos PUA U+E000-F8FF; claves/identificadores devueltos identicos), subfilas/variant!=1, duplicados (hoja,rowId,field), simulacion de la Fase A de ExdPatcher.
Uso: python3 -I construir_dat.py --game DIR_0a0000 [--sheet HOJA] [--out out/translations.dat] [--revisar out/revisar.csv] [--dry-run] [--incluir-corpus] [--root RAIZ]
--incluir-corpus: por defecto las filas con "origen":"corpus" NO entran (motivo CORPUS_HEREDADO en revisar.csv); solo entran los origen de la lista blanca ORIGENES_VALIDOS (fr-ja-retrad, reutilizada, fr-media, sesion, previo-ja); sin origen u otro valor -> ORIGEN_DESCONOCIDO.
MARCA «salto -> espacio» (U+E0F0 justo tras un NewLine; ver sestring.MARCA y docs/referencia-tecnica.md): se admite en `es` (primer caracter de un trozo i>=1 tras NewLine, o en cadenas complejas tras un token NewLine); nunca llega al juego.
--game: carpeta con 0a0000.win32.* (solo se lee el EXH de cada hoja: paginas, columnas String, variant). Actualiza PROGRESO.csv (no con --dry-run)."""
import sys, os, re, csv, json, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sestring as S, sestring_flat as F, campos, segmentar as G
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lotes'))
import normalizar_signos_japoneses as _NSJ
from netjson import entry_line
from build_blob import escribir_blob

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
ESTADOS = ('traducida', 'revisada', 'dudosa')
# Lista blanca de `origen`: cualquier otro valor (o ausencia) se rechaza (ORIGEN_DESCONOCIDO); `corpus` (ingles heredado) se rechaza aparte (CORPUS_HEREDADO).
ORIGENES_VALIDOS = ('fr-ja-retrad', 'reutilizada', 'fr-media', 'sesion', 'previo-ja')

class Rechazo(Exception):
    def __init__(self, motivo, detalle=''):
        Exception.__init__(self, motivo, detalle); self.motivo = motivo; self.detalle = detalle

def _abre_macros(tok_bytes):
    """nombres de token del source que ABREN macro con cuerpo (cierran con <MacroEnd>): bytes `00 kind len`, igual que sestring.tokenize"""
    return {t for t, b in S.tokenize(S.parse(tok_bytes))[1] if len(b) == 3 and b[0] == 0}

def _sin_tokens(t, abre=None, fundir=True):
    if not fundir: pass   # texto de las ramas <Run> cuenta (macro-celdas cuyo unico texto va dentro del <If>)
    elif '<If>' in t and abre is not None:   # emparejado por profundidad con los openers del source: solo se funde el bloque <If> hasta SU <MacroEnd>; el texto entre bloques si cuenta
        ps = _NSJ.TOK.split(t); out = []; i = 0
        while i < len(ps):
            if i % 2 and ps[i] == '<If>':
                d = 0; fin = len(ps) - 1
                for k in range(i, len(ps), 2):
                    if ps[k] in abre: d += 1
                    elif _NSJ._ME_RE.fullmatch(ps[k]):
                        d -= 1
                        if d == 0: fin = k; break
                i = fin + 1; continue
            out.append(ps[i]); i += 1
        t = ''.join(out)
    elif '<If>' in t: t = ''.join(p for i, p in enumerate(_NSJ.partes(t)) if i % 2 == 0 or not p.startswith('<If>'))   # bloque macro crudo <If>..<MacroEnd#N>: literales de rama (bytes) no cuentan como texto del es
    out = t
    for p, tk in sorted(((p, tk) for tk, p in S._atoms(t)), reverse=True): out = out[:p] + out[p + len(tk):]
    return out.replace('<<', '<')

def filtro_tokens(source, target):
    """'<' mal escapado, multiconjunto y orden de tokens iguales al source. Lanza Rechazo."""
    v = S.validate(source, target)
    stray = [m for k, m in v if k == 'StrayDelimiter']
    if stray: raise Rechazo('ESCAPE', '; '.join(stray))
    if not S.has_reserved(target):
        sa, ta = S.filtrar_colores_propios([t for t, _ in S._atoms(source)], [t for t, _ in S._atoms(target)])   # colores propios del es (<UIColor:..>): sin los ColorType/EdgeColorType del source
        ef = S.relax_newlines(source, target)   # NewLine EXTRA admitido (parcheador pgri): se comparan los tokens efectivos
        if ef is not None: ta = ef
        if collections.Counter(sa) != collections.Counter(ta):
            d = collections.Counter(sa); d.subtract(collections.Counter(ta))
            raise Rechazo('TOKENS', 'multiconjunto: ' + ' '.join('%s%+d' % (t, n) for t, n in d.items() if n))
        if sa != ta: raise Rechazo('TOKENS', 'orden distinto')
    if v: raise Rechazo('TOKENS', '; '.join('[%s] %s' % x for x in v))

# ---- proteccion de literales que no se traducen (comandos, macros de chat, URLs, Raw, Run de Sheet, glifos PUA, claves) ----
_CENT = '\ufffc'   # centinela: sustituye cada token <...> para que los regex de texto no crucen tokens
CMD_RE = re.compile(r'(?<![\w/.<\ufffc])/[A-Za-z]{2,}[A-Za-z0-9_]*|(?<=[\u3000-\u9fff\uff00-\uffef])/[a-z]{2,}[A-Za-z0-9_]*')   # \w: tampoco tras letras acentuadas (si/no); 2.ª rama: comando en minusculas pegado a japones (`は/petsize`), no `品質/HQ`
URL_RE = re.compile(r'(?:https?|ftp)://[\x21-\x3b\x3d\x3f-\x7e]*[A-Za-z0-9_~/#=%-]|www\.[\x21-\x3b\x3d\x3f-\x7e]*[A-Za-z0-9_~/#=%-]')   # solo ASCII y sin puntuacion final (`)`, `.`, `»`): la URL no arrastra el japones/anchura completa pegado
CHATMAC_RE = re.compile(r'<<[^<>\ufffc]+>')
PLACEH_RE = re.compile(r'\{[0-9]+\}|%[sd]')
PUA_RE = re.compile('[\ue000-\uf8ff]')
CLAVE_RE = re.compile(r'[_A-Za-z0-9.\-]+\Z')
FECHA_RE = re.compile(r'[0-9]+[/:][0-9]+')

def _plano(t):
    """cadena tokenizada con cada token sustituido por un centinela ('<<' queda intacto); <NewLine> pasa a '\\n' (un comando puede seguir a un salto)"""
    out = []; prev = 0
    for tk, p in S._atoms(t): out.append(t[prev:p]); out.append('\n' if S._bn(tk) == 'NewLine' else _CENT); prev = p + len(tk)
    out.append(t[prev:]); return ''.join(out)

def literales_protegidos(t):
    """-> Counter de comandos de chat, URLs, macros de chat `<<x>`, placeholders {n} %s %d (sobre la forma tokenizada)"""
    p = _plano(t); c = collections.Counter()
    for rx in (CMD_RE, URL_RE, CHATMAC_RE, PLACEH_RE): c.update(rx.findall(p))
    return c

def _bn(tk): return S._bn(tk)

def textos_raw(t):
    """-> {token Raw: texto que le sigue hasta el siguiente token}"""
    at = S._atoms(t); res = {}
    for i, (tk, p) in enumerate(at):
        if _bn(tk) == 'Raw': res[tk] = t[p + len(tk):(at[i + 1][1] if i + 1 < len(at) else len(t))]
    return res

_RAW_LARGO_JA = re.compile('[\x21-\x7e]\u300c\\Z'); _RAW_LARGO_ES = re.compile('[\x21-\x7e]\u00ab\\Z')

def _raw_largo_comilla(ja, es):
    """Unica variacion admitida en un literal tras <Raw>: byte de longitud de un run 0xFF (ASCII) + comilla, `3「` -> `<L>«` (CmnDefRelicWeapon050Trade_00221 row 8: comillas
    españolas dentro de la macro de objetos; el byte L lo recalcula a mano tools/py/lotes/test_relic050_macro.py, que verifica el payload)."""
    return bool(_RAW_LARGO_JA.match(ja) and _RAW_LARGO_ES.match(es))

def literales_run(t):
    """-> {macro: literal del primer <Run>..<RunEnd> si <Sheet|SheetSub|Fixed> va seguido (sin texto) de <Run>}"""
    at = S._atoms(t); res = {}
    for i, (tk, p) in enumerate(at):
        if _bn(tk) not in ('Sheet', 'SheetSub', 'Fixed') or i + 1 >= len(at): continue
        r, rp = at[i + 1]
        if _bn(r) != 'Run' or rp != p + len(tk): continue
        depth = 0; fin = len(t)
        for k, q in at[i + 1:]:
            if _bn(k) == 'Run': depth += 1
            elif _bn(k) == 'RunEnd':
                depth -= 1
                if depth == 0: fin = q; break
        res[tk] = t[rp + len(r):fin]
    return res

def parece_clave(t):
    """ja sin CJK, solo [_A-Za-z0-9.-], y con '_' (AETHERYTE_TEXT_SGL, _rsv_...) o con '-'/'.' + digito + sin minusculas (GA-100).
    Palabras o siglas con guion/punto (Sylph-Friend, F.A.T.E., a.m.) NO cuentan: son texto visible y se traducen."""
    if CLAVE_RE.match(t) is None: return False
    if '_' in t: return True
    return re.search(r'[.\-]', t) is not None and re.search(r'[0-9]', t) is not None and re.search(r'[a-z]', t) is None

def problemas_protegidos(tok, target):
    """-> lista de (motivo, detalle); vacia = ok. Motivos: COMANDO, RAW, RUN_LITERAL, GLIFO, CLAVE"""
    out = []
    a, b = literales_protegidos(tok), literales_protegidos(target)
    if a != b:
        d = a - b; e = b - a
        out.append(('COMANDO', 'perdidos [%s] inventados [%s]' % (' '.join(sorted(d.elements())), ' '.join(sorted(e.elements())))))
    ra, rb = textos_raw(tok), textos_raw(target)
    mal = [k for k in ra if k in rb and ra[k] != rb[k] and not _raw_largo_comilla(ra[k], rb[k])]
    if mal: out.append(('RAW', '; '.join('%s: %r -> %r' % (k, ra[k], rb[k]) for k in mal)))
    la, lb = literales_run(tok), literales_run(target)
    mal = [k for k in la if k in lb and la[k] != lb[k]]
    if mal: out.append(('RUN_LITERAL', '; '.join('%s: %r -> %r' % (k, la[k], lb[k]) for k in mal)))
    pa, pb = collections.Counter(PUA_RE.findall(tok)), collections.Counter(PUA_RE.findall(target))
    if pa != pb:
        out.append(('GLIFO', 'perdidos [%s] inventados [%s]' % (' '.join('U+%04X' % ord(c) for c in (pa - pb).elements()), ' '.join('U+%04X' % ord(c) for c in (pb - pa).elements()))))
    if parece_clave(tok) and tok != target: out.append(('CLAVE', 'clave/identificador cambiado: %r -> %r' % (tok, target)))
    return out

def avisos_cadena(tok, target):
    """-> lista de (motivo, detalle) NO bloqueantes: digitos o fechas del japones ausentes en el espanol"""
    import unicodedata
    n = lambda t: unicodedata.normalize('NFKC', _sin_tokens(t.replace(S.MARCA, '')))
    ja, es = n(tok), n(target); out = []
    da, db = collections.Counter(re.findall(r'[0-9]+', ja)), collections.Counter(re.findall(r'[0-9]+', es))
    if da - db: out.append(('AVISO_DIGITOS', 'ausentes en es: ' + ' '.join(sorted((da - db).elements()))))
    fa, fb = collections.Counter(FECHA_RE.findall(ja)), collections.Counter(FECHA_RE.findall(es))
    if fa - fb: out.append(('AVISO_FECHA', 'ausentes en es: ' + ' '.join(sorted((fa - fb).elements()))))
    return out

def filtro_protegidos(tok, target):
    """Lanza Rechazo si el espanol cambia un literal protegido respecto del japones (ver problemas_protegidos)."""
    p = problemas_protegidos(tok, target)
    if p: raise Rechazo(p[0][0], '; '.join('%s: %s' % x for x in p) if len(p) > 1 else p[0][1])

def evaluar_cadena(text, raw, e):
    """-> (source, target, via). Lanza Rechazo."""
    estado = e.get('estado')
    if estado not in ESTADOS: raise Rechazo('ESTADO', repr(estado))
    if estado == 'dudosa': raise Rechazo('DUDOSA', 'no entra en el .dat')
    if e.get('h') != G.hash_ja(text): raise Rechazo('HASH_OBSOLETO', 'h=%r actual=%s' % (e.get('h'), G.hash_ja(text)))
    b = G.bytes_ja(text, raw); tok = S.tokenize_raw(b)
    es = e.get('es')
    if isinstance(es, (list, str)): es = _NSJ.normalizar(es)   # red de seguridad: signos japoneses/anchura completa -> UTF-8 espanol (norma 2026-11-05)
    tipo = G.clasificar(tok, bool(raw))
    # compatibilidad: una cadena que solo es simple por la ampliacion (color/icono/numero) y ya traducida como cadena tokenizada
    # (`es` string) sigue por la via compleja, con su filtro completo de tokens: no cambia ni h ni el resultado de las filas existentes
    # colores propios (`<UIColor:f201f6>..<UIColorEnd>`, docs/colores-propios-es.md): solo en `es` string tokenizado (via compleja), aunque el ja sea simple
    if tipo == 'simple' and isinstance(es, str) and (G.clasificar(tok, bool(raw), solo_nl=True) == 'complejo' or S.contiene_color_propio(es)): tipo = 'complejo'
    if tipo == 'simple':
        ja, seps = G.trocear(tok)
        if not isinstance(es, list) or not all(isinstance(x, str) for x in es): raise Rechazo('TIPO_ES', 'cadena simple: `es` debe ser lista de strings')
        if len(es) != len(ja): raise Rechazo('N_TROZOS', 'esperados %d, recibidos %d' % (len(ja), len(es)))
        for i, (j, t) in enumerate(zip(ja, es)):
            if G.hay_control(t): raise Rechazo('CONTROL', 'trozo %d' % i)
            if S.contiene_color_propio(t): raise Rechazo('COLOR_PROPIO_EN_TROZO', 'trozo %d: los colores propios (<UIColor:..>) solo van en `es` como cadena tokenizada, no en una lista de trozos' % i)
            # marca «salto -> espacio» (U+E0F0, ver sestring.MARCA): solo como PRIMER caracter de un trozo i>=1 cuyo separador previo es un NewLine, una vez
            if S.MARCA in t and (t.count(S.MARCA) != 1 or not t.startswith(S.MARCA) or i == 0 or not G.NL_RE.match(seps[i - 1])): raise Rechazo('MARCA_INVALIDA', 'trozo %d' % i)
            # un marcador solo se admite si es un literal del propio trozo japones (macros de chat `<t>`, `<attack1>`: el constructor los escapa a `<<t>`)
            if G.GEN_TOK_RE.search(t):   # macro de genero: cada trozo ha de llevar macros COMPLETAS (ramas literales no vacias, sin anidar); no puede cruzar trozos
                marc, mac, why = S.split_gender(G.escapar(t))
                if why or not mac or S.has_reserved(marc): raise Rechazo('GENERO_EN_TROZO', 'trozo %d: %s' % (i, why or 'macro <Gender> incompleta'))
            nonl = lambda x: [m for m in G.MARCADOR_RE.findall(x) if not G.NL_TOK_RE.match(m) and not G.GEN_TOK_RE.match(m)]   # <NewLine> en un trozo no cuenta (lo juzga filtro_tokens); la macro de genero ya se juzgo arriba
            if collections.Counter(nonl(t)) - collections.Counter(nonl(j)): raise Rechazo('MARCADOR_EN_TROZO', 'trozo %d' % i)
            if not G.vacio_permitido(j) and not t.strip(): raise Rechazo('TROZO_VACIO', 'trozo %d' % i)
            if G.tiene_cjk(t) and not G.es_simbolos(j): raise Rechazo('CJK', 'trozo %d' % i)
        if not ''.join(es).replace(S.MARCA, '').strip(): raise Rechazo('TARGET_VACIO')
        target = S.renumerar_newlines(G.recomponer(seps, es), tok)   # NewLine extra en trozos: los del source conservan su nombre, los extra N+1... (pgri)
    else:
        if not isinstance(es, str): raise Rechazo('TIPO_ES', 'cadena compleja: `es` debe ser string tokenizado')
        target = S.renumerar_newlines(es, tok)
        plano = _sin_tokens(target, _abre_macros(b)).replace(S.MARCA, '')
        if not plano.strip() and not _sin_tokens(target, None, False).replace(S.MARCA, '').strip(): raise Rechazo('TARGET_VACIO')
        if not plano.strip(): plano = _sin_tokens(target, None, False).replace(S.MARCA, '')   # solo hay texto dentro del <If>: se juzga igualmente (CJK)
        # saltos de linea reales (LF): el target puede llevar MAS que el source (re-envolver lineas); los del source siguen exigidos como minimo.
        # El resto de caracteres de control, identicos y en el mismo orden. (sestring.validate y el validador C# ya ignoran \n.)
        if [c for c in target if G.es_control(c) and c != '\n'] != [c for c in tok if G.es_control(c) and c != '\n'] or target.count('\n') < tok.count('\n'):
            raise Rechazo('CONTROL', 'caracteres de control distintos del source (o faltan saltos de linea)')
        if G.tiene_cjk(plano) and not G.es_simbolos(_sin_tokens(tok)): raise Rechazo('CJK')
    filtro_tokens(tok, target)
    filtro_protegidos(tok, target.replace(S.MARCA, ''))   # la marca no es texto: los literales protegidos/glifos PUA se juzgan sin ella
    if F.simulate_phase_a(b, tok, tok)[0] != b: raise Rechazo('SOURCE', 'source -> bytes no reproduce los bytes del juego')
    nb, via, why = F.simulate_phase_a(b, tok, target)
    if nb is None: raise Rechazo('SIMULACION', '%s: %s' % (via, why))
    # con marcas «salto -> espacio» el resultado esperado es el target con esos NewLine ya convertidos (sestring.aplicar_marcas, independiente del detokenizador)
    if not S.has_reserved(target) and S.tokenize_raw(nb) != S.renumerar_newlines(S.expandir_colores_propios(S.aplicar_marcas(target))): raise Rechazo('SIMULACION', 're-tokenizado != target')
    return tok, target, via

def info_hoja(h, row):
    """-> (lang, start); Rechazo si la hoja no se puede parchear"""
    if h.get('variant') != 1: raise Rechazo('EXH_VARIANT', 'variant %r (el C# descarta Variant 2)' % (h.get('variant'),))
    lang = 'ja' if 'ja' in h['langs'] else ('' if h['langs'] == [''] else None)
    if lang is None: raise Rechazo('SIN_PAGINA_JA', str(h['langs']))
    for start, cnt in h['pages']:
        if start <= row < start + cnt: return lang, start
    raise Rechazo('SIN_PAGINA', 'fila %d fuera de las paginas del EXH' % row)

def procesar_hoja(root, hoja, path, exh, vistos, avisos=None, incluir_corpus=False):
    """-> (entradas [(sheet,row,field,source,target,exdPath,'approved')], rechazos [dict], nleidas); `avisos` (lista opcional) recibe los avisos no bloqueantes;
    filas con "origen":"corpus" (heredadas del corpus ingles) se rechazan (CORPUS_HEREDADO) salvo incluir_corpus"""
    ok = []; rech = []; n = 0
    ja = G.leer_ja(root, hoja); h = exh(hoja) if ja is not None else None
    lineas = []
    with open(path, encoding='utf-8') as f:
        for ln, l in enumerate(f, 1):
            if not l.strip(): continue
            n += 1
            try: e = json.loads(l)
            except ValueError: rech.append(dict(hoja=hoja, row='', sub='', col='', estado='', motivo='JSON_INVALIDO', detalle='linea %d' % ln)); continue
            if not isinstance(e, dict) or not isinstance(e.get('row'), int) or isinstance(e.get('row'), bool) or not isinstance(e.get('col'), int) or e.get('sub') is not None and not isinstance(e.get('sub'), int):
                rech.append(dict(hoja=hoja, row='', sub='', col='', estado='', motivo='JSON_INVALIDO', detalle='linea %d: faltan row/sub/col enteros' % ln)); continue
            lineas.append(e)
    cuenta = collections.Counter((e['row'], e.get('sub'), e['col']) for e in lineas)
    for e in lineas:
        k = (e['row'], e.get('sub'), e['col'])
        base = dict(hoja=hoja, row=e['row'], sub='' if e.get('sub') is None else e['sub'], col=e['col'], estado=e.get('estado', ''))
        try:
            if cuenta[k] > 1: raise Rechazo('DUPLICADO', 'row/sub/col repetido en el fichero')
            if e.get('origen') == 'corpus':
                if not incluir_corpus: raise Rechazo('CORPUS_HEREDADO', 'origen corpus: retraducir desde ja+fr (o --incluir-corpus)')
            elif e.get('origen') not in ORIGENES_VALIDOS: raise Rechazo('ORIGEN_DESCONOCIDO', 'origen %r no esta en %s' % (e.get('origen'), ORIGENES_VALIDOS))
            if ja is None: raise Rechazo('HOJA_INEXISTENTE', 'sin textos/ja/%s.jsonl' % hoja)
            if k not in ja: raise Rechazo('FILA_INEXISTENTE', 'no esta en textos/ja')
            if e.get('sub') is not None: raise Rechazo('SUBFILA', 'hojas con subfilas (variant 2) no soportadas')
            if h is None: raise Rechazo('EXH_AUSENTE', 'sin EXH en el juego')
            text, raw = ja[k]
            tok, target, via = evaluar_cadena(text, raw, e)
            lang, start = info_hoja(h, e['row'])
            try: field = campos.col_to_field(h, e['col'])
            except ValueError as ex: raise Rechazo('COLUMNA', str(ex))
            dk = (hoja.lower(), e['row'], field)
            if dk in vistos: raise Rechazo('DUPLICADO', 'sheet+rowId+field ya presente')
            vistos.add(dk)
            path_exd = 'exd/%s_%d_%s.exd' % (hoja.lower(), start, lang) if lang else 'exd/%s_%d.exd' % (hoja.lower(), start)
            ok.append((hoja, e['row'], field, tok, target, path_exd, 'approved'))
            if avisos is not None: avisos += [dict(base, motivo=m, detalle=d) for m, d in avisos_cadena(tok, target)]
        except Rechazo as r:
            rech.append(dict(base, motivo=r.motivo, detalle=r.detalle))
    return ok, rech, n

def hojas_traducidas(root, solo=None):
    base = os.path.join(root, 'traducciones'); res = []
    for d, _, fs in os.walk(base):
        for f in fs:
            if f.endswith('.jsonl'):
                p = os.path.join(d, f); hoja = os.path.relpath(p, base)[:-6].replace(os.sep, '/')
                if solo is None or hoja == solo: res.append((hoja, p))
    return sorted(res)

def construir(root, exh, solo=None, avisos=None, incluir_corpus=False):
    """-> (entradas, rechazos, nleidas); `avisos` (lista opcional) recibe los avisos no bloqueantes (digitos/fechas que desaparecen)"""
    ok = []; rech = []; vistos = set(); total = 0
    for hoja, p in hojas_traducidas(root, solo):
        o, r, n = procesar_hoja(root, hoja, p, exh, vistos, avisos, incluir_corpus); ok += o; rech += r; total += n
    return ok, rech, total

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', required=True); ap.add_argument('--sheet'); ap.add_argument('--root', default=RAIZ)
    ap.add_argument('--out'); ap.add_argument('--revisar'); ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--incluir-corpus', action='store_true', help='incluye tambien las filas con origen corpus (comportamiento anterior)')
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    out = a.out or os.path.join(root, 'out', 'translations.dat')
    revisar = a.revisar or os.path.join(os.path.dirname(os.path.abspath(out)), 'revisar.csv')
    from sqpack_raw import Pack
    pk = Pack(a.game); cache = {}
    def exh(s):
        if s not in cache: cache[s] = pk.exh(s)
        return cache[s]
    avisos = []
    ok, rech, total = construir(root, exh, a.sheet, avisos, a.incluir_corpus)
    mot = collections.Counter(r['motivo'] for r in rech)
    print('leidas %d, aceptadas %d, rechazadas %d%s' % (total, len(ok), len(rech), (' (' + ', '.join('%s=%d' % kv for kv in sorted(mot.items())) + ')') if mot else ''))
    print('avisos (no bloqueantes): %d' % len(avisos))
    print('rechazos por origen: ORIGEN_DESCONOCIDO=%d CORPUS_HEREDADO=%d' % (mot['ORIGEN_DESCONOCIDO'], mot['CORPUS_HEREDADO']))
    if a.dry_run: return 0
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(revisar, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, ['hoja', 'row', 'sub', 'col', 'estado', 'motivo', 'detalle'], lineterminator='\n'); w.writeheader(); w.writerows(rech)
    with open(os.path.join(os.path.dirname(os.path.abspath(revisar)), 'avisos.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, ['hoja', 'row', 'sub', 'col', 'estado', 'motivo', 'detalle'], lineterminator='\n'); w.writeheader(); w.writerows(avisos)
    if not ok:
        print('sin entradas aceptadas: no se escribe %s' % out, file=sys.stderr); return 1
    lines = [entry_line(s, t, h, r, f_, p, st) for h, r, f_, s, t, p, st in ok]
    n, np_, nb = escribir_blob(lines, out, None, [(x[3], x[4]) for x in ok])
    print('OK %s: %d entradas, %d B JSONL -> %d B zstd(19); rechazos en %s' % (out, n, np_, nb, revisar))
    if os.path.exists(os.path.join(root, 'textos', 'INDEX.csv')):
        import progreso; progreso.escribir(root)
    return 0
if __name__ == '__main__': sys.exit(main())
