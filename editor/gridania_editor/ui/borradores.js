/* Logica pura (sin DOM) de los borradores por celda. La carga index.html (<script src="/borradores.js">) y los tests con node (require). */
(function (root) {
'use strict';
function claveCelda(c) { return [c.hoja, c.row, c.sub == null ? '' : c.sub, c.col].join('|'); }
/* b: borrador {h,texto,base}; d: celda abierta {h,es_texto}. ninguno | igual | aplicar (borrador mas reciente y la celda no cambio) | conflicto */
function decidirBorrador(b, d) { if (!b) return 'ninguno'; if (b.texto === d.es_texto) return 'igual'; if (String(b.h) === String(d.h) && b.base === d.es_texto) return 'aplicar'; return 'conflicto'; }
function puedeEnviarBorrador(st) { return !st.cargando && st.celda != null && st.texto !== st.base; }
/* cada abrir() toma un testigo; solo la ultima aplica su resultado y mientras haya alguna pendiente no se envian borradores */
function crearCarga() { let seq = 0, pend = 0; return { iniciar() { seq++; pend++; return seq; }, vigente(t) { return t === seq; }, fin() { pend--; }, cargando() { return pend > 0; } }; }
/* si el borrador solo difiere de la celda por la normalizacion que aplica el guardado, es 'igual' (sin conflicto espurio) */
async function decidirNormalizado(b, d, normalizar) {
  const dec = decidirBorrador(b, d);
  if (dec !== 'conflicto' || !normalizar || String(b.h) !== String(d.h)) return dec;
  try { if ((await normalizar(b.texto)) === d.es_texto) return 'igual'; } catch (e) { /* sin normalizar: sigue el conflicto */ }
  return dec;
}
/* deps: api(ruta,cuerpo) -> Promise; mostrar(b,d) -> Promise<'borrador'|'actual'|'luego'> (un dialogo cada vez); normalizar(c,texto) -> Promise<string>; cambio() */
function crearGestor(deps) {
  const borr = {}, cola = {}, gen = {}, ocupado = {}, luego = new Set();
  let enviado = null, cadenaDlg = Promise.resolve();
  const cuerpo = (c) => ({ hoja: c.hoja, row: c.row, sub: c.sub, col: c.col });
  const cambio = () => { if (deps.cambio) deps.cambio(); };
  const completa = (k, ver) => k + (ver ? '#' + ver : '');
  /* cola serializada por celda: un borrar espera al POST en vuelo y un POST ya anulado por un borrar posterior no se envia */
  function enc(k, fn) {
    ocupado[k] = (ocupado[k] || 0) + 1;
    const p = (cola[k] || Promise.resolve()).catch(() => {}).then(fn);
    cola[k] = p.catch(() => {}).then(() => { ocupado[k]--; });
    return p;
  }
  const MAX_VERS = 5, nver = (v) => parseInt(String(v).replace(/\D/g, ''), 10) || 0;
  const versDe = (k) => Object.keys(borr).filter((kk) => kk.startsWith(k + '#')).sort((x, y) => nver(x.split('#')[1]) - nver(y.split('#')[1]));
  /* archiva sin duplicar un texto ya archivado y conserva como mucho MAX_VERS versiones (descarta las mas antiguas) */
  async function archivar(c, viejo) {
    const k = claveCelda(c), ex = versDe(k);
    if (ex.some((kk) => borr[kk].texto === viejo.texto)) return;
    const ver = 'a' + ((ex.length ? nver(ex[ex.length - 1].split('#')[1]) : 0) + 1), reg = Object.assign(cuerpo(c), { h: viejo.h, texto: viejo.texto, base: viejo.base, ver: ver });
    await deps.api('/api/borrador', reg); borr[completa(k, ver)] = Object.assign({ fecha: viejo.fecha }, reg);
    const todas = versDe(k);
    while (todas.length > MAX_VERS) { const kk = todas.shift(), v = borr[kk].ver; await deps.api('/api/borrador_borrar', Object.assign(cuerpo(c), { ver: v })); delete borr[kk]; }
  }
  /* persiste (o limpia) la marca «Decidir luego» en el propio borrador principal del servidor */
  async function marcarLuego(c, b, valor) {
    const k = claveCelda(c);
    if (valor) luego.add(k); else luego.delete(k);
    const reg = Object.assign(cuerpo(c), { h: b.h, texto: b.texto, base: b.base, luego: valor });
    await deps.api('/api/borrador', reg); borr[k] = Object.assign({}, b, reg, { fecha: Date.now() / 1000 });
  }
  function guardarBorradorDe(c, texto) {
    const k = claveCelda(c), g = gen[k] || 0;
    return enc(k, async () => {
      if ((gen[k] || 0) !== g) return false;                       /* anulado por un borrar posterior */
      const viejo = borr[k];
      if (viejo && luego.has(k) && viejo.texto !== texto) { await archivar(c, viejo); luego.delete(k); }   /* nunca pisa en silencio un borrador pendiente de «Decidir luego» */
      const reg = Object.assign(cuerpo(c), { h: c.h, texto: texto, base: c.base, luego: luego.has(k) });
      await deps.api('/api/borrador', reg); borr[k] = Object.assign({ fecha: Date.now() / 1000 }, reg); cambio(); return true;
    });
  }
  /* ver vacio = borrador principal. opts.archivarSi: texto guardado; un principal pendiente de decidir y distinto se archiva en vez de perderse */
  function borrarBorradorDe(c, ver, opts) {
    const k = claveCelda(c), full = completa(k, ver);
    if (!ver) { gen[k] = (gen[k] || 0) + 1; if (enviado && enviado.startsWith(k + '\u0000')) enviado = null; }
    return enc(k, async () => {
      const b = borr[full];
      if (!b) { if (!ver) luego.delete(k); return; }
      if (!ver && opts && opts.archivarSi !== undefined && luego.has(k) && b.texto !== opts.archivarSi) await archivar(c, b);
      await deps.api('/api/borrador_borrar', Object.assign(cuerpo(c), ver ? { ver: ver } : {}));
      delete borr[full]; if (!ver) luego.delete(k); cambio();
    });
  }
  /* estado: {cargando,celda,texto,base}. Texto distinto de la base -> borrador; igual -> se borra el del servidor (salvo uno pendiente de «Decidir luego») */
  async function tick(st) {
    if (st.cargando || st.celda == null) return;
    const c = st.celda, k = claveCelda(c);
    if (st.texto === st.base) { if (!luego.has(k) && (borr[k] || ocupado[k])) await borrarBorradorDe(c); return; }
    if (enviado === k + '\u0000' + st.texto) return;
    const marca = k + '\u0000' + st.texto;
    if (await guardarBorradorDe(c, st.texto)) enviado = marca;
  }
  /* al cambiar de celda: con texto sin guardar se guarda su borrador; con texto igual a la base se borra */
  async function alSalir(prev, textoPrev, base) {
    if (!prev) return;
    if (textoPrev !== base) { if (await guardarBorradorDe(prev, textoPrev)) enviado = claveCelda(prev) + '\u0000' + textoPrev; }
    else if (!luego.has(claveCelda(prev))) await borrarBorradorDe(prev);
  }
  function pedirDecision(b, d, vigente) {                           /* decisiones en cola: nunca dos dialogos a la vez */
    const p = cadenaDlg.then(() => (vigente && !vigente()) ? 'luego' : deps.mostrar(b, d));
    cadenaDlg = p.catch(() => {}); return p;
  }
  function borradoresDe(c) {
    const k = claveCelda(c), l = [];
    for (const kk of Object.keys(borr)) if (kk === k || kk.startsWith(k + '#')) l.push(borr[kk]);
    return l.sort((x, y) => (x.ver ? 1 : 0) - (y.ver ? 1 : 0) || nver(x.ver) - nver(y.ver));
  }
  /* ui: {vigente(), poner(texto,msg), msg(m)}. Se llama tras cargar la celda d (c = celda abierta) */
  async function resolver(c, d, ui) {
    const k = claveCelda(c); let aplicado = false;
    const poner = (t, m) => { ui.poner(t, m); enviado = k + '\u0000' + t; };
    for (const b of borradoresDe(c)) {
      if (!ui.vigente()) return;
      const ver = b.ver || '', dec = await decidirNormalizado(b, d, (t) => deps.normalizar(c, t));
      if (!ui.vigente()) return;
      if (dec === 'igual') { await borrarBorradorDe(c, ver); continue; }
      if (dec === 'aplicar' && !ver && !aplicado) { aplicado = true; if (luego.has(k)) await marcarLuego(c, b, false); poner(b.texto, 'Restaurado el borrador sin guardar de esta celda (' + new Date(b.fecha * 1000).toLocaleString('es') + '). Revisalo y pulsa Guardar, o «Descartar borrador».'); continue; }
      const r = await pedirDecision(b, d, ui.vigente); if (!ui.vigente()) return;
      if (r === 'borrador') { if (!ver && luego.has(k)) await marcarLuego(c, b, false); poner(b.texto, 'Borrador restaurado (la celda habia cambiado). Revisalo y pulsa Guardar.'); aplicado = true; }
      else if (r === 'actual') { await borrarBorradorDe(c, ver); ui.msg('Borrador descartado.'); }
      else { if (!ver) await marcarLuego(c, b, true); ui.msg('Esta celda tiene un borrador pendiente de decidir (se conserva).'); }
    }
  }
  function cargar(lista) { for (const k of Object.keys(borr)) delete borr[k]; luego.clear(); for (const b of lista || []) { borr[completa(claveCelda(b), b.ver)] = b; if (b.luego && !b.ver) luego.add(claveCelda(b)); } cambio(); }
  function tiene(k) { for (const kk of Object.keys(borr)) if (kk === k || kk.startsWith(k + '#')) return true; return false; }
  return { borr, luego, guardarBorradorDe, borrarBorradorDe, tick, alSalir, pedirDecision, resolver, cargar, tiene, borradoresDe, cola: () => Promise.all(Object.values(cola)) };
}
const api = { claveCelda, decidirBorrador, decidirNormalizado, puedeEnviarBorrador, crearCarga, crearGestor };
if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Borradores = api;
})(typeof self !== 'undefined' ? self : this);
