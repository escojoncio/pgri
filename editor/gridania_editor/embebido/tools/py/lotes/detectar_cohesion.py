#!/usr/bin/env -S python3 -I
"""Detector de COHESION entre lineas/filas vecinas de un dialogo (no escribe en traducciones/).
Una frase japonesa puede partirse en dos filas (o trozos) consecutivas y el es la cierra con punto o abre la segunda como frase nueva.
Unidad de analisis = LINEA (trozo de una celda). Se emparejan lineas consecutivas de la misma conversacion:
  - dentro de una celda (trozos j, j+1)  [tipo 'intra']
  - ultimo trozo de la celda i con el primero de la celda i+1 [tipo 'inter']; celdas vecinas = filas consecutivas con texto, misma col y mismo hablante
    (quest/cut_scene/opening/dungeon/raid/custom...: hablante por la etiqueta `(-X-)` o por la clave TEXT_* de la col 0) o, en DefaultTalk/NpcYell/Balloon/
    GoldSaucerTalk/CustomTalk, cols consecutivas de la MISMA fila.
Señales (puntuacion; se detecta con >= UMBRAL=3):
  A  ja_i abierto (termina en 、 o forma conectiva: て で が けど し から ので のに と を に は も へ ば たら...) y es_i cerrado con . ! ?     (+5 con 、, +4 resto; -3 si ja_i <= 10 car., -1 si el es cierra con ! o ?)
  A3 ja_i cerrado pero ja_j empieza por particula de continuacion y es_i cerrado                                                                    (+2)
  F  ja_j es un fragmento (termina en particula が を に で と は も antes del 。) y es_i cerrado                                                       (+2)
  B  ja_j empieza por particula de continuacion y es_j empieza como frase nueva (mayuscula, ¡, ¿)                                                  (+2)
  D  es_i cerrado y es_j empieza en minuscula (frase partida por el propio es)                                                                        (+3)
  E  ja_i abierto y es_j empieza como frase nueva (mayuscula, ¡ ¿) aunque es_i no cierre (+1: sola no basta, las listas dan falsos positivos)
  H  es_i acaba en palabra puente (pero, y, que, de, la, en, con, si...) y es_j empieza con mayuscula de palabra comun, con ja_i sin cierre             (+3)
Uso: python3 -I tools/py/lotes/detectar_cohesion.py [--hojas SUBCADENA,...] [--salida F.tsv] [--umbral 3] [--raiz RAIZ]
Salida TSV: hoja,row,sub,col,trozo,tipo,señal,puntuacion,nivel,ja_i,es_i,ja_sig,es_sig,row_sig,sub_sig,col_sig,trozo_sig  + cifras por hoja en stderr."""
import argparse, collections, glob, json, os, re, sys
AQUI = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, AQUI)
import _comun as K, _bloque as B
G = K.G
UMBRAL = 3
MISMA_FILA = {'DefaultTalk', 'NpcYell', 'Balloon', 'GoldSaucerTalk', 'CustomTalk'}
FILAS_SEGUIDAS = ('quest/', 'cut_scene/', 'opening/', 'dungeon/', 'raid/', 'custom/', 'content/', 'story/', 'guild_order/', 'leve/', 'system/')

RE_PREF = re.compile(r'^\(-([^)]*)-\)')
RE_TOK = re.compile(r'<[^<>]*>|\{0x[0-9A-Fa-f]{2}[^}]*\}')
TERMINA_JA = '。！？!?…」』）)♪♡★☆'
RE_ABIERTO_JA = re.compile(r'(、|，|,|て|で|が|けど|けれど|けれども|し|から|ので|のに|と|を|に|は|(?<!か)も|へ|ば|たら|なら|ながら|たり|ても|でも|や|ず|って)$')
RE_CONT_JA = re.compile(r'^(を|まで|ので|のに|ながら|ても)')
RE_FRAG_JA = re.compile(r'(が|を|に|は|と)[。！？!?…」』 ]*$')

def _tok(m):
    x = m.group(0).lower()
    return ' ' if ('newline' in x or x.startswith('{0x10')) else '\u25c6'   # \u25c6 = marcador (nombre, color, icono): ocupa el sitio de una palabra
def plano_ja(t):
    t = RE_TOK.sub(_tok, RE_PREF.sub('', t or ''))
    return re.sub('\u25c6+', '\u25c6', t.replace('\u3000', '')).strip()

