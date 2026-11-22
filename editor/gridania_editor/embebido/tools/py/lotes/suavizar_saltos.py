#!/usr/bin/env -S python3 -I
"""Convierte los saltos de linea DUROS (<NewLine>) del texto visible en «saltos suaves» (marca U+E0F0 tras el NewLine: el parcheador lo cambia por un espacio y el JUEGO envuelve).
Motivo (2026-11-05/08): nuestros saltos duros por linea caen a media frase y dejan lineas huerfanas; la ventana envuelve sola.

COBERTURA (orden del propietario 2026-11-08: «todo el juego»). Cada celda se trata segun su perfil de caja (cajas/perfiles_caja.tsv):
- `dialogo`: modo `todo` (comportamiento original): se suavizan TODOS los saltos que no separan una linea en blanco (parrafo vacio).
- `autoajuste`, `guia`, `desconocido` / sin perfil (Item, Addon, ActionTransient, tutoriales, diario SEQ/TODO, Fate, ContentTalk...): modo `media`: SOLO los saltos a media frase
  (la linea previa no acaba en puntuacion terminal `. ! ? … :` y la siguiente empieza en minuscula, o la previa acaba en `,` `;` o en palabra funcional: articulo, preposicion,
  conjuncion...) y el que deja una ultima linea huerfana (<= 2 palabras). Se respetan saltos tras puntuacion terminal (parrafos reales), lineas en blanco, titulos/etiquetas
  (siguiente linea en mayuscula tras linea sin palabra funcional final), notas `※`, listas.
- `subtitulo` (cut_scene, opening, NARRATION): igual que `media`, pero la linea resultante no supera el ancho seguro del perfil (58): no hay recuadro que envuelva.
- NO se tocan: cajas de ancho fijo (`hud_fijo`, `descripcion` del creador de personaje, `sistema`), hojas Balloon y NpcYell (se reajustan solas por orden expresa), ENpcResident (nombres),
  Lobby y CharaMake*. Texto dentro de macros (Run/If/Sheet...) o antes del ultimo MacroEnd no se marca (reglas pgri); LF reales de la fuente tampoco.
Que se suaviza segun la forma de la celda:
- lista de trozos (cadena simple): el NewLine entre trozos se marca (primer caracter del trozo siguiente); un `<NewLine>` literal DENTRO de un trozo (salto EXTRA del reflujo) se cambia por un espacio.
- cadena compleja (con macros): se marca tras cada NewLine de nivel superior elegido; un LF real del `es` que no esta en el ja (salto extra del reflujo) se cambia por un espacio.
Todo candidato pasa por `construir_dat.evaluar_cadena`; si se rechaza se reintenta con menos saltos y si no, la celda se deja como esta.
No modifica traducciones/: escribe RAIZ_SALIDA/traducciones/<hoja>.jsonl con las celdas transformadas (mismo h/origen/estado); luego construir_dat.py --root RAIZ_SALIDA (flujo bitacora §4: fusionar sobre una copia).
Uso: python3 -I suavizar_saltos.py --repo RAIZ --ja RAIZ_JA --out RAIZ_SALIDA [--hojas a,b] [--excluir lista.txt] [--jobs N]   (RAIZ_JA = raiz con textos/ja; vale el propio repo)"""
import sys, os, json, re, argparse, collections, fnmatch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ELIPSIS = re.compile(r'(?:…+|\.{3,})')
def unir(a, b):
    """Costura de un salto suave: A y B acaban fundidos en un solo texto. En japones cada linea abre/cierra con pausa (……) y al fundirlas se acumulan.
    A acaba en elipsis y B empieza con elipsis -> se quita la de B; A acaba en '.' y B empieza con elipsis -> 'A...' + ' ' + B sin elipsis. Solo presentacion en el .dat."""
    mb = re.match(r'\s*(?:…+|\.{3,})\s*', b)
    if not mb: return a, b
    resto = b[mb.end():]
    if not resto.strip(): return a, b
    ra = a.rstrip()
    if re.search(r'(?:…|\.{3})$', ra): return a, resto
    if ra.endswith('.') and not ra.endswith('..'): return ra[:-1] + '...', resto
    return a, b
import normalizar_signos_japoneses as _NSJ, normalizar_puntos_suspensivos as _NPS
def normalizar(es):
    """orden fijo: signos japoneses -> espanoles (sobre el texto SIN marca: la apertura ¡/¿ debe ir antes de la marca que se anade despues) -> puntos suspensivos RAE (max. 3)"""
    return _NPS.normalizar(_NSJ.normalizar(es))

G = S = CD = PF = None   # modulos del repo (iniciar)
def iniciar(repo):
    """importa segmentar, sestring y construir_dat del repo dado (los tests llaman a esto)"""
    global G, S, CD, PF
    for p in (os.path.join(repo, 'tools', 'py'), os.path.join(repo, 'tools', 'py', 'cajas')):
        if p not in sys.path: sys.path.insert(0, p)
    cj = os.path.join(repo, 'tools', 'py', 'lotes', 'cajas')
    if cj not in sys.path: sys.path.insert(0, cj)
    import segmentar as g, sestring as s, construir_dat as cd
    G, S, CD = g, s, cd
    return G, S, CD

