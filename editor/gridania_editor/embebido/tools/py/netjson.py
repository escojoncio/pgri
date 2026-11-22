"""Serializador JSON que imita System.Text.Json con JavaScriptEncoder.Default
(el de tools/XivSpanish.BlobBuilder): escapa " \\ controles, < > & ' + ` y todo lo no-ASCII como \\uXXXX."""
_SHORT = {'"': '\\u0022', '\\': '\\\\', '\b': '\\b', '\t': '\\t', '\n': '\\n', '\f': '\\f', '\r': '\\r'}
def _s(s):
    out = ['"']
    for ch in s:
        if ch in _SHORT: out.append(_SHORT[ch])
        elif ch in "<>&'+`" or ord(ch) < 0x20 or ord(ch) >= 0x7F:
            o = ord(ch)
            if o > 0xFFFF:
                o -= 0x10000; out.append('\\u%04X\\u%04X' % (0xD800 + (o >> 10), 0xDC00 + (o & 0x3FF)))
            else: out.append('\\u%04X' % o)
        else: out.append(ch)
    out.append('"'); return ''.join(out)
def entry_line(source, target, sheet, row_id, field, exd_path, status='approved'):
    # sin exdPath el C# resuelve la pagina `_en` en silencio (ClientPatchBackend.cs:54): nunca se omite
    if not exd_path or not str(exd_path).strip(): raise ValueError('exdPath ausente o vacio (%s/%s.%s)' % (sheet, row_id, field))
    key = '{"sheet":%s,"rowId":%d,"field":%s,"exdPath":%s}' % (_s(sheet), int(row_id), _s(field), _s(exd_path))
    return '{"source":%s,"target":%s,"sourceKey":%s,"status":%s}' % (_s(source), _s(target), key, _s(status))
