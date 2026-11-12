"""Logica de una celda: texto editable <-> `es`, validacion con las reglas del hook, reflujo, suavizado y vista previa «como en el juego».
Todo se apoya en los modulos del repo (tools/py): construir_dat.evaluar_cadena, reflujar_lineas.procesar_celda, suavizar_saltos.suavizar_celda,
latinismos, normalizar_*, auditar_global.revisar_fila, auditar_simbologia, auditar_say, cajas/nucleo."""
import collections, csv, json, os, re

CRITICOS_AG = {'N_TROZOS', 'TIPO_ES', 'CJK', 'TROZO_VACIO', 'ANCHURA'}   # = verificar_antes_de_commit.CRITICAS (ANCHURA_FATAL = True)
GEN_RE = re.compile(r'<Gender>(.*?)<GenderElse>(.*?)<GenderEnd>', re.S)
TOK_RE = re.compile(r'<[A-Za-z][A-Za-z0-9]*(?:#[0-9]+)?(?::[0-9A-Fa-f]+)?>')
NL_RE = re.compile(r'<NewLine(?:#[0-9]+)?>')
ABRE_C, CIERRA_C, ICONO_C = '\x01', '\x02', '\x03'   # centinelas de la vista previa: abre color, cierra color, icono (2 columnas)
HABLANTE_RE = re.compile(r'^\(-(.+?)-\)')
PUNT = re.compile(r'[.,;:!?…»”\)]$')


class Contexto(object):
    pass


class Almacen(object):
    """cache pequena de hojas ja / fr leidas de disco"""
    def __init__(self, R, raiz_textos):
        self.R = R; self.raiz = raiz_textos; self._ja = collections.OrderedDict(); self._fr = collections.OrderedDict()

    def _lru(self, d, k, f, n=4):
        if k in d: d.move_to_end(k); return d[k]
        v = f(); d[k] = v
        while len(d) > n: d.popitem(last=False)
        return v

    def ja(self, hoja): return self._lru(self._ja, hoja, lambda: self.R.G.leer_ja(self.raiz, hoja) or {})
    def fr(self, hoja): return self._lru(self._fr, hoja, lambda: self.R.NC.leer_fr(self.raiz, hoja))


class Glosario(object):
    def __init__(self, ruta):
        self.por_inicial = collections.defaultdict(list)
        if ruta and os.path.exists(ruta):
            with open(ruta, encoding='utf-8', newline='') as f:
                for r in csv.DictReader(f, delimiter='\t'):
                    ja, es = (r.get('ja') or '').strip(), (r.get('es') or '').strip()
                    if len(ja) >= 2 and es and r.get('estado') in ('ok', 'fijo'): self.por_inicial[ja[0]].append((ja, es))
        for v in self.por_inicial.values(): v.sort(key=lambda x: -len(x[0]))

    def terminos(self, ja):
        i = 0; out = []
        while i < len(ja):
            for j, e in self.por_inicial.get(ja[i], ()):
                if ja.startswith(j, i): out.append((j, e)); i += len(j) - 1; break
            i += 1
        return out