NOSTART = {'NewLine', 'ColorType', 'EdgeColorType', 'Raw', 'Run', 'RunEnd', 'MacroEnd', 'Gender', 'GenderElse', 'GenderEnd', 'Icon', 'Icon2', 'Num', 'Kilo', 'UIColor', 'UIColorEnd'}
NL_LIT = re.compile(r'<NewLine(?:#[0-9]+)?>')
COLOR_SEP = re.compile(r'<(?:Edge)?ColorType')
EXCLUIR_HOJAS = ('Balloon', 'NpcYell', 'ENpcResident', 'Lobby', 'CharaMake*')
TIPOS_FIJOS = ('hud_fijo', 'descripcion', 'sistema')
TERM = '.!?…:。！？'
CIERRES = '»”"\')]'
FUNC = frozenset((
    'el la los las un una unos unas lo al del de a ante bajo con contra desde en entre hacia hasta para por según segun sin sobre tras durante mediante '
    'y e o u ni que como cuando donde cuyo cuya cuyos cuyas si pero aunque mientras porque pues se su sus mi mis tu tus nuestro nuestra nuestros nuestras vuestro vuestra vuestros vuestras '
    'me te nos os le les este esta estos estas ese esa esos esas aquel aquella más menos muy tan no ya también tampoco cada otro otra otros otras todo toda todos todas').split())

def es_clave_narrador(clave):
    """clave col 0 con MYSTERYVOICE o NARRAT (criterio antiguo, solo para puntuar_narrador/gen_corrnarr)"""
    c = (clave or '').upper()
    return 'MYSTERYVOICE' in c or 'NARRAT' in c

def es_narrador(perfil, clave=None):
    """celda de narrador = su perfil de caja es `subtitulo` (cut_scene/*, opening/*, quest/*_NARRATION|HYDAELYN|MOTHERCRYSTAL): sus trozos son frases sueltas y NO se funden nunca (propietario 2026-11-17). `clave` (opcional): se conserva ademas la proteccion antigua por clave MYSTERYVOICE/NARRAT (291 celdas de dialogo)"""
    return getattr(perfil, 'tipo', None) == 'subtitulo' or es_clave_narrador(clave)

def excluida(hoja):
    return any(fnmatch.fnmatchcase(hoja, p) for p in EXCLUIR_HOJAS)

def modo_de(perfil, fr_text=None):
    """-> (modo, cap): modo 'todo' | 'media' | None (no se toca); cap = ancho maximo de la linea resultante (0 = sin tope)"""
    t = perfil.tipo
    if t == 'dialogo': return 'todo', 0
    if t in TIPOS_FIJOS: return None, 0
    if t == 'subtitulo':   # sin recuadro: tope de ancho del proyecto (cajas/nucleo.py): min(90, max(ancho de linea del fr, 58)); sin fr, 58
        import nucleo
        return 'media', nucleo.tope_ancho_subtitulo(perfil, nucleo.medida_fr(fr_text, perfil) if fr_text else None) or 58
    return 'media', 0

# ---------------------------------------------------------------- analisis de lineas
def termina(p):
    """True si la linea acaba en puntuacion terminal (tras cierres de comillas/parentesis): fin de frase o de parrafo"""
    q = p.rstrip()
    while q and q[-1] in CIERRES: q = q[:-1].rstrip()
    return bool(q) and q[-1] in TERM

def _ultima_palabra(p):
    m = re.search(r'([^\W\d_]+)$', p)
    return m.group(1).lower() if m else ''

def es_media(p, n):
    """salto duro p|n a media frase: p no acaba en puntuacion terminal y n continua (minuscula, o p acaba en coma/punto y coma o palabra funcional)"""
    p = p.strip(); n = n.strip()
    if not p or not n or termina(p): return False
    return n[0].islower() or p[-1] in ',;' or _ultima_palabra(p) in FUNC

# ---------------------------------------------------------------- estructura (listas numeradas, titulos ■, cortes funcionales)
ITEM_ES = re.compile(r'^\s*(\d{1,2})[.):](?=\s|$)')
ITEM_JA = re.compile(r'^\s*([0-9０-９]{1,2})[.．:：)）、]')
FIN_ITEM = re.compile(r'(?:^|\s)(\d{1,2})\.$')
MARC_TIT = '■●◆▼'
ARTPREP = frozenset('el la los las un una unos unas lo al del de a ante bajo con contra desde en entre hacia hasta para por segun según sin sobre tras'.split())
CONJ = frozenset('y e o u ni que'.split())

def es_item(n):
    """la linea n abre un elemento numerado «N.» (N. / N) / N:)"""
    return bool(ITEM_ES.match(n))

def cola_funcional(p, maxw=3):
    """palabras funcionales (articulo/preposicion, en minuscula) que la linea p deja colgadas al final; 0 si no hay o la linea acaba en puntuacion/mayuscula (rotulo «Plan A»)"""
    q = p.rstrip()
    if not q or termina(q): return 0
    ws = q.split(); k = 0
    while k < min(maxw, len(ws) - 1) and ws[-1 - k].lower() == ws[-1 - k] and (ws[-1 - k] in ARTPREP or ws[-1 - k] in CONJ): k += 1
    return k

