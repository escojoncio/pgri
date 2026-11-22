#!/usr/bin/env -S python3 -I
"""Reparador seguro de N_TROZOS sistematico: el ja tiene UN solo trozo y el traductor devolvio varios strings (partio la frase en lineas por anchura).
`unir_trozos(ja, es)` -> (es_nuevo, reparado). Solo actua si len(ja)==1, es es lista con >1 strings no vacios y sin saltos (\\n) ni CJK: los une con un espacio
(separados por espacios simples; sin espacios dobles). Nunca parte ni une en otros casos (ja con varios trozos: ambiguo, sigue rechazado).
Se usa con `aplicar_resultados.py --unir-trozos`; las demas validaciones (LONGITUD, glosario, digitos, intocables) siguen aplicandose despues."""
import re

def unir_trozos(ja, es):
    if not (isinstance(ja, list) and isinstance(es, list) and len(ja) == 1 and len(es) > 1): return es, False
    if not all(isinstance(t, str) and t.strip() for t in es): return es, False
    if any('\n' in t for t in es): return es, False
    return [re.sub(r' {2,}', ' ', ' '.join(t.strip() for t in es))], True
