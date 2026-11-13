"""Importar parche: informe de novedades entre dos extracciones (textos/ja anterior vs nuevo) y reparto en el flujo de trabajo.
Este modulo NUNCA escribe en traducciones/ ni en ediciones/ ni toca el `es`: solo lee traducciones (para conservar el es de las filas borradas/movidas en el informe)
y escribe datos/parches/<version>.json y las marcas locales de flujo.
Clases (por hoja+row+sub+col, solo celdas con japones CJK):
  NUEVA    = clave inexistente en la extraccion anterior.   CAMBIADA = clave en ambas con `text` ja distinto (el es se conserva; el indice la marca naranja = a revisar).
  BORRADA  = clave que ya no esta (se guarda su es, si lo tenia).   MOVIDA = NUEVA cuyo ja es identico (mismo h) a una BORRADA con es de la MISMA hoja: solo se PROPONE arrastrar su traduccion."""
import collections, hashlib, json, os, time
from . import extractor, indexer

TIPOS = ('nuevas', 'cambiadas', 'borradas', 'movidas')


def _h(t): return hashlib.sha1(t.encode('utf-8')).hexdigest()[:12]


def leer_ja(raiz, hoja, idioma='ja'):
    """{(row,sub,col): text} de una hoja de <raiz>/textos/<idioma> (solo texto no vacio)"""
    out = {}
    for k, l in indexer._lineas(indexer._rutas_hoja(raiz, idioma, hoja)).items():
        t = indexer._texto(l)[0]
        if t: out[k] = t
    return out


def leer_es(repo_dir, ediciones_dir, hoja):
    """{(row,sub,col): es} (repo + ediciones del usuario; las ediciones ganan). Solo lectura."""
    suf = os.path.join(*hoja.split('/')) + '.jsonl'
    tr = indexer._leer_trad_lineas(os.path.join(repo_dir, 'traducciones', suf)) if repo_dir else {}
    if ediciones_dir: tr.update(indexer._leer_trad_lineas(os.path.join(ediciones_dir, 'traducciones', suf)))
    return {k: e.get('es') for k, (e, _) in tr.items() if indexer.plano(e.get('es')).strip()}


def _hojas(raiz):
    return indexer.listar_jsonl(os.path.join(raiz, 'textos', 'ja'), quitar_part=True)


def comparar(raiz_viejo, raiz_nuevo, repo_dir=None, ediciones_dir=None, tiene_cjk=None, hash_ja=None, progreso=None, excluir=()):
    """raiz_* = carpetas que contienen textos/ja. -> {hoja: {'nuevas': [[r,s,c]], 'cambiadas': [[r,s,c,ja_anterior]], 'borradas': [[r,s,c,ja,es]], 'movidas': [{'de','a','ja','es'}]}}
    (solo hojas con alguna novedad). No escribe nada."""
    if tiene_cjk is None:
        import re
        cjk = re.compile('[぀-ヿ㐀-鿿＀-￯]'); tiene_cjk = lambda t: cjk.search(t) is not None
    hash_ja = hash_ja or _h
    hv, hn = _hojas(raiz_viejo), _hojas(raiz_nuevo)
    todas = sorted((hv | hn) - set(excluir)); res = {}      # excluir = hojas que no se pudieron leer: ni nuevas ni borradas (se conservan)
    for i, hoja in enumerate(todas):
        v = leer_ja(raiz_viejo, hoja) if hoja in hv else {}
        n = leer_ja(raiz_nuevo, hoja) if hoja in hn else {}
        nuevas = [k for k in n if k not in v and tiene_cjk(n[k])]
        cambiadas = [k for k in n if k in v and v[k] != n[k] and tiene_cjk(n[k])]
        sin_n = [k for k in v if k not in n]
        if not (nuevas or cambiadas or sin_n):
            continue
        es = leer_es(repo_dir, ediciones_dir, hoja) if (sin_n or nuevas) else {}
        borradas = [k for k in sin_n if tiene_cjk(v[k]) or k in es]
        orden = lambda k: (k[0], -1 if k[1] is None else k[1], k[2])
        # movidas: nueva con el mismo ja (h) que una borrada CON es de la misma hoja, sin traduccion propia, con ja UNICO en esa hoja a ambos lados (si la frase se repite
        # en varias filas el emparejamiento seria ambiguo: no se propone) y, si ambos tienen frances, con el mismo frances
        rep_v = collections.Counter(v.values()); rep_n = collections.Counter(n.values())
        por_h = {}
        for k in sorted((k for k in borradas if k in es and rep_v[v[k]] == 1), key=orden): por_h.setdefault(hash_ja(v[k]), []).append(k)
        movidas = []; fr_v = fr_n = None
        for k in sorted(nuevas, key=orden):
            if k in es or rep_n[n[k]] != 1: continue
            lst = por_h.get(hash_ja(n[k]))
            if lst:
                if fr_v is None:
                    fr_v = leer_ja(raiz_viejo, hoja, 'fr') if hoja in hv else {}; fr_n = leer_ja(raiz_nuevo, hoja, 'fr') if hoja in hn else {}
                de = lst[0]
                if fr_v.get(de) and fr_n.get(k) and fr_v[de] != fr_n[k]: continue
                lst.pop(0)
                movidas.append({'de': list(de), 'a': list(k), 'ja': n[k], 'es': es[de], 'aceptada': False})
        d = {'nuevas': [list(k) for k in sorted(nuevas, key=orden)],
             'cambiadas': [list(k) + [v[k]] for k in sorted(cambiadas, key=orden)],
             'borradas': [list(k) + [v[k], es.get(k)] for k in sorted(borradas, key=orden)],
             'movidas': movidas}
        if any(d.values()): res[hoja] = d
        if progreso and i % 500 == 0: progreso('comparando %d/%d (%s)' % (i, len(todas), hoja))
    return res