def mover_cola(nes, seps, cap=0, items_ja=()):
    """Regla «nunca cortar tras articulo/preposicion» y «un item N. nunca acaba linea»: en cada salto duro entre trozos vecinos no vacios (no suave) las palabras funcionales colgadas
    al final del trozo previo (o el `N.` final de un item) pasan al inicio del siguiente. Con `cap` (subtitulos) solo si la linea siguiente no pasa del tope. -> (lista, nº movimientos)"""
    nes = list(nes); n = 0
    for i, sp in enumerate(seps):
        if i + 1 >= len(nes) or not G.NL_RE.match(sp): continue
        a, b = nes[i], nes[i + 1]
        if not a.strip() or not b.strip() or b.startswith(S.MARCA): continue
        pa = a.rstrip(); nb = b.lstrip()
        mf = FIN_ITEM.search(pa)
        if mf and not es_item(nb) and int(mf.group(1)) in items_ja and len(pa.split()) > 1:
            k = pa.rfind(mf.group(1) + '.'); mov = pa[k:]; resto = pa[:k].rstrip()
        else:
            k = cola_funcional(pa)
            if not k or es_item(nb): continue
            ws = pa.split(); mov = ' '.join(ws[-k:]); resto = ' '.join(ws[:-k])
            if '<' in mov or '>' in mov: continue
        if not resto or (cap and len(mov) + 1 + len(nb) > cap): continue
        nes[i] = resto; nes[i + 1] = mov + ' ' + nb; n += 1
    return nes, n

BRK = re.compile(r'(\n|<NewLine(?:#[0-9]+)?>)')
def _nivel(t):
    """texto tokenizado -> True si al final de `t` se esta dentro de una macro (If/Sheet/...) o de una rama de genero"""
    depth = 0; gen = 0
    for tk, _ in S._atoms(t):
        bn = S._bn(tk)
        if bn == 'MacroEnd': depth = max(0, depth - 1)
        elif bn == 'Gender': gen = 1
        elif bn == 'GenderElse': gen = 2
        elif bn == 'GenderEnd': gen = 0
        elif bn not in NOSTART: depth += 1
    return depth > 0 or gen != 0

def mover_en_texto(t, cap=0):
    """misma regla que `mover_cola` para saltos DENTRO de un texto (LF real o `<NewLine>` literal): las palabras funcionales (texto plano, sin macros) colgadas ante el salto pasan tras el.
    No toca saltos dentro de macros/ramas de genero ni saltos suaves. -> (texto, n)"""
    partes = BRK.split(t)
    if len(partes) < 3: return t, 0
    n = 0
    for k in range(1, len(partes), 2):
        li = partes[k - 1].rstrip(' '); der = partes[k + 1]
        if not der.strip() or es_item(der.lstrip()) or der.startswith(S.MARCA): continue   # salto suave: el juego lo vuelve espacio
        kf = cola_funcional(li)
        if not kf: continue
        mov = ' '.join(li.split()[-kf:])
        if '<' in mov or '>' in mov or not li.endswith(mov): continue
        if cap and len(mov) + 1 + len(der.strip()) > cap: continue
        if '<' in t and _nivel(''.join(partes[:k])): continue
        partes[k - 1] = li[:len(li) - len(mov)].rstrip(' '); partes[k + 1] = mov + ' ' + der.lstrip(' '); n += 1
    return ''.join(partes), n

def lineas_fr(t):
    return [re.sub(r'\{0x[0-9A-Fa-f]+(?::[0-9A-Fa-f]*)?\}', '', x) for x in t.split('{0x10:}')]

def duros_fr(fr_text, n_trozos):
    """indices de trozo que el FRANCES abre siempre en linea nueva (item «N.», titulo ■ y la linea que sigue a un titulo); solo si el fr tiene tantas lineas como trozos tiene la celda"""
    if not fr_text: return frozenset()
    ls = lineas_fr(fr_text)
    if len(ls) != n_trozos: return frozenset()
    return frozenset(i for i in range(1, len(ls)) if ls[i].strip() and (es_item(ls[i]) or ls[i].lstrip().startswith('■') or ls[i - 1].lstrip().startswith('■') and ls[i - 1].strip()))

def bloques_ja(ch):
    """chunks ja (cadena simple, todo separado por NewLine) -> lista de bloques (tipo, n, [indices de trozo no vacios]).
    Un bloque nuevo empieza tras linea en blanco, en un item «N.», un titulo ■ o nota ※, y en la linea que sigue a un titulo; el resto son continuaciones (linea del ja partida por la caja)."""
    bl = []; prev = None; prev_t = None
    for i, l in enumerate(ch):
        t = l.strip()
        if not t: prev = None; prev_t = None; continue
        mi = ITEM_JA.match(t)
        if mi: tipo, n = 'I', int(mi.group(1).translate(str.maketrans('０１２３４５６７８９', '0123456789')))
        elif t[0] in MARC_TIT: tipo, n = 'T', 0
        elif t[0] == '※': tipo, n = 'N', 0
        else: tipo, n = 'P', 0
        nuevo = prev is None or tipo != 'P' or prev_t == 'T'
        if nuevo: bl.append([tipo, n, [i]])
        else: bl[-1][2].append(i)
        prev = i; prev_t = tipo
    return [tuple(b) for b in bl]