def plano_es(t):
    t = RE_TOK.sub(_tok, RE_PREF.sub('', t or ''))
    return re.sub('\u25c6[\u25c6 ]*', '\u25c6', t).strip()

def ja_cerrado(t):
    return bool(t) and t[-1] in TERMINA_JA
def ja_abierto_fuerte(t):
    return bool(t) and not ja_cerrado(t) and bool(RE_ABIERTO_JA.search(t))
def ja_sin_final(t):
    return bool(t) and not ja_cerrado(t)
def ja_continua(t):
    return bool(t) and bool(RE_CONT_JA.match(t)) and not re.match(r'^(.)、\1', t)   # tartamudeo «も、もちろん»
def ja_fragmento(t):
    t = t.strip()
    return bool(t) and bool(RE_FRAG_JA.search(t)) and len(t) >= 3

_CIERRES = '»"\'”’)]*_ '
def es_cerrado(t):
    """termina en . ! ? (tras cierres de comillas/parentesis); los puntos suspensivos no cuentan"""
    t = t.rstrip(_CIERRES)
    if t.endswith('...') or t.endswith('…') or not t: return False
    return t[-1] in '.!?'
_INI = '¡¿«"\'“‘([—-… .'
def es_inicio(t):
    """'mayus' (palabra con mayuscula), 'excl' (¡ ¿), 'minuscula', 'cont' (puntos suspensivos iniciales, comillas «, marcador, digito, otro)"""
    t = t.lstrip()
    if t.startswith('...') or t.startswith('\u2026'): return 'cont'
    if t[:1] in '¡¿': return 'excl'
    if t[:1] in '«"\u201c([': return 'cont'
    s = t.lstrip(_INI)
    if not s: return 'cont'
    if s[0].isupper(): return 'mayus'
    if s[0].islower(): return 'minuscula'
    return 'cont'

INICIOS_FRASE = set('y pero así asi por si ahora entonces el la los las un una unos unas eso esto ese esa yo tú tu te me se lo le les ya no es está hay puedes puede podrías también ni aunque cuando como mientras aquí allí nosotros ustedes usted él ella nos que de a en con para sin más muy todo todos cada otro otra hasta desde'.split())
def es_palabra_comun(t):
    """la primera palabra del es_j es una palabra de inicio de frase (no un nombre propio ni un titulo: «Maestro del gremio», «Primer Reflejo»)"""
    m = re.match(r"[^A-Za-zÁÉÍÓÚÑáéíóúñü]*([A-Za-zÁÉÍÓÚÑáéíóúñü]+)", t)
    return bool(m) and m.group(1).lower() in INICIOS_FRASE

PALABRAS_PUENTE = set('pero y e o u ni que de del la el los las un una unos unas a al en con por para si como aunque sino cuando mientras se su sus mi mis tu tus lo le les sin sobre entre hasta desde porque pues'.split())
def es_acaba_en_puente(t):
    m = re.search(r"([A-Za-zÁÉÍÓÚÑáéíóúñü]+)[^A-Za-zÁÉÍÓÚÑáéíóúñü]*$", t)
    return bool(m) and m.group(1).lower() in PALABRAS_PUENTE and not t.rstrip(_CIERRES).endswith(('.', '!', '?'))

def puntuar(ji, ei, jj, ej):
    """-> (puntos, [señales]) para el par de lineas (i, j) ya en plano"""
    sg = []; p = 0
    cerr = es_cerrado(ei); ini = es_inicio(ej)
    ab = ja_abierto_fuerte(ji); sf = ja_sin_final(ji); cont = ja_continua(jj); frag = ja_fragmento(jj)
    if cerr and ab:
        v = 5 if ji[-1] in '、，,' else 4
        if len(ji) <= 10: v -= 3          # saludo / vocativo / interjeccion corta: cortar ahi es natural
        elif ei.rstrip(_CIERRES)[-1] in '?!': v -= 1   # el es cierra con ! o ?: reestructurar suele ser legitimo
        if v >= 1: p += v; sg.append('A')
    elif cerr and ja_cerrado(ji) and cont:
        p += 2; sg.append('A3')
    if cerr and frag and 'A' not in sg and 'A2' not in sg:
        p += 2; sg.append('F')
    if cont and ini in ('mayus', 'excl'):
        p += 2; sg.append('B')
    if cerr and ini == 'minuscula' and not ei.rstrip().endswith(('»', '\u201d', '"')):   # «...!» y minuscula = la frase sigue tras la cita
        p += 3; sg.append('D')
    if (ab and ini == 'mayus' and not cerr and not ei.rstrip(_CIERRES).endswith(('...', '\u2026', ':')) and es_palabra_comun(ej)
            and ji[-1] in '、，,'):
        p += 1; sg.append('E')
    if es_acaba_en_puente(ei) and ini == 'mayus' and es_palabra_comun(ej) and not ja_cerrado(ji) and not ei.rstrip().endswith(('--', '\u2014', '-')):
        p += 3; sg.append('H')
    return p, sg

