#!/usr/bin/env -S python3 -I
"""CSV (hoja,rowId,campo,source_baliza,target,exdPath[,status]) -> translations.dat
(UN frame Zstandard nivel 19 de JSONL UTF-8 sin BOM, '\\n' tras cada linea incl. la ultima).
Toda fila necesita exdPath (si falta o esta vacio -> MissingExdPath) y status approved|gold.
Cada fila pasa el gate (port de SeStringCompatibilityValidator); si alguna falla no se escribe nada
salvo --force. Verifica el roundtrip descomprimiendo el resultado.
Uso: python3 -I build_blob.py --csv entradas.csv --out translations_test.dat [--jsonl-out x.jsonl] [--status approved] [--force]"""
import sys, os, csv, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sestring as S, zst
from netjson import entry_line

def escribir_blob(lines, out, jsonl_out=None, pares=None):
    """lineas JSONL (netjson.entry_line) -> .dat (un frame zstd-19, '\\n' tras cada linea). Verifica el roundtrip y que cada
    linea sea JSON valido (y, si se pasa `pares` [(source,target)], que lo refleje). -> (n, bytes_jsonl, bytes_zstd)"""
    payload = ('\n'.join(lines) + '\n').encode('utf-8')
    assert not payload.startswith(b'\xef\xbb\xbf')
    blob = zst.compress(payload, 19)
    back = zst.decompress(blob)
    assert back == payload, 'roundtrip distinto'
    js = [json.loads(ln) for ln in back.decode('utf-8').split('\n')[:-1]]
    assert len(js) == len(lines)
    for j, (s_, t_) in zip(js, pares or []):
        assert j['source'] == s_ and j['target'] == t_
    open(out, 'wb').write(blob)
    if jsonl_out: open(jsonl_out, 'wb').write(payload)
    return len(lines), len(payload), len(blob)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--jsonl-out'); ap.add_argument('--status', default='approved'); ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.csv, encoding='utf-8', newline='')))
    lines = []; bad = []; seen = set(); kept = []
    for r in rows:
        src, tgt = r['source_baliza'], r['target']
        if not tgt.strip(): bad.append((r, [('EmptyTarget', 'target vacio')])); continue
        if not (r.get('exdPath') or '').strip(): bad.append((r, [('MissingExdPath', 'sin exdPath: el C# resolveria la pagina _en en silencio')])); continue
        if (r.get('status') or a.status) not in ('approved', 'gold'): bad.append((r, [('BadStatus', 'status debe ser approved|gold')])); continue
        k = (r['hoja'], r['rowId'], r['campo'])
        if k in seen: bad.append((r, [('Duplicate', 'clave repetida')])); continue
        seen.add(k)
        v = S.validate(src, tgt) if (S.has_payloads(src) or S.has_reserved(tgt) or S.contiene_color_propio(tgt)) else []
        if v: bad.append((r, v))
        lines.append(entry_line(src, tgt, r['hoja'], r['rowId'], r['campo'], r['exdPath'], r.get('status') or a.status)); kept.append(r)
    for r, v in bad:
        print('GATE FAIL %s/%s.%s: %s' % (r['hoja'], r['rowId'], r['campo'], '; '.join('[%s] %s' % x for x in v)), file=sys.stderr)
    if bad and not a.force: sys.exit('abortado: %d fila(s) no pasan el gate' % len(bad))
    n, np_, nb = escribir_blob(lines, a.out, a.jsonl_out, [(r['source_baliza'], r['target']) for r in kept])
    print('OK %s: %d entradas, %d B JSONL -> %d B zstd(19), roundtrip identico' % (a.out, n, np_, nb))
if __name__ == '__main__': main()