class Motor(object):
    def __init__(self, R, raiz_textos, repo_dir, base=None):
        self.R = R; self.repo_dir = repo_dir; self.base = base
        self.almacen = Almacen(R, raiz_textos)
        self.glosario = Glosario(os.path.join(repo_dir, 'data', 'glosario-propio.tsv'))
        self._listas = None

    # ------------------------------------------------------------ contexto
    def contexto(self, hoja, row, sub, col):
        R = self.R; G, S = R.G, R.S
        ja = self.almacen.ja(hoja); k = (row, sub, col)
        if k not in ja: raise KeyError('la celda no esta en el japones actual')
        c = Contexto(); c.hoja, c.row, c.sub, c.col, c.k = hoja, row, sub, col, k
        c.text, c.raw = ja[k]; c.h = G.hash_ja(c.text)
        c.tok = S.tokenize_raw(G.bytes_ja(c.text, c.raw))
        c.tipo = G.clasificar(c.tok, bool(c.raw))
        c.ch = c.seps = None
        if c.tipo == 'simple': c.ch, c.seps = G.trocear(c.tok)
        fr = self.almacen.fr(hoja).get(k); c.fr_text = fr
        c.fr_tok = None
        if fr:
            try: c.fr_tok = S.tokenize_raw(G.bytes_ja(fr, None))
            except Exception: c.fr_tok = None
        c.clave = (ja.get((row, sub, 0)) or ('', None))[0] if col != 0 else ''
        clave = c.clave if R.PF.necesita_clave(hoja, col) else None
        c.pf = R.PF.de(hoja, col, row, clave)
        c.reflujo_W, c.creador = self.ancho_reflujo(hoja)
        return c

    @staticmethod
    def ancho_reflujo(hoja):
        if hoja == 'quest' or hoja.startswith('quest/') or hoja == 'DefaultTalk': return 58, False
        if hoja == 'Lobby': return 49, True
        return None, False

    # ------------------------------------------------------------ texto del editor <-> es
    def tokenizada(self, c, es):
        S, G = self.R.S, self.R.G
        if isinstance(es, str): return es
        if c.tipo == 'simple' and len(es) == len(c.seps) + 1: return G.recomponer(c.seps, es)
        return None

    def es_a_texto(self, c, es):
        """es (lista o cadena) -> texto del editor: la cadena tokenizada sin marcas; en celdas simples los <NewLine> se ven como saltos de linea"""
        S = self.R.S
        s = self.tokenizada(c, es)
        if s is None: s = ''
        s = s.replace(S.MARCA, '')
        return NL_RE.sub('\n', s) if c.tipo == 'simple' else s

    def texto_a_es(self, c, texto):
        S, RL = self.R.S, self.R.RL
        t = texto.replace('\r\n', '\n').replace('\r', '\n').replace(S.MARCA, '')
        if c.tipo != 'simple': return t
        s = S.renumerar_newlines(t.replace('\n', '<NewLine>'), c.tok)
        if S.contiene_color_propio(s): return s
        try: return RL.partir_lista(s, c.seps)
        except ValueError as x: raise ValueError('estructura: faltan separadores del original (%s)' % x)

    # ------------------------------------------------------------ evaluacion
    def _fila(self, c, es):
        return {'row': c.row, 'sub': c.sub, 'col': c.col, 'es': es, 'estado': 'traducida', 'h': c.h, 'origen': 'sesion'}

    def _validar(self, c, es):
        C = self.R.C
        try: C.evaluar_cadena(c.text, c.raw, self._fila(c, es)); return True
        except C.Rechazo: return False

    SALTO_RE = re.compile(r'[ ]*(?:<NewLine(?:#[0-9]+)?>|\r?\n)[ ]*')

    @classmethod
    def _unir(cls, x):
        """quita TODOS los saltos de x (los une con un espacio; sin espacio en los extremos)"""
        return cls.SALTO_RE.sub(lambda m: '' if (m.start() == 0 or m.end() == len(x)) else ' ', x)

    @classmethod
    def _sin_uno(cls, x, m):
        return x[:m.start()] + ('' if (m.start() == 0 or m.end() == len(x)) else ' ') + x[m.end():]

    def sin_saltos(self, c, es):
        """quita los saltos de presentacion que el contrato de construir_dat deja quitar: UNO A UNO, de atras adelante, conservando solo los que la validacion admite.
        Los <NewLine> que el japones exige (separadores entre trozos y tokens del original) NO se pueden borrar: se quedan (el suavizado del .dat los convierte en espacio con la marca).
        -> nuevo es, o None si no cambia nada"""
        if isinstance(es, list): act = list(es)
        elif isinstance(es, str) and c.tipo != 'simple': act = es
        else: return None
        def trozos(a): return list(enumerate(a)) if isinstance(a, list) else [(None, a)]
        for idx, x in reversed(trozos(act)):
            if not isinstance(x, str): continue
            for m in reversed(list(self.SALTO_RE.finditer(x))):
                y = self._sin_uno(x, m)
                cand = act[:idx] + [y] + act[idx + 1:] if idx is not None else y
                if self._validar(c, cand): act = cand; x = y
        if act == es: return None
        try: act = self.R.SS.normalizar(act)
        except Exception: pass
        return act if self._validar(c, act) else None

    def evaluar(self, c, texto, genero='masc', reflujo=True, es_actual=None):
        """-> dict(errores, avisos, es (lo que se guardaria), texto (editor, tras reflujo), vista). No escribe nada."""
        R = self.R; S, C, RL, SS, NC = R.S, R.C, R.RL, R.SS, R.NC
        errores = []; avisos = []
        res = {'errores': errores, 'avisos': avisos, 'es': None, 'texto': texto, 'vista': None, 'ok': False}
        try: es0 = self.texto_a_es(c, texto)
        except ValueError as x:
            errores.append(('ESTRUCTURA', str(x))); self._poner_vistas(res, self.vista_texto, c, texto, genero); return res
        es1 = SS.normalizar(es0)
        if es1 != es0: avisos.append(('AUTOCORREGIDO', 'signos japoneses, «…» o puntos suspensivos corregidos automaticamente'))
        try: C.evaluar_cadena(c.text, c.raw, self._fila(c, es1))
        except C.Rechazo as r:
            errores.append(('RECHAZO_' + r.motivo, r.detalle))
            self._poner_vistas(res, self.vista_texto, c, self.es_a_texto(c, es1) if self.tokenizada(c, es1) is not None else texto, genero)
            self._comprobaciones(c, es1, errores, avisos)
            return res
        es2 = es1
        info = res['suavizado'] = {'reflujo': 'desactivado' if not reflujo else ('no_aplica' if not c.reflujo_W else 'sin_cambios'), 'suavizado': 'no_aplica', 'motivo': ''}
        if reflujo and c.reflujo_W:
            RL.CFG.paginar = True; RL.CFG.macros = True; RL.CFG.maxwin = 4; RL.CFG.solo = False
            try:
                st, a, b = RL.procesar_celda(c.text, c.raw, self._fila(c, es1), c.reflujo_W, c.creador, c.clave)
            except Exception as x:
                st, a, b = 'excepcion', 'error_interno', '%s: %s' % (type(x).__name__, x)
            if st == 'cambiada': es2 = a; info['reflujo'] = 'cambiada'
            elif st == 'excepcion': info['reflujo'] = 'error'; avisos.append(('REFLUJO_NO_APLICADO', '%s %s' % (a, b)))
        modo, cap = SS.modo_de(c.pf, c.fr_text)
        info['modo'] = modo
        es3 = es2
        if modo is not None:
            try:
                n, motivo = SS.suavizar_celda(es2, c.tok, c.raw, modo, cap, lambda cand: self._validar(c, cand), c.fr_text)
                if n is not None: es3 = n; info['suavizado'] = 'aplicado'
                else: info['suavizado'] = 'cumplia'; info['motivo'] = str(motivo or '')
            except Exception as x:
                avisos.append(('SUAVIZADO_NO_APLICADO', '%s: %s' % (type(x).__name__, x)))
        res['es'] = es2   # se guarda SIN marcas: el suavizado se aplica al generar el .dat (igual que el flujo del repo)
        res['texto'] = self.es_a_texto(c, es2)
        self._comprobaciones(c, es2, errores, avisos)
        s_juego = R.S.aplicar_marcas(self.tokenizada(c, es3) or '')
        self._poner_vistas(res, self.vista, c, s_juego, genero)
        for cod in self.vista_problemas(c, self.tokenizada(c, es2) or ''):   # como la auditoria del repo: sobre las lineas duras (sin marcas)
            avisos.append(('CAJA_' + cod, self.TXT_CAJA.get(cod, cod)))
        res['ok'] = not errores
        return res

    @staticmethod
    def tiene_genero(s):
        return bool(GEN_RE.search(s or ''))

    def _poner_vistas(self, res, fn, c, s, genero):
        """res['vista'] = vista del genero pedido (compatibilidad); res['variantes'] = {'fem': vista, 'masc': vista} si el texto lleva macro <Gender>, si no None"""
        if self.tiene_genero(s):
            res['variantes'] = {g: fn(c, s, g) for g in ('fem', 'masc')}
            res['vista'] = res['variantes'].get(genero if genero in ('fem', 'masc') else 'masc')
        else:
            res['variantes'] = None; res['vista'] = fn(c, s, genero)

    TXT_CAJA = {'PALABRA_SUELTA': 'ventana o linea final huerfana (<= 2 palabras)', 'LINEA_EXCEDE': 'linea mas ancha que la caja', 'MACRO_NO_CONTADA': 'la expansion de una macro desborda la caja',
                'SUBTITULO_EXCEDE': 'subtitulo demasiado ancho o con demasiadas lineas', 'ALTO_EXCEDE': 'mas lineas que el frances', 'CAJA_DESCONOCIDA': 'linea ancha en caja sin medir', 'FR_EXCEDE': 'mas ancho que el frances'}

    def _comprobaciones(self, c, es, errores, avisos):
        R = self.R; AG, LAT, SIMB = R.AG, R.LAT, R.SIMB
        e = self._fila(c, es)
        try:
            for cod, det in AG.revisar_fila(e, c.ch if (c.tipo == 'simple' and isinstance(es, list)) else None, c.seps, c.tok, c.text):
                (errores if cod in CRITICOS_AG else avisos).append((cod, det))
        except Exception as x: avisos.append(('REVISAR_FILA', '%s: %s' % (type(x).__name__, x)))
        for nv, cod, det in LAT.detectar(es, c.text):
            (errores if nv == 'error' else avisos).append(('LATINISMO' if nv == 'error' else 'USTEDES_FORMAL', '%s: %s' % (cod, det)))
        if c.tipo == 'simple' and isinstance(es, list):
            try:
                for cod in SIMB.objetivas_puerta(c.ch, es): errores.append(('SIMBOLOGIA', cod))
            except Exception as x: avisos.append(('SIMBOLOGIA_NO_EVALUADA', str(x)))
        plano = ' '.join(es) if isinstance(es, list) else es
        if '…' in plano or '‥' in plano: errores.append(('PUNTOS_SUSPENSIVOS', 'el caracter … esta prohibido: usa tres puntos ...'))
        self._glosario(c, plano, avisos)
        self._say(c, es, avisos)

    def _glosario(self, c, plano, avisos):
        pl = plano.lower(); n = 0
        for j, e in self.glosario.terminos(c.text):
            if e.lower() not in pl:
                avisos.append(('GLOSARIO', '%s -> %s' % (j, e))); n += 1
                if n >= 6: break

    def listas_say(self):
        if self._listas is None: self._listas = self.R.AS.cargar_listas(self.repo_dir)
        return self._listas

    def _say(self, c, es, avisos):
        AS = self.R.AS
        if c.hoja in AS.EXCLUIR: return
        t = c.text
        try:
            ja = self.almacen.ja(c.hoja)
            if not any(AS.RE_MODO.search(v[0]) or '/' in v[0] or '{0x12:' in v[0] for v in ja.values()): return
            jd = {k: {'text': v[0]} for k, v in ja.items()}
            ed = {}
            if self.base is not None:
                for r in self.base.q('SELECT row,sub,col,es_json FROM celdas WHERE hoja=? AND es_json IS NOT NULL', (c.hoja,)):
                    ed[(r['row'], r['sub'], r['col'])] = {'es': json.loads(r['es_json'])}
            ed[c.k] = {'es': es}
            for r in AS.auditar_hoja(c.hoja, jd, ed, self.listas_say()):
                if (r[1], (None if r[2] == '' else r[2]), r[3]) == c.k and r[7] in ('alta', 'media'):
                    avisos.append(('SAY_' + r[6], '%s | ja «%s» es «%s»' % (r[7], r[4], r[5])))
        except Exception as x:
            avisos.append(('SAY_NO_EVALUADO', '%s: %s' % (type(x).__name__, x)))

    # ------------------------------------------------------------ vista previa
    def vista_problemas(self, c, s_juego):
        try:
            frm = self.R.NC.medida_fr(c.fr_text, c.pf) if c.fr_text and c.pf.fr_ref else None
            cods, _ = self.R.NC.problemas(s_juego, c.pf, frm)
            return list(dict.fromkeys(cods))
        except Exception:
            return []

    def vista_texto(self, c, texto, genero):
        """vista aproximada de un texto del editor aun no valido: tokens tal cual"""
        s = texto.replace('\n', '<NewLine>') if c.tipo == 'simple' else texto
        try: return self.vista(c, s, genero)
        except Exception: return None

    def vista(self, c, s, genero='masc', envolver=True):
        """cadena tokenizada (con NewLine/LF y ya sin marcas) -> {ventanas: [[lineas]], ...}. Colores con centinelas \\x01 \\x02; iconos \\x03."""
        R = self.R; RL, NC = R.RL, R.NC; pf = c.pf
        hm = HABLANTE_RE.match(s); hablante = hm.group(1) if hm else None
        s = s[RL.prefijo_len(s):]
        s = GEN_RE.sub(lambda m: m.group(1) if genero == 'fem' else m.group(2), s)
        lineas = []; activo = [False]
        for dura in RL.partir_lineas(s):
            if RL.no_ok(dura):
                txt = NC._pantalla(dura, pf, True); partes = self._envolver(txt, pf) if envolver else [txt]
            else:
                txt = self._plano_color(dura, pf, activo); partes = self._envolver_c(txt, pf) if envolver else [txt]
            lineas += partes
        n = pf.lineas if (pf.lineas and pf.envuelve) else (0 if pf.tipo in ('subtitulo', 'hud_fijo') else 4)
        vent = [lineas[i:i + n] for i in range(0, len(lineas), n)] if n else [lineas]
        return {'ventanas': vent, 'genero': genero, 'nlineas': len(lineas), 'nventanas': len(vent), 'hablante': hablante,
                'caja': {'tipo': pf.tipo, 'seguro': pf.seguro, 'duro': pf.duro, 'lineas': pf.lineas or 4}}

    def _envolver(self, txt, pf):
        return self.R.NC.envolver(txt, pf) if pf.envuelve else [txt]

    def _plano_color(self, dura, pf, activo):
        """linea dura -> texto de pantalla con centinelas de color; `activo` (lista de 1 bool) conserva el color entre lineas duras"""
        out = []; i = 0
        if activo[0]: out.append(ABRE_C)
        while i < len(dura):
            ch = dura[i]
            if ch == '<':
                if dura.startswith('<<', i): out.append('<'); i += 2; continue
                m = TOK_RE.match(dura, i) or re.compile(r'<UIColor:[0-9A-Fa-f]{6}>|<UIColorEnd>').match(dura, i)
                if m:
                    t = m.group(0); nom = re.match(r'<([A-Za-z0-9]+)', t).group(1)
                    if nom == 'ColorType':
                        out.append(CIERRA_C if activo[0] else ABRE_C); activo[0] = not activo[0]
                    elif nom == 'UIColor': out.append(ABRE_C); activo[0] = True
                    elif nom == 'UIColorEnd': out.append(CIERRA_C); activo[0] = False
                    elif nom in ('Num', 'Kilo'): out.append(('1234567890' * 2)[:pf.exp_num])
                    elif nom == 'Icon2': out.append(ICONO_C)
                    i += len(t); continue
            out.append(ch); i += 1
        return ''.join(out)

    @staticmethod
    def _ancho(t):
        return len(t.replace(ABRE_C, '').replace(CIERRA_C, '')) + t.count(ICONO_C)

    def _envolver_c(self, txt, pf):
        """envoltura voraz del juego (como nucleo.envolver) sobre texto con centinelas de color (anchura = caracteres visibles)"""
        if txt in ('', ABRE_C + CIERRA_C) or not pf.envuelve or not pf.seguro: return [txt]
        ws = re.split(r' (?! )', txt); out = []; cur = None
        for w in ws:
            if cur is None: cur = w; continue
            n = self._ancho(cur) + 1 + self._ancho(w)
            if n <= pf.seguro or (n <= pf.duro and PUNT.search(w.replace(CIERRA_C, '').replace(ABRE_C, ''))): cur += ' ' + w
            else: out.append(cur); cur = w
        out.append(cur)
        # reabrir/cerrar el color en cada linea para que cada una sea autonoma
        res = []; abierto = False
        for l in out:
            pref = ABRE_C if abierto else ''
            for ch in l:
                if ch == ABRE_C: abierto = True
                elif ch == CIERRA_C: abierto = False
            res.append(pref + l + (CIERRA_C if abierto else ''))
        return res