# ------------------------------------------------------------------ carga
def listar_hojas(raiz):
    base = os.path.join(raiz, 'traducciones'); out = []
    for p in glob.glob(os.path.join(base, '**', '*.jsonl'), recursive=True):
        h = os.path.relpath(p, base)[:-6]
        if h in MISMA_FILA or h.startswith(FILAS_SEGUIDAS): out.append(h)
    return sorted(out)

def clave_hablante(txt):
    """hablante a partir de la clave TEXT_* de la col 0 (o None si no es un dialogo)"""
    if not txt or not txt.startswith('TEXT_'): return None
    t = txt.split('_')
    if re.fullmatch(r'\d+', t[-1]) and len(t) >= 3 and re.fullmatch(r'\d{3}', t[-2]) and t[-3] and not t[-3].isdigit(): return t[-3]   # SPEAKER_000_142
    if not t[-1].isdigit() and len(t) >= 3 and t[-2].isdigit(): return t[-1]                                                              # VOICEMAN_02200_000010_THANCRED
    if t[-1] in ('TODO',) or 'TODO' in t: return None
    return None

def cargar_celdas(raiz, hoja):
    """-> {(row,sub,col): {'ja': [trozos planos], 'es': [trozos planos], 'hab': str|None, 'raw_es': es}} (solo texto, col != 0)"""
    ja = G.leer_ja(raiz, hoja)
    if ja is None: return {}
    ruta = os.path.join(raiz, 'traducciones', *hoja.split('/')) + '.jsonl'
    ult = {}
    with open(ruta, encoding='utf-8') as f:
        for l in f:
            if l.strip():
                j = json.loads(l); ult[(j['row'], j.get('sub'), j['col'])] = j
    out = {}
    for k, j in ult.items():
        if k[2] == 0 or j.get('estado') == 'dudosa': continue
        tj = ja.get(k)
        if not tj or not G.tiene_cjk(tj[0]): continue
        es = j['es']
        if isinstance(es, list):
            d = B.descomponer(tj[0], tj[1])
            if d is None or d['tipo'] != 'simple' or len(d['ja']) != len(es): continue
            jt = [plano_ja(x) for x in d['ja']]; et = [plano_es(x) for x in es]
        else:
            try: tk = G.tokenizar_volcado(tj[0], tj[1])
            except Exception: tk = tj[0]
            jt = [plano_ja(tk)]; et = [plano_es(es)]
        k0 = ja.get((k[0], k[1], 0))
        out[k] = {'ja': jt, 'es': et, 'hab': clave_hablante(k0[0]) if k0 else None, 'etq': (RE_PREF.match(tj[0]) or [None, None])[1] if isinstance(tj[0], str) else None}
    return out

def secuencias(hoja, celdas):
    """-> lista de secuencias de claves (conversaciones) en orden de lectura"""
    ks = sorted(celdas, key=lambda k: (k[0], -1 if k[1] is None else k[1], k[2]))
    seqs = []
    if hoja in MISMA_FILA:
        por = collections.OrderedDict()
        for k in ks: por.setdefault((k[0], k[1]), []).append(k)
        return [v for v in por.values() if len(v) > 1]
    por_col = collections.defaultdict(list)
    for k in ks: por_col[k[2]].append(k)
    for col, lst in por_col.items():
        cur = []
        for k in lst:
            if cur:
                a, b = celdas[cur[-1]], celdas[k]
                if a['etq'] and b['etq']: ok = a['etq'] == b['etq']
                elif a['hab'] and b['hab']: ok = a['hab'] == b['hab']
                else: ok = bool((a['etq'] or a['hab']) and (b['etq'] or b['hab']))
                if not ok: seqs.append(cur); cur = []
            cur.append(k)
        seqs.append(cur)
    return [s for s in seqs if len(s) > 1]