def flujo_es(nes):
    """trozos es -> texto corrido: lineas unidas por espacio, tramos en blanco = '\\n\\n' (marcas leidas como espacio)"""
    out = []; blanco = False
    for t in nes:
        for ln in NL_LIT.split(t.replace(S.MARCA, '')):
            ln = ln.strip()
            if not ln: blanco = True; continue
            if out: out.append('\n\n' if blanco else '\x01')
            out.append(ln); blanco = False
    return ''.join(out)

def partir(seg, k, pesos):
    """segmento -> k partes no vacias por corte gramatical (tras puntuacion o antes de palabra funcional/conjuncion, nunca tras articulo/preposicion), proporcional a `pesos`; None si no se puede"""
    if k == 1: return [seg]
    ws = seg.split(' ')
    if len(ws) < k: return None
    tot = float(sum(pesos)); acum = 0; objetivos = []
    for p in pesos[:-1]: acum += p; objetivos.append(acum / tot * len(seg))
    cortes = []; ini = 0
    for t in objetivos:
        mejor = None
        for j in range(ini + 1, len(ws) - (k - 1 - len(cortes)) + 0):
            if j > len(ws) - 1: break
            izq = ' '.join(ws[:j]); ult = ws[j - 1]
            if (ult in ARTPREP or ult in CONJ): continue
            c = abs(len(izq) - t) - (8 if izq[-1:] in ',;:.!?»)' else 0) - (4 if ws[j].lower() in CONJ else 0)
            if mejor is None or c < mejor[0]: mejor = (c, j)
        if mejor is None: return None
        cortes.append(mejor[1]); ini = mejor[1]
    partes = []; a = 0
    for c in cortes + [len(ws)]: partes.append(' '.join(ws[a:c])); a = c
    return partes if all(x.strip() for x in partes) else None

def reestructurar(nes, ch):
    """Realinea el es de una guia/tutorial con la estructura del ja (trozo a trozo): titulos ■ enteros en su linea, cada «N.» al inicio de linea, notas ※ en su linea, lineas en blanco donde el ja las tiene,
    y sin trozos vacios donde el ja tiene texto. El texto no cambia (solo reparte). -> (lista, motivo): lista nueva o None si no se puede (el motivo explica por que)."""
    bl = bloques_ja(ch)
    if not bl: return None, 'sin_bloques'
    txt = flujo_es(nes); pos = [0]
    def buscar(tipo, n, desde):
        if tipo == 'T': m = re.compile(r'■').search(txt, desde)
        elif tipo == 'I': m = re.compile(r'(?:(?<=[\s\x01])|^)%d\s*[.):](?=[\s\x01])' % n).search(txt, desde)
        elif tipo == 'N': m = re.compile(r'(?:(?<=[\s\x01])|^)[*※]').search(txt, desde)
        elif tipo == 'P':
            ant = bl[len(starts) - 1][0] if starts else None
            if ant == 'T':   # titulo seguido de texto sin linea en blanco: el titulo acaba donde el es ya lo tenia en su propia linea (salto sin cola funcional y texto en mayuscula)
                m = re.compile(r'\x01(?=[^a-zá-ú\s])').search(txt, desde)
                if m and txt[starts[-1]:m.start()].startswith('■') and not cola_funcional(txt[starts[-1]:m.start()]): return m.end()
                return None
            m = re.compile(r'\n\n+').search(txt, desde); return m.end() if m else None
        return m.start() if m else None
    starts = []
    for bi, (tipo, n, idx) in enumerate(bl):
        if bi == 0:
            if tipo != 'P' and buscar(tipo, n, 0) != 0: return None, 'inicio_no_coincide'
            starts.append(0); continue
        desde = starts[-1] + 1
        s0 = buscar(tipo, n, desde)
        if s0 is None: return None, 'sin_marcador_%s%s' % (tipo, n or '')
        starts.append(s0)
    segs = []
    for bi in range(len(bl)):
        fin = starts[bi + 1] if bi + 1 < len(bl) else len(txt)
        seg = re.sub(r'[\s\x01]+', ' ', txt[starts[bi]:fin]).strip()
        if not seg: return None, 'segmento_vacio'
        segs.append(seg)
    out = [''] * len(ch)
    for (tipo, n, idx), seg in zip(bl, segs):
        partes = partir(seg, len(idx), [max(1, len(ch[i].strip())) for i in idx])
        if partes is None: return None, 'no_parte'
        for j, (i, p) in enumerate(zip(idx, partes)): out[i] = (S.MARCA if j else '') + p
    return out, 'ok'

