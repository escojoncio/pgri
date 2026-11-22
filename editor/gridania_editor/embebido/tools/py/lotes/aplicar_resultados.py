#!/usr/bin/env -S python3 -I
"""Aplica a traducciones/<Hoja>.jsonl los resultados de una retraduccion `gen_lote_fr.py` (EDICION IN SITU de la linea corpus; no anade lineas).
Uso: python3 -I tools/py/lotes/aplicar_resultados.py --nombre X [--hojas H1,H2] [--lotes DIR] [--informe F] [--dry-run]
     python3 -I tools/py/lotes/aplicar_resultados.py --bloque N [--hojas H1,H2] [--lotes DIR] [--informe F] [--dry-run]
  --bloque N   recorre DIR/bloqueN_manifest.tsv (DIR por defecto trabajo/lotes/bN) y aplica los lotes bN_<Hoja>_NN que tengan res_fr_bN_<Hoja>_NN.jsonl (salida de
               expandir_resultados.py); los lotes sin resultado se ignoran (se cuentan). Las reutilizadas (reutilizadas_fr_bN_<Hoja>_NN.jsonl) se aplican siempre, tengan o no
               resultado. Copias: solo si su fila origen tiene resultado valido (en este u otro lote de la misma pasada). Una sola escritura por hoja aunque tenga varios lotes.
               Backups en trabajo/lotes/bak/. Informe por defecto DIR/informe_aplicar_bN.txt.
  --nombre X   lote a aplicar (por defecto piloto_1): lee en --lotes (por defecto trabajo/lotes) lote_fr_X.jsonl, reutilizadas_fr_X.jsonl y
               res_fr_X_<Hoja>.jsonl ({"hoja","row","sub","col","es","estado","h","origen":"fr-ja-retrad"}, una linea por fila; si una clave se repite gana la ultima).
  --hojas      limitar a esas hojas (por defecto: todas las del lote, copias y reutilizadas).
  (--solo-traducidas: obsoleto, sin efecto: un resultado con estado "dudosa" SIEMPRE se rechaza como FALLO ESTADO_DUDOSA; regla «sin dudosas».)
  --dry-run    solo informa (no escribe traducciones/, ni backup, ni informe salvo --informe).
  --informe F  ruta del informe (por defecto <lotes>/informe_aplicar_X.txt; solo si no es --dry-run).
Que se aplica (cada una sustituye la linea EN SU SITIO por {"row","sub","col","es","estado","h","origen"}):
  - resultados del traductor: solo si pasan (nº de trozos == len(ja del lote), sin trozos vacios [salvo ja sin letras], sin CJK/U+3000/anchura completa,
    glifos PUA U+E000-U+F8FF / caracteres de control / marcadores <Nombre> de cada trozo `es` == los del trozo ja (multiconjunto; si no, fila fallida INTOCABLES),
    h == h del lote, estado traducida [dudosa = FALLO ESTADO_DUDOSA, no se aplica], es lista de str). origen = "fr-ja-retrad".
  - copias (campo `copias` del lote): misma `es`/`estado` que su fila origen (si esta pasa), con su propio h/row/sub/col, origen "fr-ja-retrad".
  - reutilizadas (reutilizadas_fr_X.jsonl): tal cual (es/estado/h/origen del fichero), tras las mismas comprobaciones de es (estado traducida|revisada|dudosa;
    el nº de trozos debe coincidir con el `es` actual de la linea).
Localizacion de la linea: pista `linea` (1-based) si su row/sub/col coincide; si no, la ultima linea de esa clave con origen "corpus" o estado "dudosa". Se pueden
  sustituir lineas con origen corpus O con estado dudosa; si la linea no es ninguna de las dos: igual al resultado -> "ya aplicada" (idempotente); distinta -> se salta y
  se informa (nunca se pisa una retraduccion/edicion previa).
ALINEACION (no se aplica la fila si falla digitos o proporcion; informe `FALLO ... ALINEACION` con la causa y recuento por causa): ALIN_DIGITOS = el multiconjunto de digitos de los trozos
  ja (sin los de marcadores <..>/{0x..}; anchura completa = ASCII) != el de los trozos es; ALIN_GLOSARIO (SOLO AVISO: se cuenta en el resumen y la fila se aplica) = un termino de data/glosario-propio.tsv (estado ok|fijo; sin los contenidos en
  otro termino mas largo presente) cuyo ja esta en la fila no tiene su es en el espanol (sin mayusculas ni articulo inicial; si el ja del termino tiene < 3 car. solo AVISO en el fichero
  del informe); ALIN_PROPORCION = len(es)/len(ja) de un trozo con ja >= 10 car. fuera de [0.4, 8]. Solo en resultados del traductor (copias heredan; reutilizadas no llevan ja).
BLOQUE 3 (lineas con `fuente:"fr"`, ja latino sin CJK, fuente = el frances): ALIN_DIGITOS compara los digitos de `es` con los del ja O los del fr; ALIN_GLOSARIO (aviso) usa el glosario fr de la fila;
  sin proporcion; no se exige CJK en ja. Las B_AUTO (reutilizadas_fr_b3_auto.jsonl, origen fr-ja-retrad) pasan por las comprobaciones de las reutilizadas + construir_dat.evaluar_cadena.
Escritura: un unico escritor por hoja; backup previo en trabajo/lotes/bak/<Hoja>.<fecha>.jsonl; fichero temporal + rename atomico; el resto de lineas y el \\n final
se conservan byte a byte. Idempotente: segunda pasada = 0 cambios (no se reescribe ni se hace backup). rc!=0 si hay filas fallidas.
Solo biblioteca estandar (+ segmentar.py del repo)."""
import argparse, collections, csv, datetime, hashlib, json, os, re, sys, unicodedata
AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.environ.get('LOTES_RAIZ') or os.path.join(AQUI, '..', '..', '..'))   # LOTES_RAIZ: raiz alternativa (pruebas)
sys.path.insert(0, os.path.join(AQUI, '..'))
import segmentar as G
sys.path.insert(0, AQUI)
import _bloque as B
import normalizar_signos_japoneses as NSJ
from digitos_equiv import digitos_discrepantes   # equivalencias kanji/romano/cifra (compartido con auditar_glosario_items)

