"""Estados de flujo de trabajo («Por hacer» / «Hecho» / sin clasificar) por celda. Independientes del color de traduccion.
Se guardan SOLO en un fichero local del usuario (flujo.json en la carpeta de datos del editor), nunca en traducciones/ ni en el repo.
Clave de celda: hoja + row + sub + col."""
import csv, io, json, os, threading

POR_HACER, HECHO, SIN = 'por_hacer', 'hecho', 'sin'
ESTADOS = (POR_HACER, HECHO, SIN)
NOMBRES = {POR_HACER: 'Por hacer', HECHO: 'Hecho', SIN: 'Sin clasificar'}
_TXT_A_ESTADO = {'por_hacer': POR_HACER, 'por hacer': POR_HACER, 'hecho': HECHO, 'sin': SIN, 'sin clasificar': SIN, '': SIN}


def clave(hoja, row, sub, col):
    return '%s|%s|%s|%s' % (hoja, row, '' if sub is None else sub, col)


def partir_clave(k):
    hoja, row, sub, col = k.rsplit('|', 3)
    return hoja, int(row), (int(sub) if sub != '' else None), int(col)


class Flujo(object):
    def __init__(self, ruta):
        self.ruta = ruta; self.lock = threading.RLock(); self.datos = {}
        self.alcambiar = None   # callback(cambios|None) -> mantiene la columna materializada `flujo` de la BD (None = resincronizar todo)
        try:
            with open(ruta, encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d, dict): self.datos = {k: v for k, v in d.items() if v in (POR_HACER, HECHO)}
        except (OSError, ValueError):
            pass

    def estado(self, hoja, row, sub, col):
        return self.datos.get(clave(hoja, row, sub, col), SIN)

    def estado_sql(self, hoja, row, sub, col):
        return self.datos.get(clave(hoja, row, sub, col), SIN)

    def poner(self, celdas, estado):
        """celdas = iterable de (hoja,row,sub,col); estado 'sin' = quitar la marca. -> n cambiadas"""
        if estado not in ESTADOS: raise ValueError('estado desconocido: %s' % estado)
        n = 0; cambios = []
        with self.lock:
            for c in celdas:
                k = clave(*c)
                if estado == SIN:
                    if self.datos.pop(k, None) is not None: n += 1; cambios.append((tuple(c), SIN))
                elif self.datos.get(k) != estado: self.datos[k] = estado; n += 1; cambios.append((tuple(c), estado))
            if n: self._guardar()
        if n and self.alcambiar: self.alcambiar(cambios)   # fuera del cerrojo: evita interbloqueos con el de la BD
        return n

    def totales(self):
        with self.lock:
            t = {POR_HACER: 0, HECHO: 0}
            for v in self.datos.values(): t[v] = t.get(v, 0) + 1
            return t

    def _guardar(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.ruta)), exist_ok=True)
        tmp = self.ruta + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f: json.dump(self.datos, f, ensure_ascii=False, indent=0)
        os.replace(tmp, self.ruta)

    def exportar_tsv(self, ruta):
        with self.lock, open(ruta, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f, delimiter='\t', lineterminator='\n'); w.writerow(['hoja', 'row', 'sub', 'col', 'estado'])
            for k, v in sorted(self.datos.items()):
                h, r, s, c = partir_clave(k); w.writerow([h, r, '' if s is None else s, c, v])
            return len(self.datos)

    def importar_tsv(self, ruta, reemplazar=False):
        with open(ruta, encoding='utf-8', newline='') as f: return self.importar_texto(f.read(), reemplazar)

    def importar_texto(self, texto, reemplazar=False):
        """texto = contenido TSV (hoja, row, sub, col, estado) -> (importadas, ignoradas). reemplazar=True borra antes todas las marcas."""
        nuevas = {}; ign = 0
        for r in csv.DictReader(io.StringIO(texto.lstrip('\ufeff'), newline=''), delimiter='\t'):
            try:
                e = _TXT_A_ESTADO[(r.get('estado') or '').strip().lower()]
                s = (r.get('sub') or '').strip()
                nuevas[clave(r['hoja'], int(r['row']), int(s) if s else None, int(r['col']))] = e
            except (KeyError, ValueError, TypeError, AttributeError): ign += 1
        with self.lock:
            if reemplazar: self.datos = {}
            for k, e in nuevas.items():
                if e == SIN: self.datos.pop(k, None)
                else: self.datos[k] = e
            self._guardar()
        if self.alcambiar: self.alcambiar(None)
        return len(nuevas), ign