def defecto_estructura(lineas, ch_items, hay_titulo):
    """celda con items «N.» (los del ja) pegados al final de la linea previa o no al inicio de linea, o titulo ■ partido/seguido de texto"""
    ini = set(int(m.group(1)) for l in lineas for m in [ITEM_ES.match(l)] if m)
    if ch_items and not set(ch_items) <= ini: return True
    for i, l in enumerate(lineas):
        s = l.strip()
        m = FIN_ITEM.search(s)
        if m and i + 1 < len(lineas) and lineas[i + 1].strip() and int(m.group(1)) in ch_items: return True
        if hay_titulo and s.startswith('■'):
            if cola_funcional(s) or re.search(r'\s\d{1,2}[.):]\s', s[1:]): return True
            nx = lineas[i + 1].strip() if i + 1 < len(lineas) else ''
            if nx and nx[0].islower(): return True
    return False

def es_huerfana(lineas, k):
    """la linea k (ultima no vacia, k>=1) es huerfana: <= 2 palabras tras una linea larga sin puntuacion terminal"""
    if k < 1: return False
    p = lineas[k - 1].strip(); n = lineas[k].strip()
    if not p or not n or len(p) < 20 or termina(p): return False
    if n[0] in '※■●◆・[(' or p[-1] in '])': return False   # notas y campos entre corchetes/parentesis: no son continuacion
    if not (n[0].islower() or termina(n)): return False       # ultima linea que no cierra frase ni continua (etiqueta, nombre): campo, no huerfana
    return len(n.split()) <= 2

def ultima_no_vacia(lineas):
    for k in range(len(lineas) - 1, -1, -1):
        if lineas[k].strip(): return k
    return -1

def corriente_lista(nes, seps, respetar_marcas):
    """lista de trozos + separadores -> (lineas, fronteras). fronteras[i] = sitio entre lineas[i] y lineas[i+1]: ('sep', i_sep) | ('lit', i_trozo, k)"""
    lineas = ['']; fr = []
    def add(t): lineas[-1] += t
    for i, t in enumerate(nes):
        if i > 0:
            sp = seps[i - 1]
            if G.NL_RE.match(sp):
                if respetar_marcas and t.startswith(S.MARCA): add(' ')
                else: fr.append(('sep', i - 1)); lineas.append('')
            elif re.match(r'<(?:Num|Kilo)', sp): add('0')
            elif sp.startswith('<Icon2'): add('¤')
        t = t.replace(S.MARCA, '')
        for k, pt in enumerate(NL_LIT.split(t)):
            if k > 0: fr.append(('lit', i, k - 1)); lineas.append('')
            add(pt)
    return lineas, fr

def corriente_compleja(es, respetar_marcas):
    """cadena tokenizada -> (lineas, fronteras, ult); sitio ('tok', pos) NewLine de nivel superior; ('lf', pos) LF real; None = no suavizable (dentro de macro)"""
    at = S._atoms(es); lineas = ['']; fr = []; depth = 0; prev = 0; gen = 0
    ult = max([p for tk, p in at if S._bn(tk) == 'MacroEnd'] or [-1])
    def add(t): lineas[-1] += t
    def texto(seg, start):
        if depth > 0 or gen == 2: return
        p = start
        for k, part in enumerate(seg.split('\n')):
            if k > 0: fr.append(('lf', p - 1)); lineas.append('')
            add(part.replace(S.MARCA, '').replace('<<', '<')); p += len(part) + 1
    for tk, pos in at:
        texto(es[prev:pos], prev); prev = pos + len(tk); bn = S._bn(tk)
        if bn == 'MacroEnd': depth = max(0, depth - 1)
        elif bn == 'Gender': gen = 1
        elif bn == 'GenderElse': gen = 2
        elif bn == 'GenderEnd': gen = 0
        elif bn == 'NewLine':
            if depth == 0 and respetar_marcas and es[prev:prev + 1] == S.MARCA: add(' ')
            else: fr.append(('tok', pos) if depth == 0 else None); lineas.append('')
        elif bn not in NOSTART:
            if depth == 0: add('¤')   # la macro (nombre, objeto, rama If...) escribe texto: cuenta como una palabra
            depth += 1
        elif depth == 0 and bn in ('Num', 'Kilo'): add('0')
        elif depth == 0 and bn in ('Icon', 'Icon2'): add('¤')
    texto(es[prev:], prev)
    return lineas, fr, ult

def decidir(lineas, fronteras, modo, cap=0, duros=frozenset()):
    """-> conjunto de sitios a suavizar"""
    sel = set(); ult = ultima_no_vacia(lineas)
    for i, b in enumerate(fronteras):
        if b is None or (b[0] == 'sep' and b[1] + 1 in duros): continue
        p = lineas[i].strip(); n = lineas[i + 1].strip()
        if not p or not n or es_item(n): continue
        if modo == 'todo' or es_media(p, n) or (i + 1 == ult and es_huerfana(lineas, ult)): sel.add(b)
    if cap and sel:   # sin recuadro que envuelva: la linea fundida no pasa del ancho seguro
        actual = lineas[0].strip()
        for i, b in enumerate(fronteras):
            n = lineas[i + 1].strip()
            if b in sel and len(actual) + 1 + len(n) <= cap: actual += ' ' + n
            else: sel.discard(b); actual = n if n else ''
    return sel