ESTADOS_RES = ('traducida',)
ESTADOS_REUT = ('traducida', 'revisada')
ORIGEN = 'fr-ja-retrad'
FULL_CH = [chr(c) for c in range(0xFF01, 0xFF5F) ] + ['…', '‥']   # U+2026 / U+2025 tambien son ERROR (orden 2026-11-08: puntos suspensivos SIEMPRE '...' ASCII, nunca …)   # ！-～ (anchura completa FF01-FF5E; sin exenciones: ～ -> ~, ver normalizar_signos_japoneses.py)

PUA_RE = re.compile('[\ue000-\uf8ff]')

def intocables(t):
    """multiconjunto de lo no traducible de un trozo: glifos PUA (U+E000-U+F8FF), caracteres de control y marcadores <Nombre>/{0xNN"""
    return collections.Counter(PUA_RE.findall(t) + [c for c in t if G.es_control(c)] + G.MARCADOR_RE.findall(t))

GENDER_MACRO_RE = re.compile(r'<Gender>([^<]+)<GenderElse>([^<]+)<GenderEnd>')

def _solo_genero_extra(a, b, t):
    """--permitir-genero: la unica diferencia es que `t` (es) trae macros <Gender>fem<GenderElse>masc<GenderEnd> bien formadas (ramas no vacias, sin '<' ni
    saltos, sin anidar) que el ja no marca. Nada falta y sobran exactamente 3 marcadores por macro; el resto de intocables es identico."""
    if a - b: return False
    ex = b - a
    n = len(GENDER_MACRO_RE.findall(t))
    if n == 0 or any(c not in ('<Gender>', '<GenderElse>', '<GenderEnd>') for c in ex): return False
    if not (ex['<Gender>'] == ex['<GenderElse>'] == ex['<GenderEnd>'] == n): return False
    return all('\n' not in x and '\n' not in y for x, y in GENDER_MACRO_RE.findall(t)) and t.count('<Gender>') == n

def _sin_num(c):
    out = collections.Counter()
    for k, v in c.items(): out[re.sub(r'^<(\w+)#\d+>$', r'<\1>', k) if isinstance(k, str) else k] += v
    return out

def dif_intocables(ja, es, permitir_genero=False, permitir_lf=False):
    """trozo a trozo (misma longitud): motivos 'INTOCABLES trozo i: faltan [...] sobran [...]' si no coinciden los multiconjuntos"""
    mal = []
    for i, (j, t) in enumerate(zip(ja, es)):
        a, b = _sin_num(intocables(j)), _sin_num(intocables(t))   # <NewLine#2> del ja == <NewLine> del es (celdas «cadena»): se compara el recuento por nombre de marca
        if permitir_lf and b['<NewLine>'] > a['<NewLine>']: b = b - collections.Counter({'<NewLine>': b['<NewLine>'] - a['<NewLine>']})   # <NewLine> extra del reflujo (pgri admite saltos extra fuera de Run/macro)
        if permitir_lf and b['\n'] > a['\n']: b = b - collections.Counter({'\n': b['\n'] - a['\n']})   # saltos reales anadidos por el reflujo
        if a != b:
            if permitir_genero and _solo_genero_extra(a, b, t): continue
            f = sorted((a - b).elements()); x = sorted((b - a).elements())
            mal.append('INTOCABLES trozo %d: faltan %s sobran %s' % (i, ['U+%04X' % ord(c) if len(c) == 1 else c for c in f], ['U+%04X' % ord(c) if len(c) == 1 else c for c in x]))
    return mal

# ---------------------------------------------------------------- alineacion (texto en la fila equivocada aunque el nº de trozos coincida)
RATIO_MIN, RATIO_MAX, TROZO_MIN_PROP, TERM_MIN = 0.4, 8.0, 10, 3
MARC_DIG_RE = re.compile(r'\{0x[0-9A-Fa-f]{2}[^}]*\}|<[^<>]*>')
ARTICULO_RE = re.compile(r'^(?:el|la|los|las|un|una|unos|unas)\s+')

def digitos(trozos):
    """multiconjunto de digitos (anchura completa -> ASCII) de los trozos, sin contar los de marcadores <...> / {0x..}"""
    c = collections.Counter()
    for t in trozos:
        for ch in MARC_DIG_RE.sub('', t):
            d = unicodedata.digit(ch, None) if ch.isdigit() else None
            if d is not None: c[str(d)] += 1
    return c

def norm_es(t):
    t = t.casefold().strip()
    return ARTICULO_RE.sub('', t)

