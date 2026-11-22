#!/usr/bin/env -S python3 -I
"""Convencion de nombre de campo del C# para hojas sin nombres de miembro (p. ej. quest/*): `Column<ordinal>`.
El ordinal cuenta SOLO las columnas de tipo String del EXH, en el orden del EXH (0 = primera columna String).
Fuente: vendor/XivSpanish.GameData/ExdPatcher.cs:229-232 (alias posicional Column{i} -> stringColumnOffsets[i]),
ExhLayout.cs / ExdResolver.ReadStringLayout (stringColumnOffsets = solo columnas String, en orden EXH) y
vendor/XivSpanish.Core/Translation/StringColumnFieldNames.cs (Resolve: i-esima columna String -> Column{i}).
Distinto del indice fisico de columna EXH (el `col` de textos/ja/*.jsonl): coinciden solo si ninguna columna no-String
precede a una String (en 201 de 7183 hojas con cadenas difieren).
Uso como biblioteca: col_to_field(h, col) / field_to_col(h, 'Column3'); h = Pack.exh(hoja).
CLI: python3 -I campos.py --game DIR_0a0000 --sheet quest/000/ManFst002_00085 --col 1   (col = indice EXH, como en textos/)"""
import sys, os, re, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def string_cols(h):
    """indices EXH de las columnas String, en orden"""
    return [i for i, (t, _) in enumerate(h['cols']) if t == 0]

def col_to_ordinal(h, col):
    """indice EXH de columna (`col` de textos/) -> ordinal entre columnas String (= N de Column<N> del C#)"""
    sc = string_cols(h)
    if col not in sc: raise ValueError('la columna EXH %d no es String' % col)
    return sc.index(col)

def ordinal_to_col(h, ordinal):
    sc = string_cols(h)
    if not 0 <= ordinal < len(sc): raise ValueError('ordinal %d fuera de rango (%d columnas String)' % (ordinal, len(sc)))
    return sc[ordinal]

def col_to_field(h, col, mode='ordinal'):
    """mode 'ordinal' (convencion del C#) o 'index' (heredado: indice fisico)"""
    return 'Column%d' % (col_to_ordinal(h, col) if mode == 'ordinal' else col)

def field_to_col(h, field, mode='ordinal'):
    m = re.fullmatch(r'Column(\d+)', field or '')
    if not m: raise ValueError('campo %r no es Column<N>' % field)
    n = int(m.group(1))
    if mode == 'ordinal': return ordinal_to_col(h, n)
    if n not in string_cols(h): raise ValueError('la columna EXH %d no es String' % n)
    return n

if __name__ == '__main__':
    from sqpack_raw import Pack
    ap = argparse.ArgumentParser(); ap.add_argument('--game', required=True); ap.add_argument('--sheet', required=True); ap.add_argument('--col', type=int, required=True)
    a = ap.parse_args(); h = Pack(a.game).exh(a.sheet)
    if h is None: sys.exit('sin EXH: ' + a.sheet)
    print('col EXH %d -> %s (columnas String EXH: %s)' % (a.col, col_to_field(h, a.col), string_cols(h)))

# ---------------------------------------------------------------------------------------------------------------
# Campos con NOMBRE (Name, Description, Text, Singular...) del corpus original -> columna EXH.
# C# (vendor/XivSpanish.GameData/SheetStringFieldResolver.cs, StringColumnFieldNames.cs, ExdPatcher.cs:215-232):
#  - El nombre sale de los tipos generados de Lumina.Excel (NO hay esquema en vendor/): el i-esimo miembro string (en orden de
#    declaracion) nombra la i-esima columna String; `ResolveByOffset` corrige las hojas permutadas (p. ej. TextCommand) comparando,
#    fila a fila, el valor tipado (Language.English) con las columnas String fisicas: cada miembro parte de "cualquier ordinal" y
#    se ESTRECHA por interseccion (si una fila no coincide con nadie se conserva el conjunto previo); si queda ambiguo o dos miembros
#    caen en el mismo ordinal -> null (fallback a orden de declaracion). Sin Lumina no se puede leer la lista de miembros, asi que
#    aqui se replica la misma resolucion por contenido usando como "valor tipado" el `source` del corpus (ingles).
#  - Independiente del idioma de la pagina: nombres y ordinales son posicionales por columna String (misma disposicion en _en y _ja).
#  - `Column<N>` es SIEMPRE un alias posicional valido (ExdPatcher.cs:229-232); por eso el .dat para _ja emite `Column<ordinal>`.
def resolver_nombres(h, filas_en, pares):
    """h: EXH; filas_en: {rowId: {col EXH: texto tokenizado _en}}; pares: [(campo, rowId, source_en)]
    -> (mapa {campo: col|None}, notas {campo: motivo}, confianza {campo: (coinciden, evaluadas)})"""
    sc = string_cols(h); cand = {}; tocado = set()
    for campo, rid, src in pares:
        cand.setdefault(campo, set(sc))
        if not src or rid not in filas_en: continue
        hit = {c for c in sc if filas_en[rid].get(c) == src}
        if hit:
            tocado.add(campo)
            n = cand[campo] & hit
            if n: cand[campo] = n
    mapa = {}; notas = {}
    for campo, v in cand.items():
        if len(v) == 1: mapa[campo] = next(iter(v))
        else: mapa[campo] = None; notas[campo] = ('ambiguo entre columnas %s' % sorted(v)) if campo in tocado else 'ninguna columna _en coincide'
    usados = {}
    for campo, c in mapa.items():
        if c is not None: usados.setdefault(c, []).append(campo)
    for c, fs in usados.items():
        if len(fs) > 1:
            for f in fs: mapa[f] = None; notas[f] = 'colision de %s en la columna %d' % (fs, c)
    conf = {}
    for campo, rid, src in pares:
        c = mapa.get(campo)
        if c is None or not src or rid not in filas_en or src not in filas_en[rid].values(): continue  # filas del corpus sin texto en el juego no cuentan
        a, b = conf.get(campo, (0, 0)); conf[campo] = (a + (filas_en[rid].get(c) == src), b + 1)
    return mapa, notas, conf

def nombre_a_col(mapas, hoja, campo):
    """mapas = {hoja: {campo: col}} (de resolver_nombres) o `Column<N>`. -> col EXH | None"""
    m = mapas.get(hoja, {})
    return m.get(campo)

def col_a_nombre(mapas, hoja, col):
    for k, v in mapas.get(hoja, {}).items():
        if v == col: return k
    return None

def col_a_campo(h, col):
    """campo que se escribe en el .dat para paginas _ja: alias posicional Column<ordinal> (siempre aceptado por el C#)"""
    return col_to_field(h, col)