def laxa(lineas):
    """medida laxa de la lectura D (informativa, NO es objetivo): cualquier salto duro cuya linea previa no acaba en puntuacion terminal (incluye titulos/etiquetas y campos de Item)"""
    return sum(1 for i in range(len(lineas) - 1) if lineas[i].strip() and lineas[i + 1].strip() and not termina(lineas[i]))

def defectos(lineas):
    """-> (media, huerfana): saltos duros a media frase y si la ultima linea es huerfana (medidor)"""
    media = sum(1 for i in range(len(lineas) - 1) if es_media(lineas[i], lineas[i + 1]))
    return media, es_huerfana(lineas, ultima_no_vacia(lineas))

# ---------------------------------------------------------------- aplicar
def aplicar_lista(nes, seps, sel):
    nes = list(nes); por = collections.defaultdict(set)
    for s in sel:
        if s[0] == 'lit': por[s[1]].add(s[2])
    for i, ks in por.items():
        partes = NL_LIT.split(nes[i]); toks = NL_LIT.findall(nes[i]); out = partes[0]
        for k in range(1, len(partes)):
            if (k - 1) in ks: out = out.rstrip() + ' ' + partes[k].lstrip()
            else: out += toks[k - 1] + partes[k]
        nes[i] = out
    for s in sorted(x for x in sel if x[0] == 'sep'):
        i = s[1]
        if nes[i + 1].strip():
            nes[i], nes[i + 1] = unir(nes[i], nes[i + 1]); nes[i + 1] = S.MARCA + nes[i + 1].lstrip()
        else:   # salto seguido de trozos vacios + texto en color (solo separadores de color entre medias): la marca va en el primer trozo vacio
            k2 = i + 1
            while k2 < len(nes) and not nes[k2].strip() and k2 < len(seps) and COLOR_SEP.match(seps[k2]): k2 += 1
            if k2 < len(nes) and nes[k2].strip(): nes[i + 1] = S.MARCA
    return nes

def aplicar_compleja(es, sel):
    toks = {p: tk for tk, p in S._atoms(es)}; out = []; prev = 0
    for s in sorted(sel, key=lambda x: x[1]):
        if s[0] == 'tok':
            fin = s[1] + len(toks[s[1]]); out.append(es[prev:fin]); out.append(S.MARCA); prev = fin
        else:
            out.append(es[prev:s[1]]); izq = es[s[1] - 1:s[1]]; der = es[s[1] + 1:s[1] + 2]
            out.append('' if izq == ' ' or der == ' ' else ' '); prev = s[1] + 1
    out.append(es[prev:]); return ''.join(out)

def _todo_lista(nes, seps, duros=frozenset()):
    """modo `todo` sobre lista de trozos (algoritmo original, probado en el flujo vigente): marca todo NewLine entre trozos que no sea salto duro consecutivo"""
    nes = list(nes); cambio = False
    def duro(i):
        # el salto de seps[i] es duro (inicio o pegado a otro NewLine, mirando a traves de trozos vacios con separadores de color): no se marca
        j = i
        while not nes[j].strip():
            if j == 0 or not re.match(r'<(Edge)?ColorType', seps[j - 1]): return True
            j -= 1
        return False
    for i, sp in enumerate(seps):
        if G.NL_RE.match(sp) and duro(i): continue
        if G.NL_RE.match(sp) and (es_item(nes[i + 1].strip()) or i + 1 in duros): continue   # un item «N.» abre siempre linea
        if G.NL_RE.match(sp) and nes[i + 1].strip():
            nes[i], nes[i + 1] = unir(nes[i], nes[i + 1]); nes[i + 1] = S.MARCA + nes[i + 1].lstrip(); cambio = True
        elif G.NL_RE.match(sp) and not nes[i + 1].strip() and nes[i].strip():
            k2 = i + 1
            while k2 < len(nes) and not nes[k2].strip() and k2 < len(seps) and re.match(r'<(Edge)?ColorType', seps[k2]): k2 += 1
            if k2 < len(nes) and nes[k2].strip() and not nes[i + 1].strip(): nes[i + 1] = S.MARCA; cambio = True
    return nes if cambio else None

def _todo_compleja(es, solo_tras_ultima=False):
    """modo `todo` sobre cadena compleja (original): MARCA tras cada <NewLine> fuera de macro; pgri: ni dentro de un Run ni ANTES del ultimo MacroEnd (solo_tras_ultima)"""
    at = list(S._atoms(es)); out = []; prev = 0; depth = 0; cambio = False
    ult = max([pos for tk, pos in at if S._bn(tk) == 'MacroEnd'] or [-1])
    for tk, pos in at:
        out.append(es[prev:pos + len(tk)]); prev = pos + len(tk); bn = S._bn(tk)
        if bn == 'MacroEnd': depth = max(0, depth - 1)
        elif bn not in NOSTART: depth += 1
        elif bn == 'NewLine' and depth == 0 and (pos > ult or not solo_tras_ultima) and not es[prev:prev + 1] == S.MARCA and not es_item(es[prev:prev + 6]):
            out.append(S.MARCA); cambio = True
    out.append(es[prev:])
    return ''.join(out) if cambio else None