def cargar_glosario_alin():
    """{ja: es} de data/glosario-propio.tsv con estado ok|fijo (primera entrada de cada ja)"""
    g = {}
    ruta = os.path.join(RAIZ, 'data', 'glosario-propio.tsv')
    if not os.path.exists(ruta): return g
    with open(ruta, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f, delimiter='\t', quoting=csv.QUOTE_NONE):
            ja = (r.get('ja') or '').strip(); es = (r.get('es') or '').strip()
            if ja and es and ja not in g and (r.get('estado') or 'ok') in ('ok', 'fijo'): g[ja] = es
    return g

def terminos_en(trozos, glos, longitudes):
    """terminos del glosario cuyo ja aparece en algun trozo, sin los contenidos en otro termino presente mas largo"""
    pres = set()
    for t in trozos:
        n = len(t)
        for L in longitudes:
            if L > n: break
            for i in range(n - L + 1):
                if t[i:i + L] in glos: pres.add(t[i:i + L])
    return [x for x in pres if not any(x != y and x in y for y in pres)]

def alineacion(ja, es, glos, longitudes, fr=None):
    """-> (causas de fallo [ALIN_DIGITOS + detalle], avisos [ALIN_PROPORCION (no bloquea); ALIN_GLOSARIO; ALIN_GLOSARIO_CORTO si ja < TERM_MIN car.]). ja y es: listas de trozos (misma longitud)"""
    fallos = []; avisos = []
    a, b = digitos(ja), digitos(es)
    if a != b:
        # 五一式=51, 第三次=3.ª, G5/7世=V/VII: misma cifra con otra grafia no discrepa; si falta o sobra un numero de verdad sigue siendo ALIN_DIGITOS
        fa, so = digitos_discrepantes(MARC_DIG_RE.sub('', ' '.join(ja)), MARC_DIG_RE.sub('', ' '.join(es)),
                                    MARC_DIG_RE.sub('', fr if isinstance(fr, str) else ' '.join(x or '' for x in (fr or []))))   # fr: si trae los mismos digitos que el es, manda (Stigma-1, 2.0, 8bit)
        if fa or so: fallos.append(('ALIN_DIGITOS', 'faltan %s sobran %s' % (sorted(fa), sorted(so))))
    es_txt = norm_es(' '.join(es)); es_cf = ' '.join(es).casefold()
    mal = []; corto = []
    for t in sorted(terminos_en(ja, glos, longitudes)):
        e = norm_es(glos[t])
        if e and e not in es_cf and e not in es_txt: (corto if len(t) < TERM_MIN else mal).append('%s=%s' % (t, glos[t]))
    if mal: avisos.append(('ALIN_GLOSARIO', 'sin su es: ' + ', '.join(mal[:6])))   # AVISO: la fila se aplica
    if corto: avisos.append(('ALIN_GLOSARIO_CORTO', 'sin su es: ' + ', '.join(corto[:6])))
    for i, (j, t) in enumerate(zip(ja, es)):
        if len(j) >= TROZO_MIN_PROP:
            r = len(t) / len(j)
            if not (RATIO_MIN <= r <= RATIO_MAX): avisos.append(('ALIN_PROPORCION', 'trozo %d: len es/ja = %d/%d = %.2f' % (i, len(t), len(j), r))); break   # AVISO (decision del director): ya no bloquea; empujaba a rellenar
    return fallos, avisos

def alineacion_fr(L, es):
    """BLOQUE 3 (fuente fr: el ja es latino, la fuente es el frances). -> (fallos, avisos). ALIN_DIGITOS: los digitos de `es` deben ser los del ja O los del fr (lista alineada o cadena);
    no se exige CJK ni proporcion; AVISO ALIN_GLOSARIO si falta el `es` de un termino fr del glosario de la fila."""
    fallos = []; avisos = []
    fr = L.get('fr'); frs = fr if isinstance(fr, list) else ([fr] if isinstance(fr, str) else [])
    b = digitos(es)
    if b != digitos(L['ja']) and b != digitos(frs):
        a = digitos(frs) if frs else digitos(L['ja'])
        fallos.append(('ALIN_DIGITOS', 'faltan %s sobran %s (ref. %s)' % (sorted((a - b).elements()), sorted((b - a).elements()), 'fr' if frs else 'ja')))
    es_cf = ' '.join(es).casefold(); es_txt = norm_es(' '.join(es)); mal = []
    for g in L.get('glosario', ()):
        e = norm_es(g.get('es', ''))
        if e and e not in es_cf and e not in es_txt: mal.append('%s=%s' % (g.get('fr') or g.get('ja'), g.get('es')))
    if mal: avisos.append(('ALIN_GLOSARIO', 'sin su es: ' + ', '.join(mal[:6])))
    return fallos, avisos

# ---------------------------------------------------------------- excepciones auditadas del validador (falsos positivos revisados)
def _es_nombre_glosario(t, L):
    """Bloque 6: un trozo es EXACTAMENTE un nombre completo del glosario (estado ok|fijo, entre los del `glosario` prefiltrado de la fila), salvo puntuacion/comillas/espacios en los extremos: no se acorta (excepcion de LONGITUD)."""
    core = re.sub(r'^[^\w]+|[^\w]+$', '', t.strip()).casefold()
    if not core: return False
    return any(g.get('estado') in ('ok', 'fijo') and (g.get('es') or '').strip().casefold() == core for g in (L.get('glosario') or []))

