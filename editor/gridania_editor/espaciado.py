"""Espaciado automatico MASIVO: «Aplicar espaciado automatico a todo» y «Quitar espaciado automatico de todo».
Operan en bloque sobre TODAS las hojas (una pasada por hoja, una escritura de ediciones/ por hoja, sin ir celda a celda desde la UI), con barra de progreso, cancelacion,
registro de lo cambiado (datos/espaciado/<fecha>_<modo>.jsonl) y deshacer (se restaura cada celda a su texto, origen y fila de ediciones anteriores).

Reglas (mismas que el .dat y que la vista previa; ver celda.Motor.modo_suavizado):
- Solo celdas VERDES (traduccion vigente con el h actual). Las naranjas (japones cambiado, a revisar) NO se tocan: guardarlas las pasaria a verde y borraria la marca de revision.
- Balloon y NpcYell: nunca se tocan (en ningun modo). ENpcResident, Lobby y CharaMake* estan excluidos del SUAVIZADO del .dat: «quitar» no los toca.
- Narrador (perfil de caja subtitulo, o clave NARRAT / MYSTERYVOICE): sus trozos son frases sueltas que nunca se funden: no se tocan.
- Cajas de ancho fijo (hud_fijo, descripcion, sistema, CharaMake*): no se reflujan en ningun modo (en APLICAR solo hay reflujo en quest*, DefaultTalk a 58 y Lobby a 49: Motor.ancho_reflujo).
- APLICAR solo toca celdas que INCUMPLEN (ventana final huerfana o ultima linea < 10 car.) y solo si el reflujo mejora (violaciones y coste), como `reflujar_lineas --solo-incumplen`.
- APLICAR = el reflujo del editor (el mismo que el boton «Suavizar saltos» de una celda): dialogo de quest/* y DefaultTalk a 58 caracteres y maximo 4 lineas por ventana, creador de
  personaje (Lobby) a 49. El resto de clases (objetivos, menus, descripciones...) se espacia al GENERAR el .dat (suavizar_saltos): no cambia el texto guardado, y la vista previa ya lo
  muestra. Nunca cambia palabras, macros ni el numero de trozos (si cambiase algo mas que saltos, la celda se descarta).
- QUITAR = quita los saltos de presentacion que construir_dat admite quitar (los que exige el japones se conservan), uniendo con un espacio; solo en celdas de las clases que el .dat
  suaviza (dialogo, objetivos, menus...)."""
import collections, glob, json, os, re, time

MODOS = ('aplicar', 'quitar')
SIEMPRE_EXCLUIDAS = ('Balloon', 'NpcYell')        # nunca se tocan, en ningun modo
CONSERVAR_REGISTROS = 5
NL_RE = re.compile(r'<NewLine(?:#\d+)?>|\n')
CATEGORIAS = ('cambiada', 'ya_cumplia', 'se_espacia_en_el_dat', 'sin_saltos', 'no_admite', 'excluida', 'narrador', 'caja_fija', 'solo_saltos', 'rechazada',
              'sin_mejora', 'sin_japones', 'cambiada_durante', 'error', 'naranja_no_tocada', 'escritura_fallida')


def dir_registros(cfg):
    return cfg.sub('espaciado')


def _tiene_salto(es):
    xs = es if isinstance(es, list) else [es]
    return any(isinstance(x, str) and NL_RE.search(x) for x in xs)