def conteos(hojas):
    c = {t: 0 for t in TIPOS}
    for d in hojas.values():
        for t in TIPOS: c[t] += len(d.get(t, ()))
    return c


def crear_informe(version, base_version, hojas, no_leidas=()):
    return {'formato': 1, 'version': version, 'base_version': base_version, 'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'conteos': conteos(hojas), 'hojas': hojas,
            'no_leidas': list(no_leidas)}      # no_leidas = hojas que fallaron al leer y se conservaron como estaban (no cuentan como borradas)


def _ruta(parches_dir, version): return os.path.join(parches_dir, extractor.version_segura(version) + '.json')


def leer_informe(parches_dir, version):
    try:
        with open(_ruta(parches_dir, version), encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError): return None


def listar_informes(parches_dir):
    out = []
    try: nombres = os.listdir(parches_dir)
    except OSError: return out
    for n in nombres:
        if not n.endswith('.json'): continue
        try:
            with open(os.path.join(parches_dir, n), encoding='utf-8') as f: j = json.load(f)
            out.append({'version': j.get('version') or n[:-5], 'fecha': j.get('fecha'), 'base_version': j.get('base_version'), 'conteos': j.get('conteos') or {}})
        except (OSError, ValueError): continue
    return sorted(out, key=lambda x: x.get('fecha') or '', reverse=True)


def guardar_informe(parches_dir, informe):
    """Escritura atomica. IDEMPOTENTE: si ya hay informe de esa version y el nuevo no trae novedades se conserva el existente (-> (informe, False)); si trae, lo sustituye
    conservando las movidas ya aceptadas. -> (informe_vigente, escrito)"""
    previo = leer_informe(parches_dir, informe['version'])
    if previo and not any(informe['conteos'].values()): return previo, False
    if previo:
        ya = {(tuple(m['a'])) for d in previo.get('hojas', {}).values() for m in d.get('movidas', ()) if m.get('aceptada')}
        for d in informe['hojas'].values():
            for m in d['movidas']:
                if tuple(m['a']) in ya: m['aceptada'] = True
    os.makedirs(parches_dir, exist_ok=True)
    ruta = _ruta(parches_dir, informe['version']); tmp = ruta + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(informe, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, ruta)
    return informe, True


def celdas_flujo(informe):
    """-> (nuevas, cambiadas): listas de (hoja,row,sub,col)"""
    nu, ca = [], []
    for hoja, d in informe['hojas'].items():
        nu += [(hoja, r, s, c) for r, s, c in d['nuevas']]
        ca += [(hoja, r, s, c) for r, s, c, _ in d['cambiadas']]
    return nu, ca


def marcar_flujo(flujo, informe):
    """nuevas y cambiadas -> «Por hacer» con etiqueta de version. IDEMPOTENTE: una celda con la etiqueta de ESTA version ya se proceso y no se vuelve a tocar (asi un reimporte, o abrir
    Novedades tras un corte, completa lo que faltaba sin pisar lo que el usuario ya hizo). Las nuevas ya «Hecho» no se tocan (se etiquetan igual); una cambiada «Hecho» vuelve a
    «Por hacer». Solo escribe flujo.json y flujo_parche.json (nada de traducciones). -> {'por_hacer': n, 'respetadas_hecho': n, 'ya_procesadas': n}"""
    nu, ca = celdas_flujo(informe); v = informe['version']
    def pend(lst): return [c for c in lst if (flujo.etiqueta(*c) or {}).get('version') != v]
    nu, ca, ya = pend(nu), pend(ca), len(nu) + len(ca)
    ya -= len(nu) + len(ca)
    hechas = [c for c in nu if flujo.estado(*c) == 'hecho']
    nu_ok = [c for c in nu if flujo.estado(*c) != 'hecho']
    n = flujo.poner(nu_ok + ca, 'por_hacer')
    flujo.etiquetar(nu, v, 'nueva'); flujo.etiquetar(ca, v, 'cambiada')
    return {'por_hacer': n, 'respetadas_hecho': len(hechas), 'ya_procesadas': ya}