EXC_FICHERO = os.path.join(RAIZ, 'trabajo', 'lotes', 'excepciones_validador.tsv')
def cargar_excepciones(ruta=None):
    """{(hoja,row,sub,col): {codigo}} de trabajo/lotes/excepciones_validador.tsv (hoja,row,sub,col,motivo; el CODIGO exento es la 1.ª palabra del motivo: ALIN_DIGITOS|ALIN_PROPORCION|TROZO_VACIO|SIN_TEXTO_TRADUCIDO, seguida de ':' y la razon). Solo esas claves y ese codigo quedan exentos."""
    ruta = ruta or EXC_FICHERO; out = collections.defaultdict(set)
    if not os.path.exists(ruta): return out
    with open(ruta, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f, delimiter='\t', quoting=csv.QUOTE_NONE):
            cod = re.split(r'[:\s]', (r.get('motivo') or '').strip(), 1)[0]
            if r.get('hoja') and cod: out[(r['hoja'], str(r['row']), r.get('sub') or '', str(r['col']))].add(cod)
    return out
EXCEPCIONES = cargar_excepciones()
def exento(hoja, k, codigo):
    """k = (row,sub,col)"""
    return codigo in EXCEPCIONES.get((hoja, str(k[0]), '' if k[1] is None else str(k[1]), str(k[2])), ())

ORIGENES_VALIDOS = ('fr-ja-retrad', 'reutilizada', 'fr-media', 'sesion', 'previo-ja')   # = construir_dat.ORIGENES_VALIDOS

def dumps(r, estricto=True):
    """serializa una fila de traducciones/; ASERCION: toda fila escrita lleva `origen` de la lista blanca (nunca filas de origen desconocido)"""
    assert not estricto or r.get('origen') in ORIGENES_VALIDOS, 'fila sin origen valido: %r' % (r,)
    return json.dumps(r, ensure_ascii=False, separators=(',', ':'))
def clave(j): return (j.get('row'), j.get('sub'), j.get('col'))
def kstr(h, k): return '%s %s/%s/%s' % (h, k[0], k[1], k[2])

def leer_jsonl(ruta):
    out = []
    with open(ruta, encoding='utf-8') as f:
        for n, l in enumerate(f, 1):
            if l.strip():
                try: out.append((n, json.loads(l)))
                except Exception: out.append((n, None))
    return out

def mal_es(es, ja=None):
    """motivos por los que `es` no pasa (lista vacia = OK). ja = trozos japoneses del lote (None: no se comprueba nº de trozos ni vacios)"""
    if not isinstance(es, list) or not es or not all(isinstance(t, str) for t in es): return ['ES_NO_LISTA_DE_STR']
    mal = []
    if ja is not None:
        if len(es) != len(ja): return ['N_TROZOS es=%d ja=%d' % (len(es), len(ja))]
        if any(not t.strip() and not G.vacio_permitido(j) for j, t in zip(ja, es)): mal.append('TROZO_VACIO')
    elif any(not t.strip() for t in es): mal.append('TROZO_VACIO')
    for t in es:
        if '　' in t: mal.append('U+3000'); break
        if any(c in t for c in FULL_CH): mal.append('ANCHURA_COMPLETA'); break
        if G.tiene_cjk(t): mal.append('CJK_EN_ES'); break
    if ja is not None:   # regla absoluta: castellano de España, jamás latinismos (solo errores; «usted(es)» con ja formal es aviso)
        try:
            import latinismos as LAT
            for _n, _c, _f in LAT.detectar(es, ja):
                if _n == 'error': mal.append('LATINISMO %s: %s' % (_c, _f)); break
        except ImportError: pass
        try:   # SIMBOLOGIA objetiva (¡/! ¿/? ( ) « » y rachas agrupadas) sobre la celda unida; ver auditar_simbologia.objetivas_puerta
            import auditar_simbologia as _AS
            _o = _AS.objetivas_puerta(ja, es)
            if _o: mal.append('SIMBOLOGIA ' + ','.join(_o))
        except ImportError: pass
    return mal

class Hoja:
    """traducciones/<hoja>.jsonl en memoria: lineas crudas (split por \\n, sin perder nada) + indice clave -> numeros de linea"""
    def __init__(self, hoja):
        self.hoja = hoja; self.ruta = os.path.join(RAIZ, 'traducciones', hoja + '.jsonl')
        if os.path.exists(self.ruta):
            with open(self.ruta, encoding='utf-8', newline='') as f: self.texto = f.read()
        else: self.texto = ''   # hoja sin fichero (bloque 2: filas nuevas)
        self.partes = self.texto.split('\n')   # ultimo elemento '' si el fichero acaba en \n
        self.json = {}; self.idx = collections.defaultdict(list)
        for n, p in enumerate(self.partes, 1):
            if not p.strip(): continue
            try: j = json.loads(p)
            except Exception: continue
            self.json[n] = j; self.idx[clave(j)].append(n)

    def localizar(self, k, hint):
        """-> (nº linea | None, motivo): pista si coincide la clave; si no, la ultima linea de la clave con origen corpus o estado dudosa; si no, la ultima de la clave"""
        if hint in self.json and clave(self.json[hint]) == k: return hint, None
        ls = self.idx.get(k)
        if not ls: return None, 'SIN_LINEA'
        corp = [n for n in ls if self.json[n].get('origen') == 'corpus' or self.json[n].get('estado') == 'dudosa']
        return (corp[-1] if corp else ls[-1]), None