def solo_saltos(a, b):
    """True si a y b (str o lista de trozos) solo difieren en saltos de linea/espacios: mismo n. de trozos, misma secuencia plana de palabras y las mismas macros por trozo"""
    la = a if isinstance(a, list) else [a]; lb = b if isinstance(b, list) else [b]
    if len(la) != len(lb) or isinstance(a, list) != isinstance(b, list): return False
    def pal(l): return [w for x in l if isinstance(x, str) for w in re.sub(r'<NewLine(?:#\d+)?>', ' ', x).split()]
    if pal(la) != pal(lb) or [not isinstance(x, str) for x in la] != [not isinstance(x, str) for x in lb]: return False
    def macros(x): return sorted(t for t in re.findall(r'<[^<>]*>', x) if not re.fullmatch(r'<NewLine(?:#\d+)?>', t)) if isinstance(x, str) else None
    if [macros(x) for x in la] != [macros(x) for x in lb]: return False
    return [bool(pal([x])) if isinstance(x, str) else None for x in la] == [bool(pal([x])) if isinstance(x, str) else None for x in lb]


def bloqueo(m, c, modo):
    """categoria que impide tocar la celda (excluida | narrador | caja_fija) o '' si se puede. m = celda.Motor, c = contexto"""
    SS = m.R.SS
    if c.hoja in SIEMPRE_EXCLUIDAS: return 'excluida'
    es_n = getattr(SS, 'es_narrador', None)
    if es_n is not None and es_n(c.pf, c.clave if c.col != 0 else None): return 'narrador'
    if modo == 'quitar':
        if SS.excluida(c.hoja): return 'excluida'
        if c.pf.tipo in getattr(SS, 'TIPOS_FIJOS', ('hud_fijo', 'descripcion', 'sistema')): return 'caja_fija'
        modo_dat, _ = SS.modo_de(c.pf, c.fr_text)
        if modo_dat is None: return 'caja_fija'
    return ''


def espaciar_celda(m, c, es0, modo):
    """una celda (contexto c, es actual es0) -> (es_nuevo | None, categoria). Sin auditorias ni vistas: solo lo necesario (rapido). No escribe nada."""
    if modo not in MODOS: raise ValueError('modo desconocido')
    b = bloqueo(m, c, modo)
    if b: return None, b
    if modo == 'aplicar':
        W = c.reflujo_W
        if not W:      # sin reflujo en el editor: o el .dat no la suaviza (excluida / caja fija) o la espacia al generarse
            SS = m.R.SS
            if SS.excluida(c.hoja): return None, 'excluida'
            return (None, 'caja_fija') if SS.modo_de(c.pf, c.fr_text)[0] is None else (None, 'se_espacia_en_el_dat')
        if not _tiene_salto(es0) and not (isinstance(es0, list) and len(es0) > 1): return None, 'sin_saltos'
        RL = m.R.RL
        RL.CFG.paginar = True; RL.CFG.macros = True; RL.CFG.maxwin = 4
        d = {}      # procesar_celda ignora CFG.solo (lo lee procesar_hoja): el filtro «solo incumplen» se reproduce aqui
        try: st, a, info = RL.procesar_celda(c.text, c.raw, m._fila(c, es0), W, c.creador, c.clave, d)
        except Exception: return None, 'error'
        if st == 'sin_saltos': return None, 'sin_saltos'
        if st not in ('cambiada', 'ya_correcta'): return None, 'rechazada'
        s0 = d.get('antes')
        if s0 is None: return None, 'rechazada'
        v0 = RL.violaciones(s0)
        if v0 == 0: return None, 'ya_cumplia'      # gridania: solo se toca lo que incumple
        if st == 'ya_correcta': return None, 'sin_mejora'      # incumple pero el reflujo no encuentra mejora
        v1 = RL.violaciones(d.get('despues') or s0)
        ca, cn = (info.get('coste') or (None, None)) if isinstance(info, dict) else (None, None)
        if v1 >= v0 or (ca is not None and ca != float('inf') and cn > ca): return None, 'sin_mejora'
        nuevo = a
    else:
        if not _tiene_salto(es0): return None, 'sin_saltos'
        try: nuevo = m.sin_saltos(c, es0)
        except Exception: return None, 'error'
        if nuevo is None: return None, 'no_admite'
    if nuevo == es0: return None, 'ya_cumplia'
    if not solo_saltos(es0, nuevo): return None, 'solo_saltos'      # cambiaria algo mas que saltos/espacios: se descarta
    if not m._validar(c, nuevo): return None, 'rechazada'
    return nuevo, 'cambiada'