def _suavizar_celda(es, tok, raw, modo, cap=0, validar=None, fr_text=None):
    """-> (nuevo_es | None, motivo). es: lista de trozos o cadena tokenizada; tok: ja tokenizado; validar(cand) -> bool (construir_dat.evaluar_cadena) o None.
    modo `todo`: algoritmo original (todos los saltos) + cambio de los saltos EXTRA (`<NewLine>` dentro de un trozo / LF real) por espacio; modo `media`: solo saltos a media frase y huerfanas."""
    ok = validar or (lambda c: True)
    if isinstance(es, list):
        if G.clasificar(tok, bool(raw)) != 'simple': return None, 'complejo'
        ch, seps = G.trocear(tok)
        if len(es) != len(ch): return None, 'no_alinea'
        base = normalizar([x.replace(S.MARCA, '') for x in es])
        if all(G.NL_RE.match(x) for x in seps):   # guias/tutoriales con items o titulos: realinear con la estructura del ja
            bl = bloques_ja(ch); its = [b[1] for b in bl if b[0] == 'I']
            if (len(its) >= 2 or any(b[0] == 'T' for b in bl)) and (defecto_estructura(corriente_lista(base, seps, False)[0], its, any(b[0] == 'T' for b in bl))
                                                                    or any(c.strip() and not b.strip() for c, b in zip(ch, base))):
                nuevo, mot = reestructurar(base, ch)
                if nuevo is not None:
                    if ok(nuevo): return nuevo, 'ok'
                    mot = 'rechazo_validador_reestructura'
        if modo == 'todo':
            duros = duros_fr(fr_text, len(ch))
            cand = _todo_lista(base, seps, duros)
            lineas, fr = corriente_lista(cand or base, seps, True)
            sel = set(x for x in decidir(lineas, fr, 'todo') if x[0] == 'lit')
            if sel: cand = aplicar_lista(cand or base, seps, sel)
            if cand is None: return None, 'sin_saltos'
            if ok(cand): return cand, 'ok'
            c2 = _todo_lista(base, seps, duros)
            if c2 is not None and ok(c2): return c2, 'ok'
            return None, 'rechazo_validador'
        lineas, fr = corriente_lista(base, seps, False)
        sel = decidir(lineas, fr, modo, cap, duros_fr(fr_text, len(ch)))
        if not sel: return None, 'sin_saltos'
        for s in (sel, set(x for x in sel if x[0] == 'sep')):
            if not s: break
            cand = aplicar_lista(base, seps, s)
            if ok(cand): return cand, 'ok'
        return None, 'rechazo_validador'
    if isinstance(es, str):
        base = normalizar(es.replace(S.MARCA, ''))
        if modo == 'todo':
            cands = []
            for solo_tras in (False, True):
                c = _todo_compleja(base, solo_tras)
                if c is None: break
                cands.append(c)
            cand = None
            for c in cands:
                if ok(c): cand = c; break
            if cand is None and cands: return None, 'rechazo_validador'
            if '\n' not in tok:   # LF reales del es que no vienen del ja (saltos extra del reflujo) -> espacio
                lineas, fr, ult = corriente_compleja(cand or base, True)
                sel = set(x for x in decidir(lineas, fr, 'todo') if x[0] == 'lf')
                if sel:
                    c3 = aplicar_compleja(cand or base, sel)
                    if ok(c3): cand = c3
            return (cand, 'ok') if cand is not None else (None, 'sin_saltos')
        lineas, fr, ult = corriente_compleja(base, False)
        sel = decidir(lineas, fr, modo, cap)
        if '\n' in tok: sel = set(x for x in sel if x[0] != 'lf')   # LF de la fuente: no se sabe cual es extra
        if not sel: return None, 'sin_saltos'
        cand = aplicar_compleja(base, sel)
        if ok(cand): return cand, 'ok'
        tras = set(x for x in sel if x[1] > ult)   # pgri: nada antes del ultimo MacroEnd
        if tras and tras != sel:
            cand = aplicar_compleja(base, tras)
            if ok(cand): return cand, 'ok'
        acumulado = set()   # ultimo recurso: sitio a sitio
        for s in sorted(sel, key=lambda x: x[1]):
            if ok(aplicar_compleja(base, acumulado | {s})): acumulado.add(s)
        if acumulado: return aplicar_compleja(base, acumulado), 'ok'
        return None, 'rechazo_validador'
    return None, 'tipo'