def reemplazable(cur):
    """una linea se puede sustituir si es corpus (ingles) o esta dudosa"""
    return cur.get('origen') == 'corpus' or cur.get('estado') == 'dudosa'

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--nombre', default='piloto_1'); ap.add_argument('--hojas'); ap.add_argument('--lotes'); ap.add_argument('--bloque', type=int)
    ap.add_argument('--unir-trozos', action='store_true', help='une con espacio los trozos es sobrantes cuando el ja tiene un solo trozo (reparar_trozos.py)'); ap.add_argument('--reponer', action='store_true', help='repone de forma determinista los intocables (PUA/controles/marcadores) que faltan en es antes de validar'); ap.add_argument('--no-escribir', help='hojas (H1,H2) cuyas lineas NO se escriben aunque se validen (p. ej. hojas de otro bloque en curso)'); ap.add_argument('--sin-cajas', action='store_true', help='no ejecutar la puerta de cajas (corregir_cajas) tras aplicar'); ap.add_argument('--informe'); ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--solo-traducidas', action='store_true', help='obsoleto, sin efecto')
    ap.add_argument('--permitir-genero', action='store_true', help='admite macros <Gender>fem<GenderElse>masc<GenderEnd> bien formadas que el ja no trae (norma de genero del jugador); el resto de intocables sigue exacto')
    a = ap.parse_args()
    bloque = a.bloque
    d = os.path.abspath(a.lotes) if a.lotes else os.path.join(RAIZ, 'trabajo', 'lotes', 'b%d' % bloque) if bloque else os.path.join(RAIZ, 'trabajo', 'lotes')
    filtro = {x for x in a.hojas.split(',') if x} if a.hojas else None
    nombre = 'b%d' % bloque if bloque else a.nombre
    # unidades: (filas {clave: lote}, ruta de resultados, hoja) ; reut: reutilizadas
    unidades = []; lote = {}; reut = []; lotes_sin_res = []; n_lotes = 0
    if bloque:
        f_man = os.path.join(d, 'bloque%d_manifest.tsv' % bloque)
        if not os.path.exists(f_man): ap.error('no existe %s' % f_man)
        with open(f_man, encoding='utf-8') as f: man = [l.rstrip('\n').split('\t')[:2] for l in list(f)[1:] if l.strip()]
        for nl, hoja in man:
            if filtro and hoja not in filtro: continue
            f_l = os.path.join(d, 'lote_fr_%s.jsonl' % nl); f_r = os.path.join(d, 'reutilizadas_fr_%s.jsonl' % nl)
            filas = {}
            try: lineas_lote = B.fusionar_partes(B.cargar_lote(f_l))   # complejas: estructura de _est.jsonl; partes (>400 car.) fusionadas
            except ValueError as e: ap.error('%s: JSON invalido (%s)' % (f_l, e))
            for r in lineas_lote:
                if r.get('_incompleta'): ap.error('%s: fila %s con partes incompletas' % (f_l, clave(r)))
                filas[(r['hoja'],) + clave(r)] = r
            lote.update(filas); n_lotes += 1
            if os.path.exists(f_r): reut += [r for n, r in leer_jsonl(f_r) if r is not None]
            f_res = os.path.join(d, 'res_fr_%s.jsonl' % nl)
            if os.path.exists(f_res): unidades.append((filas, f_res, hoja))
            elif filas: lotes_sin_res.append(nl)
    else:
        f_lote = os.path.join(d, 'lote_fr_%s.jsonl' % nombre); f_reut = os.path.join(d, 'reutilizadas_fr_%s.jsonl' % nombre)
        if not os.path.exists(f_lote): ap.error('no existe %s' % f_lote)
        for n, r in leer_jsonl(f_lote):
            if r is None: ap.error('%s linea %d: JSON invalido' % (f_lote, n))
            lote[(r['hoja'],) + clave(r)] = r
        reut = [r for n, r in leer_jsonl(f_reut) if r is not None] if os.path.exists(f_reut) else []
        hojas = sorted({k[0] for k in lote} | {c['hoja'] for r in lote.values() for c in r.get('copias', ())} | {r['hoja'] for r in reut})
        if filtro: hojas = [h for h in hojas if h in filtro]
        for h in hojas: unidades.append(({k: v for k, v in lote.items() if k[0] == h}, os.path.join(d, 'res_fr_%s_%s.jsonl' % (nombre, h)), h))
    ok_hoja = (lambda h: h in filtro) if filtro else (lambda h: True)
    reut = [r for r in reut if ok_hoja(r['hoja'])]
    fallos = []      # (hoja, clave, tag, detalle)
    cambios = collections.defaultdict(dict)   # hoja -> {clave: (registro nuevo, pista linea, tag)}
    pendientes = 0; ok_res = {}; ja_cache = {}
    C = None
    if bloque and bloque >= 2:   # bloque 2+: cada resultado se valida ademas con construir_dat.evaluar_cadena (filtro de tokens, literales, simulacion de ExdPatcher)
        import construir_dat as C
    glos_alin = cargar_glosario_alin(); long_alin = sorted({len(x) for x in glos_alin}); avisos = []; cnt_alin = collections.Counter()
    # 1) resultados del traductor
    for filas, fr, h in unidades:
        res = {}
        if os.path.exists(fr):
            for n, r in leer_jsonl(fr):
                if r is None: fallos.append((h, ('?', '?', '?'), 'JSON', '%s linea %d' % (os.path.basename(fr), n))); continue
                res[(r.get('hoja', h), r.get('row'), r.get('sub'), r.get('col'))] = r   # la ultima gana
        for (hh, *k), L in filas.items():
            k = tuple(k); r = res.pop((hh,) + k, None); h = hh
            if r is None: pendientes += 1; continue
            if r.get('estado') == 'dudosa':
                fallos.append((h, k, 'ESTADO_DUDOSA', 'resultado dudosa: no se aplica (sin dudosas: resolver con ja + fr + glosario)')); continue
            if isinstance(r.get('es'), (list, str)): r = dict(r, es=NSJ.normalizar(r['es']))   # signos japoneses/anchura completa -> UTF-8 espanol (norma 2026-11-05)
            mal = []
            if r.get('hoja', h) != h: mal.append('HOJA')
            cplx = L.get('tipo') == 'complejo'
            m_es = B.mal_complejo(L, r.get('es')) if cplx else mal_es(r.get('es'), L['ja'])
            if a.unir_trozos and not cplx:   # N_TROZOS sistematico: ja de 1 trozo y es partido en varios (reparar_trozos.py)
                import reparar_trozos as RT
                nuevo, rep = RT.unir_trozos(L['ja'], r.get('es'))
                if rep: r = dict(r, es=nuevo)
            if a.reponer and isinstance(r.get('es'), list) and len(r['es']) == len(L['ja']):   # repone de forma determinista glifos PUA/controles/marcadores que faltan (reponer_intocables.py)
                import reponer_intocables as RI
                nuevo, rep, nores = RI.reponer(L['ja'], r['es'])
                if rep: r = dict(r, es=nuevo)
            m_es = B.mal_complejo(L, r.get('es')) if cplx else mal_es(r.get('es'), L['ja'])
            m_es = [m for m in m_es if not (m.split()[0] in ('TROZO_VACIO', 'SIN_TEXTO_TRADUCIDO') and exento(h, k, m.split()[0]))]; mal += m_es
            if not m_es: mal += dif_intocables(L['ja'], r['es'], a.permitir_genero)   # solo con es valida (mismo nº de trozos)
            if r.get('h') != L['h']: mal.append('H_LOTE %s != %s' % (r.get('h'), L['h']))
            if r.get('estado') not in ESTADOS_RES: mal.append('ESTADO %r' % r.get('estado'))
            if r.get('origen', ORIGEN) != ORIGEN: mal.append('ORIGEN %r' % r.get('origen'))
            if mal: fallos.append((h, k, 'RESULTADO', '; '.join(mal))); continue
            ff, av = alineacion_fr(L, r['es']) if L.get('fuente') == 'fr' else alineacion(L['ja'], r['es'], glos_alin, long_alin, L.get('fr')); ff = [x for x in ff if not exento(h, k, x[0])]
            if L.get('acortar'):   # bloque 5: ALIN_GLOSARIO no bloquea (acortar puede abreviar un termino); es <= max_len por trozo (fr visible)
                ff = [x for x in ff if x[0] != 'ALIN_GLOSARIO']
                ml = L.get('max_len') or []; ea = L.get('es_actual') or []
                if cplx and L.get('fijos') and len(ml) == B.esperados(L) != len(L['ja']):   # bloque 6: max_len / es_actual vienen alineados con los traducibles; se completan con los fijos
                    fjs = set(L['fijos']); it_m = iter(ml); it_e = iter(ea)
                    ml = [None if i in fjs else next(it_m) for i in range(len(L['ja']))]; ea = [L['ja'][i] if i in fjs else next(it_e) for i in range(len(L['ja']))]
                lg = []
                for i, (t, m) in enumerate(zip(r['es'], ml)):
                    if isinstance(m, list):   # bloque 6: trozo con LF internos; un max_len por linea interna
                        ls = t.split('\n')
                        if len(ls) != len(m): lg.append('trozo %d: %d lineas internas != %d' % (i, len(ls), len(m)))
                        else: lg += ['trozo %d linea %d: %d > %d' % (i, q, len(x.strip()), mm) for q, (x, mm) in enumerate(zip(ls, m)) if mm is not None and len(x.strip()) > mm]
                    elif m is not None:
                        # comandos de chat (/echo...) del ja se conservan exactos: su longitud no cuenta para max_len (solo filas acortar)
                        cmd = sum(len(x) for x in C.CMD_RE.findall(L['ja'][i])) if C is not None and i < len(L['ja']) and C.CMD_RE.findall(t) else 0
                        if len(t.strip()) - cmd > m and not _es_nombre_glosario(t, L): lg.append('trozo %d: %d > %d' % (i, len(t.strip()) - cmd, m))
                lg += ['trozo %d: cambia con max_len null' % i for i, (t, m, a0) in enumerate(zip(r['es'], ml, ea)) if m is None and t != a0]
                if lg: fallos.append((h, k, 'LONGITUD', '; '.join(lg))); continue
                L['_ea_cmp'] = None if L.get('es_h') else L.get('es_actual')   # lo que debe seguir en traducciones/ (compleja: se compara el hash `es_h` de la cadena)
            for c, det in av: avisos.append((h, k, c, det))
            if any(c == 'ALIN_GLOSARIO' for c, _ in av): cnt_alin['AVISO_GLOSARIO'] += 1
            if ff:
                for c in {c for c, _ in ff}: cnt_alin[c] += 1
                cnt_alin['FILAS'] += 1
                fallos.append((h, k, 'ALINEACION', '; '.join('%s %s' % x for x in ff))); continue
            es_final = G.recomponer(L['sep'], r['es']) if cplx else r['es']   # compleja: cadena tokenizada
            rec = {'row': k[0], 'sub': k[1], 'col': k[2], 'es': es_final, 'estado': r['estado'], 'h': L['h'], 'origen': L['origen_actual'] if L.get('acortar') else ORIGEN}   # bloque 5 (acortar): se conserva el origen de la fila
            if C is not None:
                if h not in ja_cache: ja_cache[h] = G.leer_ja(RAIZ, h) or {}
                tr_ja = ja_cache[h].get(k)
                if tr_ja is None: fallos.append((h, k, 'DAT_FILA_INEXISTENTE', 'no esta en textos/ja')); continue
                try: C.evaluar_cadena(tr_ja[0], tr_ja[1], rec)
                except C.Rechazo as e: fallos.append((h, k, 'DAT_' + e.motivo, e.detalle)); continue
            cambios[h][k] = (rec, L.get('linea'), 'resultado', {'accion': L.get('accion'), 'origen_actual': L.get('origen_actual'), 'es_actual': L.get('_ea_cmp') if L.get('acortar') else None, 'es_h': L.get('es_h')}); ok_res[(h,) + k] = rec
        for k in res: fallos.append((k[0], k[1:], 'NO_EN_LOTE', 'resultado sin fila en el lote'))
    # 2) copias (mismo japones que una fila del lote con resultado valido)
    for (hh, *k), L in lote.items():
        src = ok_res.get((hh,) + tuple(k))
        for c in L.get('copias', ()):
            if not ok_hoja(c['hoja']): continue
            kc = (c['row'], c['sub'], c['col'])
            if src is None: continue   # el origen no esta (o no paso): se informa ya por el origen / pendientes
            rec = {'row': kc[0], 'sub': kc[1], 'col': kc[2], 'es': src['es'] if isinstance(src['es'], str) else list(src['es']), 'estado': src['estado'], 'h': c['h'], 'origen': c['origen_actual'] if L.get('acortar') else ORIGEN}
            cambios[c['hoja']].setdefault(kc, (rec, c.get('linea'), 'copia', {'accion': c.get('accion'), 'origen_actual': c.get('origen_actual'), 'es_actual': L.get('_ea_cmp') if L.get('acortar') else None, 'es_h': L.get('es_h')}))
    # 3) reutilizadas
    for r in reut:
        h = r['hoja']
        k = (r['row'], r['sub'], r['col']); mal = [m for m in (mal_es(r.get('es')) if not isinstance(r.get('es'), str) else []) if m != 'TROZO_VACIO']   # es str = fila compleja (ya validada en su origen)   # mismo japones (mismo h): un trozo vacio ya existia en la fila origen
        if r.get('estado') not in ESTADOS_REUT: mal.append('ESTADO %r' % r.get('estado'))
        if not r.get('h'): mal.append('H_VACIO')
        if r.get('origen', 'reutilizada') not in ORIGENES_VALIDOS: mal.append('ORIGEN %r' % r.get('origen'))
        if mal: fallos.append((h, k, 'REUTILIZADA', '; '.join(mal))); continue
        rec = {'row': k[0], 'sub': k[1], 'col': k[2], 'es': r['es'], 'estado': r['estado'], 'h': r['h'], 'origen': r.get('origen', 'reutilizada')}
        if C is not None:   # bloque 2+: tambien se comprueba contra el japones de ESA celda
            if h not in ja_cache: ja_cache[h] = G.leer_ja(RAIZ, h) or {}
            tr_ja = ja_cache[h].get(k)
            if tr_ja is None: fallos.append((h, k, 'DAT_FILA_INEXISTENTE', 'no esta en textos/ja')); continue
            try: C.evaluar_cadena(tr_ja[0], tr_ja[1], rec)
            except C.Rechazo as e: fallos.append((h, k, 'DAT_' + e.motivo, e.detalle)); continue
        cambios[h].setdefault(k, (rec, r.get('linea'), 'reutilizada', {'accion': r.get('accion'), 'origen_actual': r.get('origen_actual')}))
    # 4) aplicar por hoja
    stats = collections.Counter(); escritas = []
    pend_escritura = {}
    no_esc = {x for x in a.no_escribir.split(',') if x} if a.no_escribir else set()
    for h in sorted(cambios):
        if h in no_esc: continue
        try: H = Hoja(h)
        except OSError as e:
            for k in cambios[h]: fallos.append((h, k, 'SIN_FICHERO', str(e)))
            continue
        nuevas = {}; nuevos = []
        for k, (rec, hint, tag, meta) in sorted(cambios[h].items(), key=lambda x: (x[0][0], -1 if x[0][1] is None else x[0][1], x[0][2])):
            n, motivo = H.localizar(k, hint)
            if n is None:
                if meta.get('accion') == 'anadir': nuevos.append(rec); stats[tag] += 1   # bloque 2: celda sin entrada -> linea nueva al final
                else: fallos.append((h, k, tag.upper(), motivo))
                continue
            cur = H.json[n]
            if cur == rec: stats['ya_' + tag] += 1; continue
            if meta.get('es_h') is not None and (hashlib.sha1(json.dumps(cur.get('es'), ensure_ascii=False).encode('utf-8')).hexdigest()[:12] != meta['es_h'] or cur.get('origen') != meta.get('origen_actual')):   # bloque 6: filas complejas
                fallos.append((h, k, tag.upper(), 'ACORTAR_FILA_CAMBIADA linea %d: es u origen ya no coinciden con los del lote' % n)); continue
            if meta.get('es_actual') is not None and (cur.get('es') != meta['es_actual'] or cur.get('origen') != meta.get('origen_actual')):   # bloque 5: solo si la fila sigue como la vio el generador
                fallos.append((h, k, tag.upper(), 'ACORTAR_FILA_CAMBIADA linea %d: es u origen ya no coinciden con los del lote' % n)); continue
            # bloque 2: 'sustituir' fuerza el reemplazo de una linea no corpus/dudosa (rechazada o pendiente de revision) SI su origen sigue siendo el que vio el generador
            forzar = meta.get('accion') == 'sustituir' and 'origen_actual' in meta and cur.get('origen') == meta['origen_actual']
            if not reemplazable(cur) and not forzar: fallos.append((h, k, tag.upper(), 'linea %d no es corpus ni dudosa (origen=%r, estado=%r) y difiere: no se pisa' % (n, cur.get('origen'), cur.get('estado')))); continue
            if tag == 'reutilizada' and not forzar and isinstance(cur.get('es'), list) and len(cur['es']) != len(rec['es']):
                fallos.append((h, k, tag.upper(), 'N_TROZOS linea %d tiene %d, reutilizada %d' % (n, len(cur['es']), len(rec['es'])))); continue
            if n in nuevas: fallos.append((h, k, tag.upper(), 'linea %d ya sustituida por otra fila' % n)); continue
            nuevas[n] = rec; stats[tag] += 1
        if nuevas or nuevos: pend_escritura[h] = (H, nuevas, nuevos)
    # 5) escribir
    claves_cajas = {}
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    for h, (H, nuevas, nuevos) in sorted(pend_escritura.items()):
        if a.dry_run: continue
        partes = list(H.partes)
        for n, rec in nuevas.items():
            cr = '\r' if partes[n - 1].endswith('\r') else ''
            partes[n - 1] = dumps(rec) + cr
        if nuevos:   # lineas nuevas al final (antes del '' que deja el \n final; fichero vacio/inexistente: se crea)
            fin = partes[-1] == ''
            if fin: partes.pop()
            partes += [dumps(r) for r in nuevos]
            if fin or not H.texto: partes.append('')
        bak = os.path.join(RAIZ, 'trabajo', 'lotes', 'bak') if bloque else os.path.join(d, 'bak'); os.makedirs(bak, exist_ok=True)
        bruta = os.path.join(bak, '%s.%s.jsonl' % (h.replace('/', '-'), ts))
        with open(bruta, 'w', encoding='utf-8', newline='') as f: f.write(H.texto)
        os.makedirs(os.path.dirname(H.ruta), exist_ok=True)
        tmp = H.ruta + '.tmp.%d' % os.getpid()
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write('\n'.join(partes)); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, H.ruta); escritas.append(h)
        claves_cajas.setdefault(h, set()).update((r['row'], r.get('sub'), r['col']) for r in list(nuevas.values()) + list(nuevos))
    # 5b) PUERTA DE CAJAS (tools/py/lotes/cajas): reflujo determinista de las celdas aplicadas segun su perfil de caja (palabra suelta, macros, ventana final); no recorta, mismo h/origen
    if claves_cajas and not a.sin_cajas:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cajas'))
            import corregir_cajas as CC
            arr, mej, noarr = CC.corregir_celdas(RAIZ, claves_cajas, True)
            print('CAJAS: arregladas %d, mejoradas %d, no arreglables %d (lista: trabajo/informes/cajas_no_arreglables.tsv)' % (arr, mej, len(noarr)))
            if noarr: CC.escribir_no_arreglables(CC.NO_ARR, noarr)
        except Exception as ex:
            print('AVISO CAJAS: puerta de cajas no ejecutada (%s)' % ex)
    # 6) informe
    L = ['aplicar_resultados %s%s | lotes %s' % (nombre, ' [DRY-RUN]' if a.dry_run else '', d),
         'lote %d filas | sin resultado (pendientes) %d | reutilizadas en fichero %d' % (len(lote), pendientes, len(reut)),
         'lotes del manifiesto %d | con resultado %d | sin resultado %d' % (n_lotes, len(unidades), len(lotes_sin_res)) if bloque else 'lotes: 1',
         'aplicadas: resultados %d, copias %d, reutilizadas %d | ya aplicadas: resultados %d, copias %d, reutilizadas %d | FALLIDAS %d' % (
             stats['resultado'], stats['copia'], stats['reutilizada'], stats['ya_resultado'], stats['ya_copia'], stats['ya_reutilizada'], len(fallos)),
         'hojas %s: %s' % ('a escribir' if a.dry_run else 'escritas', ', '.join('%s (%d lineas)' % (h, len(v[1]) + len(v[2])) for h, v in sorted(pend_escritura.items())) or '-')]
    L.append('ALINEACION: filas fallidas %d | por causa: digitos %d, proporcion %d | AVISOS glosario (filas aplicadas) %d | avisos totales %d (incl. ja < %d car.)' % (
        cnt_alin['FILAS'], cnt_alin['ALIN_DIGITOS'], cnt_alin['ALIN_PROPORCION'], cnt_alin['AVISO_GLOSARIO'], len(avisos), TERM_MIN))
    for h, k, tag, det in fallos: L.append('FALLO\t%s\t%s\t%s' % (kstr(h, k), tag, det))
    txt = '\n'.join(L) + '\n'
    sys.stdout.write(txt)
    for h, k, tag, det in avisos: L.append('AVISO\t%s\t%s\t%s' % (kstr(h, k), tag, det))   # solo en el fichero del informe
    txt = '\n'.join(L) + '\n'
    ruta_inf = a.informe or (None if a.dry_run else os.path.join(d, 'informe_aplicar_%s.txt' % nombre))
    if ruta_inf:
        with open(ruta_inf, 'w', encoding='utf-8', newline='\n') as f: f.write(txt)
    return 1 if fallos else 0

if __name__ == '__main__': sys.exit(main())
