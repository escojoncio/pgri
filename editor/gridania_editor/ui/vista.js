/* Vista previa «como en el juego» (sin DOM: funciones puras que devuelven HTML; la UI y las pruebas con node la comparten).
   Modelo (el mismo que escribe el parcheador en el .dat y que calcula el servidor en celda.Motor.vista):
   - Fuente MONOESPACIADA: una columna = un caracter; el cuadro mide exactamente `duro` columnas (dialogo 61, creador de personaje 51...) con unidades `ch`; nunca se parte una linea por el ancho
     del panel (se desplaza en horizontal): un salto que se ve es un salto real del texto.
   - Columnas > seguro (recomendado, p. ej. 58) en ambar y > duro (limite del cuadro) en rojo; reglas verticales en esas dos columnas.
   - Ventana = como mucho `lineas` (4) lineas; la ultima ventana marca ■ y las demas ▼.
   - Colores del juego (centinelas \x01 abre, \x02 cierra), icono \x03 (2 columnas), macros de nombre/objeto expandidas por el servidor como '#' x ancho: se ven como una pieza con fondo
     (nunca como etiqueta cruda); cualquier etiqueta <...> que llegase se muestra como ⟨Nombre⟩ legible. */
(function (root) {
  'use strict';
  var ABRE = '\x01', CIERRA = '\x02', ICONO = '\x03', MAXL = 4;

  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

  function etiquetas(l) { return l.replace(/<\/?([A-Za-z][A-Za-z0-9]*)(?:[#:][^<>]*)?>/g, function (m, n) { return '⟨' + n + '⟩'; }); }

  function anchoLinea(l) { return l.replace(/[\x01\x02]/g, '').length + (l.match(/\x03/g) || []).length; }

  function palabras(l) { return l.replace(/[\x01\x02\x03]/g, '').trim().split(/\s+/).filter(Boolean).length; }

  /* HTML de UNA linea: segmentos por (color, zona, pieza). zona: '' | 'ex' (> seguro) | 'xx' (> duro). */
  function lineaHtml(l, seg, dur) {
    l = etiquetas(l);
    var toks = [], col = 0, color = false, i, c;
    for (i = 0; i < l.length; i++) {
      c = l[i];
      if (c === ABRE) { color = true; continue; }
      if (c === CIERRA) { color = false; continue; }
      toks.push({ ch: c, color: color, col: col, mac: false });
      col += (c === ICONO) ? 2 : 1;
    }
    // piezas: '#' x2 o mas (macro de nombre/objeto) y ⟨Etiqueta⟩
    var k = 0, j;
    while (k < toks.length) {
      if (toks[k].ch === '#') {
        j = k; while (j < toks.length && toks[j].ch === '#') j++;
        if (j - k >= 2) for (var q = k; q < j; q++) toks[q].mac = true;
        k = j;
      } else if (toks[k].ch === '⟨') {
        j = k; while (j < toks.length && toks[j].ch !== '⟩') j++;
        for (var q2 = k; q2 <= Math.min(j, toks.length - 1); q2++) toks[q2].mac = true;
        k = j + 1;
      } else k++;
    }
    var out = '', cur = null, buf = '';
    function cierra() { if (cur !== null) { out += '<span class="' + cur + '">' + buf + '</span>'; cur = null; buf = ''; } }
    for (i = 0; i < toks.length; i++) {
      var t = toks[i], z = (dur && t.col >= dur) ? 'xx' : ((seg && t.col >= seg) ? 'ex' : '');
      var cl = [t.color ? 'c' : '', z, t.mac ? 'mac' : '', t.ch === ICONO ? 'ico' : ''].filter(Boolean).join(' ');
      if (cl !== cur) { cierra(); cur = cl; }
      buf += (t.ch === ICONO) ? '▣' : esc(t.ch);
    }
    cierra();
    return out || '​';
  }

  /* columnas del cuadro: el limite duro (o el seguro); sin perfil (0) el de la linea mas ancha, con un minimo */
  function anchoCaja(v) {
    var d = v.caja.duro || v.caja.seguro || 0, m = 0;
    if (!d) v.ventanas.forEach(function (w) { w.forEach(function (l) { m = Math.max(m, anchoLinea(l)); }); });
    return d || Math.max(m, 24);
  }

  function problemas(v, w, ult, N) {
    var p = [], seg = v.caja.seguro, dur = v.caja.duro, tope = v.caja.lineas || MAXL;
    if (v.caja.tipo !== 'subtitulo' && v.caja.tipo !== 'hud_fijo' && w.length > tope) p.push('mas de ' + tope + ' lineas (' + w.length + ')');
    if (dur && w.some(function (l) { return anchoLinea(l) > dur; })) p.push('linea mas ancha que la caja');
    if (ult && N > 1 && w.length === 1 && palabras(w[0]) <= 2) p.push('ventana final huerfana');
    return p;
  }

  /* HTML de las ventanas de una vista (la respuesta `vista` del servidor). opt.compacto = fuente JP/FR: sin cuadro fijo ni avisos */
  function ventanasHtml(v, opt) {
    opt = opt || {};
    if (!v) return '';
    var seg = v.caja.seguro, dur = v.caja.duro, N = v.nventanas, W = anchoCaja(v), nom = v.hablante, filasMin = (v.caja.envuelve && v.caja.lineas) ? v.caja.lineas : 0;
    return v.ventanas.map(function (w, i) {
      var ult = i === N - 1, probs = opt.compacto ? [] : problemas(v, w, ult, N);
      var lin = w.map(function (l) {
        var a = anchoLinea(l), cl = '';
        if (!opt.compacto) cl = (dur && a > dur) ? 'mal' : ((seg && a > seg) ? 'aviso' : '');
        return '<div class="ln ' + cl + '"><span class="t">' + lineaHtml(l, opt.compacto ? 0 : seg, opt.compacto ? 0 : dur) + '</span><span class="nl" title="Salto de linea">↵</span>' +
          ((opt.compacto || !seg) ? '' : '<span class="an" title="Columnas de la linea / seguras (recomendado). Limite duro del cuadro: ' + dur + '">' + a + '/' + seg + '</span>') + '</div>';
      }).join('');
      var estilo = opt.compacto ? '' : ' style="--w:' + W + ';' + (filasMin ? 'min-height:' + (filasMin * 1.4) + 'em;' : '') + '"';
      var reglas = (opt.compacto || !seg) ? '' : ('<i class="regla" style="left:' + seg + 'ch" title="Ancho seguro (' + seg + ')"></i>' + (dur && dur !== seg ? '<i class="regla duro" style="left:' + dur + 'ch" title="Limite duro del cuadro (' + dur + ')"></i>' : ''));
      return '<div class="vent ' + (opt.compacto ? 'compacto ' : '') + (probs.length ? 'mala ' : '') + (v.caja.fija ? 'fija' : '') + '">' +
        (nom ? '<div class="nom" title="Hablante">' + esc(nom) + '</div>' : '') +
        '<div class="cuerpo"' + estilo + '>' + reglas + lin + '</div>' +
        '<div class="vpie"><span>ventana ' + (i + 1) + '/' + N + ' · ' + w.length + ' lineas</span>' + (probs.length ? '<span class="prob">⚠ ' + esc(probs.join('; ')) + '</span>' : '') +
        '<span class="sig" title="' + (ult ? 'Ultima ventana' : 'Pulsa para continuar') + '">' + (ult ? '■' : '▼') + '</span></div></div>';
    }).join('');
  }

  /* variantes a mostrar segun el selector: 'ambas' | 'fem' | 'masc'. Sin macro de genero (variantes null) una sola vista. -> [{g, titulo, vista}] */
  function variantes(r, sel) {
    if (!r) return [];
    if (!r.variantes) return r.vista ? [{ g: '', titulo: '', vista: r.vista }] : [];
    var todas = [['fem', '♀ Mujer'], ['masc', '♂ Hombre']];
    return todas.filter(function (x) { return sel === 'ambas' || !sel || sel === x[0]; }).map(function (x) { return { g: x[0], titulo: x[1], vista: r.variantes[x[0]] }; }).filter(function (x) { return x.vista; });
  }

  function vistaHtml(r, sel) {
    return variantes(r, sel).map(function (x) {
      return '<div class="vv">' + (x.titulo ? '<div class="vtit" title="Asi se ve si el jugador es ' + (x.g === 'fem' ? 'mujer' : 'hombre') + '">' + x.titulo + '</div>' : '') + ventanasHtml(x.vista, {}) + '</div>';
    }).join('');
  }

  /* texto de la barra de estado de la caja: tipo, columnas y aviso de caja fija / creador */
  function resumenCaja(v, suavizadoAplicado) {
    if (!v) return '';
    var c = v.caja, t = '(caja ' + c.tipo + (c.creador ? ', creador de personaje' : '') + ', ' + (c.seguro || '?') + '/' + (c.duro || '?') + ' car., max ' + (c.lineas || MAXL) + ' lineas por ventana, ' + v.nlineas + ' lineas, ' + v.nventanas + ' ventanas';
    if (c.fija) t += '; caja de ancho fijo: no se reajusta sola';
    if (suavizadoAplicado && c.tipo === 'subtitulo') t += '; tras el suavizado del .dat, que une saltos a media frase';
    return t + ')';
  }

  var MOTIVOS = { excluida: 'esta hoja (Balloon, NpcYell, ENpcResident, Lobby, CharaMake) queda fuera del suavizado del .dat', narrador: 'narrador (subtitulos): sus trozos nunca se funden',
    caja_fija: 'caja de ancho fijo: el .dat no la suaviza' };
  function textoSuavizado(s) {
    if (!s) return '';
    var m = { aplicado: 'Suavizado: <b>aplicado</b> (la vista muestra el espaciado corregido, igual que saldra en el .dat).', cumplia: 'Suavizado: <b class="ok">ya cumplia</b>, no hace falta cambiar nada.',
      no_aplica: 'Suavizado: no se aplica a esta celda' + (MOTIVOS[s.motivo] ? ' (' + MOTIVOS[s.motivo] + ').' : '.') }[s.suavizado] || '';
    if (s.reflujo === 'cambiada') m += ' Reflujo: la vista reajusta los saltos; pulsa «Usar texto con reflujo» para llevarlo al cuadro.';
    return m;
  }

  var api = { anchoLinea: anchoLinea, lineaHtml: lineaHtml, ventanasHtml: ventanasHtml, variantes: variantes, vistaHtml: vistaHtml, resumenCaja: resumenCaja, textoSuavizado: textoSuavizado, anchoCaja: anchoCaja, esc: esc };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.VistaJuego = api;
})(typeof window !== 'undefined' ? window : this);