def pares(celdas, seq):
    """genera (ki, ti, kj, tj) de lineas consecutivas dentro de la secuencia"""
    for n, k in enumerate(seq):
        c = celdas[k]
        for t in range(len(c['ja']) - 1): yield k, t, k, t + 1, 'intra'
        if n + 1 < len(seq):
            k2 = seq[n + 1]; yield k, len(c['ja']) - 1, k2, 0, 'inter'

def detectar_hoja(raiz, hoja, umbral=UMBRAL, celdas=None):
    celdas = celdas if celdas is not None else cargar_celdas(raiz, hoja)
    out = []; tot = 0
    for seq in secuencias(hoja, celdas):
        for ki, ti, kj, tj, tipo in pares(celdas, seq):
            ci, cj = celdas[ki], celdas[kj]
            ji, ei, jj, ej = ci['ja'][ti], ci['es'][ti], cj['ja'][tj], cj['es'][tj]
            if not ji or not jj or not ei or not ej: continue
            tot += 1
            p, sg = puntuar(ji, ei, jj, ej)
            if p >= umbral: out.append({'hoja': hoja, 'k': ki, 't': ti, 'k2': kj, 't2': tj, 'tipo': tipo, 'señal': '+'.join(sg), 'p': p, 'ja_i': ji, 'es_i': ei, 'ja_j': jj, 'es_j': ej})
    return out, tot

def detectar(raiz, hojas=None, umbral=UMBRAL):
    res = []; cif = collections.OrderedDict()
    for h in (hojas if hojas is not None else listar_hojas(raiz)):
        try: o, n = detectar_hoja(raiz, h, umbral)
        except FileNotFoundError: continue
        res += o; cif[h] = (n, len(o))
    return res, cif

def nivel(d):
    """alto = el propio es se contradice (D: minuscula tras cierre; H: acaba en preposicion/conjuncion y sigue en mayuscula); medio = solo el ja continua (A)"""
    return 'alto' if any(x in d['señal'].split('+') for x in ('D', 'H', 'F')) else 'medio'
def _l(t): return t.replace('\t', ' ').replace('\n', ' / ').replace('\r', '')
def fila_tsv(d):
    k, k2 = d['k'], d['k2']
    f = lambda x: '' if x is None else str(x)
    return '\t'.join([d['hoja'], str(k[0]), f(k[1]), str(k[2]), str(d['t']), d['tipo'], d['señal'], str(d['p']), nivel(d), _l(d['ja_i']), _l(d['es_i']),
                      _l(d['ja_j']), _l(d['es_j']), str(k2[0]), f(k2[1]), str(k2[2]), str(d['t2'])])
CAB = 'hoja\trow\tsub\tcol\ttrozo\ttipo\tseñal\tpuntuacion\tnivel\tja_i\tes_i\tja_sig\tes_sig\trow_sig\tsub_sig\tcol_sig\ttrozo_sig'

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--hojas'); ap.add_argument('--salida'); ap.add_argument('--cifras'); ap.add_argument('--umbral', type=int, default=UMBRAL); ap.add_argument('--raiz', default=K.RAIZ)
    a = ap.parse_args(argv)
    hs = listar_hojas(a.raiz)
    if a.hojas: sub = a.hojas.split(','); hs = [h for h in hs if any(s in h for s in sub)]
    res, cif = detectar(a.raiz, hs, a.umbral)
    res.sort(key=lambda d: (-d['p'], d['hoja'], d['k'][0], d['t']))
    if a.salida:
        with open(a.salida, 'w', encoding='utf-8', newline='\n') as f:
            f.write(CAB + '\n')
            for d in res: f.write(fila_tsv(d) + '\n')
    if a.cifras:
        with open(a.cifras, 'w', encoding='utf-8', newline='\n') as f:
            f.write('hoja\tpares\tdetectados\talto\n')
            alto = collections.Counter(d['hoja'] for d in res if nivel(d) == 'alto')
            for h, (n, d) in cif.items():
                if d: f.write('%s\t%d\t%d\t%d\n' % (h, n, d, alto[h]))
    fam = collections.defaultdict(lambda: [0, 0])
    for h, (n, d) in cif.items():
        e = fam[h.split('/')[0]]; e[0] += n; e[1] += d
    sys.stderr.write('detectados %d en %d pares\n' % (len(res), sum(v[0] for v in fam.values())))
    for fm, (n, d) in sorted(fam.items()): sys.stderr.write('  %-26s pares %7d  detectados %5d\n' % (fm, n, d))
    return res

if __name__ == '__main__': main()