def _hojas_con_traduccion(base):
    """[(hoja, n_verdes)] y {hoja: n_naranjas con es}, de una consulta agregada"""
    verdes = [(r['hoja'], r['n']) for r in base.q("SELECT hoja, COUNT(*) n FROM celdas WHERE estado='verde' AND es_json IS NOT NULL GROUP BY hoja ORDER BY hoja")]
    nar = {r['hoja']: r['n'] for r in base.q("SELECT hoja, COUNT(*) n FROM celdas WHERE estado='naranja' AND es_json IS NOT NULL GROUP BY hoja")}
    return verdes, nar


def _rotar(d):
    fs = sorted(glob.glob(os.path.join(d, '*.resumen.json')))
    for r in fs[:-CONSERVAR_REGISTROS]:
        for p in (r, r[:-len('.resumen.json')] + '.jsonl'):
            try: os.remove(p)
            except OSError: pass


def _escribir_json(ruta, obj):
    tmp = ruta + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta)


def ejecutar(app, modo, log=print, avance=None, cancelar=None):
    """recorre todas las hojas con traduccion y aplica `modo` en bloque. -> resumen (dict). `app` = Aplicacion. Cancelable entre hojas: lo ya escrito queda registrado y se puede deshacer."""
    if modo not in MODOS: raise ValueError('modo desconocido')
    avance = avance or (lambda *a: None)
    base = app.base; base.exigir_libre()
    m = app.motor(); R = m.R
    d = dir_registros(app.cfg); os.makedirs(d, exist_ok=True)
    sello = time.strftime('%Y%m%d-%H%M%S'); ruta_j = os.path.join(d, '%s_%s.jsonl' % (sello, modo)); ruta_r = os.path.join(d, '%s_%s.resumen.json' % (sello, modo))
    verdes, nar = _hojas_con_traduccion(base)
    total = sum(n for _, n in verdes); hecho = 0
    cont = collections.Counter(); por_hoja = collections.OrderedDict(); cancelado = False
    cont['naranja_no_tocada'] = sum(nar.values())
    resumen = {'formato': 1, 'modo': modo, 'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'celdas_verdes': total, 'estado': 'en_curso', 'deshecho': False, 'registro': os.path.basename(ruta_j)}
    _escribir_json(ruta_r, resumen)
    log('espaciado %s: %d hojas, %d celdas verdes (las %d naranjas no se tocan)' % (modo, len(verdes), total, cont['naranja_no_tocada']))
    avance('espaciado (%s)' % ('aplicar' if modo == 'aplicar' else 'quitar'), 0, total)
    from . import edits
    RL = R.RL; margen0 = RL.MARGEN
    if modo == 'aplicar': RL.MARGEN = 0.0      # como reflujar_lineas --solo-incumplen
    try:
        with open(ruta_j, 'w', encoding='utf-8', newline='\n') as jf:
            jf.write(json.dumps({'tipo': 'cabecera', 'modo': modo, 'fecha': resumen['fecha']}, ensure_ascii=False) + '\n')
            for hoja, n in verdes:
                if cancelar is not None and cancelar.is_set(): cancelado = True; break
                filas = base.q("SELECT id,row,sub,col,es_json FROM celdas WHERE hoja=? AND estado='verde' AND es_json IS NOT NULL ORDER BY row, COALESCE(sub,-1), col", (hoja,))
                items = []; antes = {}; hc = collections.Counter()
                for i, r in enumerate(filas):
                    try:
                        es0 = json.loads(r['es_json']); c = m.contexto(hoja, r['row'], r['sub'], r['col'])
                    except KeyError: hc['sin_japones'] += 1; continue
                    except Exception: hc['error'] += 1; continue
                    try: nuevo, cat = espaciar_celda(m, c, es0, modo)
                    except Exception: nuevo, cat = None, 'error'
                    hc[cat] += 1
                    if nuevo is not None: items.append((c, nuevo)); antes[c.k] = es0
                    if i % 200 == 199:
                        avance('espaciado (%s) %s' % (modo, hoja), hecho + i + 1, total)
                        if cancelar is not None and cancelar.is_set(): break
                if items:
                    with app.lock_ediciones:
                        # entre calcular y escribir el usuario pudo guardar una de estas celdas: se re-lee y solo se escribe donde sigue igual
                        vivas = {(r['row'], r['sub'], r['col']): r['es_json'] for r in base.q("SELECT row,sub,col,es_json FROM celdas WHERE hoja=? AND estado='verde' AND es_json IS NOT NULL", (hoja,))}
                        ok = []
                        for c, nuevo in items:
                            try: igual = json.loads(vivas.get(c.k) or 'null') == antes[c.k]
                            except ValueError: igual = False
                            if igual: ok.append((c, nuevo))
                            else: hc['cambiada'] -= 1; hc['cambiada_durante'] += 1
                        hechos, fallos = edits.guardar_lote(base, app.cfg.ediciones_dir, R, ok) if ok else ([], [])
                    hc['cambiada'] -= len(fallos); hc['escritura_fallida'] += len(fallos)
                    nuevo_de = {c.k: es for c, es in ok}
                    for h in hechos:
                        c = h['c']
                        jf.write(json.dumps({'hoja': hoja, 'row': c.row, 'sub': c.sub, 'col': c.col, 'antes': antes[c.k], 'despues': nuevo_de[c.k], 'previa': h['previa'], 'db': h['db']}, ensure_ascii=False) + '\n')
                    jf.flush(); resumen['cambiadas'] = cont['cambiada'] + hc['cambiada']; _escribir_json(ruta_r, resumen)
                cont.update(hc); hecho += n
                if hc['cambiada'] > 0: por_hoja[hoja] = hc['cambiada']
                if cancelar is not None and cancelar.is_set(): cancelado = True; break
            avance('espaciado (%s)' % modo, total if not cancelado else hecho, total)
    except BaseException as x:
        resumen.update(estado='error', error='%s: %s' % (type(x).__name__, x), cambiadas=cont['cambiada'], categorias=dict(cont)); _escribir_json(ruta_r, resumen)
        raise
    finally:
        RL.MARGEN = margen0
    resumen.update(estado='cancelado' if cancelado else 'completo', cambiadas=cont['cambiada'], categorias={k: v for k, v in cont.items() if v}, hojas_cambiadas=len(por_hoja),
                   hojas_con_mas_cambios=sorted(por_hoja.items(), key=lambda kv: -kv[1])[:20])
    _escribir_json(ruta_r, resumen); _rotar(d)
    log('espaciado %s %s: %d celdas cambiadas en %d hojas; %s' % (modo, resumen['estado'], cont['cambiada'], len(por_hoja), json.dumps(resumen['categorias'], ensure_ascii=False)))
    log('registro: %s' % ruta_j)
    resumen['ruta_registro'] = ruta_j
    return resumen


def ultimo_registro(cfg):
    """-> (ruta_resumen, resumen) del ultimo registro NO deshecho con celdas cambiadas, o (None, None)"""
    for r in sorted(glob.glob(os.path.join(dir_registros(cfg), '*.resumen.json')), reverse=True):
        try:
            with open(r, encoding='utf-8') as f: x = json.load(f)
        except (OSError, ValueError): continue
        if x.get('deshecho'): continue
        if x.get('estado') == 'en_curso' and not x.get('cambiadas'):      # cuelgue: se cuentan las lineas del registro
            try:
                with open(os.path.join(dir_registros(cfg), x.get('registro', '')), encoding='utf-8') as f: n = sum(1 for l in f if l.strip() and '"tipo": "cabecera"' not in l)
            except OSError: n = 0
            if n: x['cambiadas'] = n
        if x.get('cambiadas') and x.get('estado') in ('completo', 'cancelado', 'error', 'en_curso'): return r, x
    return None, None


def listar(cfg):
    out = []
    for r in sorted(glob.glob(os.path.join(dir_registros(cfg), '*.resumen.json')), reverse=True):
        try:
            with open(r, encoding='utf-8') as f: x = json.load(f)
        except (OSError, ValueError): continue
        out.append({k: x.get(k) for k in ('fecha', 'modo', 'estado', 'cambiadas', 'deshecho', 'registro', 'hojas_cambiadas')})
    return out


def deshacer(app, log=print, avance=None):
    """restaura el ultimo registro no deshecho: cada celda vuelve a su texto, origen y fila de ediciones anteriores. Una celda cambiada DESPUES del espaciado (su es ya no es el que escribio
    el espaciado) NO se toca y se cuenta en `cambiadas_despues`. -> dict"""
    from . import edits
    avance = avance or (lambda *a: None)
    base = app.base; base.exigir_libre()
    ruta_r, res = ultimo_registro(app.cfg)
    if not res: raise ValueError('no hay ningun espaciado masivo que deshacer')
    ruta_j = os.path.join(dir_registros(app.cfg), res['registro'])
    if not os.path.exists(ruta_j): raise ValueError('falta el registro %s: no se puede deshacer' % res['registro'])
    total = int(res.get('cambiadas') or 0); hecho = 0; restauradas = 0; cambiadas = []; incompatibles = 0
    avance('deshaciendo espaciado', 0, total)
    def procesar(hoja, lst):
        nonlocal restauradas, incompatibles
        with app.lock_ediciones:
            vivas = {(r['row'], r['sub'], r['col']): r['es_json'] for r in base.q('SELECT row,sub,col,es_json FROM celdas WHERE hoja=?', (hoja,))}
            ok = []
            for x in lst:
                if not isinstance(x.get('db'), dict) or 'despues' not in x: incompatibles += 1; continue
                try: actual = json.loads(vivas.get((x['row'], x['sub'], x['col'])) or 'null')
                except ValueError: actual = None
                if actual != x['despues']: cambiadas.append({k: x[k] for k in ('hoja', 'row', 'sub', 'col')}); continue
                ok.append({'hoja': hoja, 'row': x['row'], 'sub': x['sub'], 'col': x['col'], 'previa': x.get('previa'), 'db': x['db']})
            if ok: edits.restaurar_lote(base, app.cfg.ediciones_dir, ok)
            restauradas += len(ok)
    grupo = []; hoja_act = None
    with open(ruta_j, encoding='utf-8') as f:
        for linea in f:
            if not linea.strip(): continue
            try: x = json.loads(linea)
            except ValueError: continue
            if x.get('tipo') == 'cabecera': continue
            if x['hoja'] != hoja_act:
                if grupo: procesar(hoja_act, grupo); hecho += len(grupo); avance('deshaciendo espaciado', hecho, total)
                grupo = []; hoja_act = x['hoja']
            grupo.append(x)
        if grupo: procesar(hoja_act, grupo); hecho += len(grupo); avance('deshaciendo espaciado', hecho, total)
    res.update(deshecho=True, fecha_deshecho=time.strftime('%Y-%m-%d %H:%M:%S'), restauradas=restauradas, cambiadas_despues=len(cambiadas))
    _escribir_json(ruta_r, res)
    log('espaciado deshecho (%s %s): %d restauradas, %d no se tocan (editadas despues), %d incompatibles' % (res.get('modo'), res.get('fecha'), restauradas, len(cambiadas), incompatibles))
    return {'restauradas': restauradas, 'cambiadas_despues': len(cambiadas), 'cambiadas': cambiadas[:50], 'incompatibles': incompatibles, 'modo': res.get('modo'), 'fecha': res.get('fecha')}