def suavizar_celda(es, tok, raw, modo, cap=0, validar=None, fr_text=None):
    """envoltorio: suavizado (`_suavizar_celda`) + regla de cortes funcionales/items finales sobre los saltos duros que queden: `mover_en_texto` (LF/<NewLine> dentro de un texto: cadenas complejas y trozos)
    y `mover_cola` (salto entre trozos vecinos). Cada paso se valida; si se rechaza se queda el resultado anterior."""
    nuevo, motivo = _suavizar_celda(es, tok, raw, modo, cap, validar, fr_text)
    if motivo not in ('ok', 'sin_saltos', 'rechazo_validador'): return nuevo, motivo
    ok = validar or (lambda c: True)
    if isinstance(es, str):
        b0 = nuevo if nuevo is not None else normalizar(es.replace(S.MARCA, ''))
        c, n = mover_en_texto(b0, cap)
        return (c, 'ok') if n and ok(c) else (nuevo, motivo)
    if not isinstance(es, list): return nuevo, motivo
    base = nuevo if nuevo is not None else normalizar([x.replace(S.MARCA, '') for x in es])
    c1 = []; n1 = 0
    for x in base: y, k = mover_en_texto(x, cap); c1.append(y); n1 += k
    if n1 and ok(c1): base, nuevo, motivo = c1, c1, 'ok'
    if len(es) > 1:
        ch, seps = G.trocear(tok)
        if len(es) == len(ch):
            items = set(b[1] for b in bloques_ja(ch) if b[0] == 'I') if all(G.NL_RE.match(x) for x in seps) else ()
            c2, n2 = mover_cola(base, seps, cap, items)
            if n2 and ok(c2): return c2, 'ok'
    return nuevo, motivo

# ---------------------------------------------------------------- hoja
def hojas_repo(base):
    for dp, _, fs in os.walk(base):
        for f in sorted(fs):
            if f.endswith('.jsonl'): yield os.path.relpath(os.path.join(dp, f), base)[:-6].replace(os.sep, '/'), os.path.join(dp, f)

def perfil_celda(pf, hoja, e, ja):
    clave = None
    if pf.necesita_clave(hoja, e['col']):
        c0 = ja.get((e['row'], e.get('sub'), 0)); clave = c0[0] if c0 else None
    return pf.de(hoja, e['col'], e['row'], clave)

def tiene_candidato(es):
    """prefiltro barato: la celda puede llevar un salto (NewLine/LF) o es una lista de >= 2 trozos"""
    if isinstance(es, list): return len(es) > 1 or any('<NewLine' in x for x in es)
    return isinstance(es, str) and ('<NewLine' in es or '\n' in es)

def procesar_hoja(args):
    repo, ja_root, out, hoja, path = args
    cnt = collections.Counter()
    ja = G.leer_ja(ja_root, hoja)
    if ja is None: return hoja, cnt
    res = []; import nucleo; fr = nucleo.leer_fr(ja_root, hoja)
    for l in open(path, encoding='utf-8'):
        if not l.strip(): continue
        e = json.loads(l); k = (e['row'], e.get('sub'), e['col']); es = e.get('es')
        if k not in ja or not tiene_candidato(es): continue
        perfil = perfil_celda(PF, hoja, e, ja)
        c0 = ja.get((e['row'], e.get('sub'), 0))
        if es_narrador(perfil, c0[0] if c0 and e['col'] != 0 else None): cnt['narrador'] += 1; continue
        modo, cap = modo_de(perfil, fr.get(k))
        if modo is None: cnt['caja_fija'] += 1; continue
        t, raw = ja[k]; tok = S.tokenize_raw(G.bytes_ja(t, raw))
        def validar(cand, e=e, t=t, raw=raw):
            try: CD.evaluar_cadena(t, raw, dict(e, es=cand, estado='traducida')); return True
            except CD.Rechazo: return False
        n, motivo = suavizar_celda(es, tok, raw, modo, cap, validar, fr.get(k))
        cnt[motivo] += 1
        if n is not None: cnt['suavizada_' + modo] += 1; res.append(dict(e, es=n))
    if res:
        p = os.path.join(out, 'traducciones', hoja + '.jsonl'); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w', encoding='utf-8').write('\n'.join(json.dumps(x, ensure_ascii=False) for x in res) + '\n')
    return hoja, cnt

def init_worker(repo):
    global PF
    iniciar(repo)
    from nucleo import Perfiles
    PF = Perfiles(os.path.join(repo, 'tools', 'py', 'lotes', 'cajas', 'perfiles_caja.tsv'))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--repo', required=True); ap.add_argument('--ja', required=True, help='raiz con textos/ja'); ap.add_argument('--out', required=True)
    ap.add_argument('--hojas', default=''); ap.add_argument('--excluir', default=''); ap.add_argument('--jobs', type=int, default=2)
    a = ap.parse_args()
    solo = set(x for x in a.hojas.split(',') if x); excl = set(open(a.excluir).read().split()) if a.excluir else set()
    base = os.path.join(a.repo, 'traducciones'); tareas = []
    for hoja, path in hojas_repo(base):
        if solo and hoja not in solo or hoja in excl or excluida(hoja): continue
        tareas.append((a.repo, a.ja, a.out, hoja, path))
    tot = collections.Counter(); por_hoja = {}
    if a.jobs > 1:
        import multiprocessing as mp
        with mp.get_context('fork').Pool(a.jobs, initializer=init_worker, initargs=(a.repo,)) as pool:
            for hoja, c in pool.imap_unordered(procesar_hoja, tareas, chunksize=1): tot.update(c); por_hoja[hoja] = c
    else:
        init_worker(a.repo)
        for t in tareas: hoja, c = procesar_hoja(t); tot.update(c); por_hoja[hoja] = c
    print(dict(tot))
if __name__ == '__main__':
    main()
