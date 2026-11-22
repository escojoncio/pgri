#!/usr/bin/env -S python3 -I
"""Detector de LATINISMOS (regla absoluta: castellano de ESPAÑA, jamás latinismos). Solo lee.
detectar(es, ja='') -> lista de (nivel, codigo, fragmento); nivel 'error' | 'aviso'.
  USTEDES   «ustedes» explicito (+ su/sus/les/los de la misma celda, solo informativo). AVISO si el ja es claramente formal (cortes), ERROR si no.
  VOSEO     vos, tenés, podés, sos, querés, mirá, vení, decí, hacé...   (ERROR)
  LEXICO    léxico americano frecuente (carro, celular, computadora, platicar, ahorita, boleto, durazno, frutilla, rentar, chamba, ¡órale!,
            lindo/a, pararse (= ponerse de pie), manejar un vehículo...)   (ERROR)
Falsos positivos evitados: las palabras ambiguas se buscan solo en minuscula (los nombres propios del juego llevan mayuscula); se ignora el texto entre
«» y comillas (nombres de objetos/lugares citados); «ahora mismo», «dale», «manejar un arma», «parar» no se marcan."""
import re, sys

USTEDES = re.compile(r'\bustedes\b', re.I)
PLURAL_USTEDES = re.compile(r'\b(?:su|sus|les|los|se)\b', re.I)
VOSEO = re.compile(r'(?<![\w-])(?:vos|(?-i:sos)|tenés|podés|querés|sabés|mirá|vení|decí|hacé|andá|pensá|sentate|quedate|acordate|fijate|decime|escuchá|esperá|dejá|vas a poder vos|tomá|traé|ponete|hacés)\b', re.I)
# solo minuscula (sensible a mayusculas) para no tocar nombres propios del juego
LEX_MIN = re.compile(r'\b(?:autos?|carros?|computadoras?|platic(?:ar|o|a|as|an|ando|amos)|ahorita|(?<!de )boletos?|duraznos?|frutillas?|pastos?|rentar|renta|rentamos|chambas?|chambear|lindos?|linda(?!\s+(?:con|por|en|a|al|hasta)\b)|lindas|parars?e|me paré|te paraste|se paró|se pararon|manej(?:ar|o|as|a|ando)\s+(?:un|el|una|la)\s+(?:carro|auto|coche|vehículo|carruaje|camión|barco|bicicleta)|(?<!en su )(?<!de )(?<!conserva el )(?<!conservar el )jugos?(?!\s+(?:digestivos?|gástricos?|de(?:\s+la)?\s+carne))|popotes?|frijoles?|elotes?|banquetas?|cobijas?|recámaras?|albercas?|chamarras?|playeras?|meseros?|meseras?|apúrate|apúrense|apurarse|ándale|andale|híjole|hijole|chido|chida|padrísimo|bacano|güey|wey|huevón|boludos?|pelotudos?|ya mero|al rato|ni modo|de plano)\b')
# «celular» = teléfono solo con determinante delante; «células»/«división celular» (adjetivo) no se marca. «de boleto» = seta (Boletus).
CELULAR_TEL = re.compile(r'\b(?:el|un|mi|tu|su|al|del|mis|tus|sus|los|unos|este|ese|otro)\s+celular(?:es)?\b')
LEX_ANY = re.compile(r'\b(?:órale|orale|párate|párese|apúrate|apúrense|ándale)\b', re.I)
FORMAL_JA = re.compile('ございま|でございま|です|ます|ませ|ください|下さい|くださ|いらっしゃ|なさい|なさる|おります|おりません|でしょう|ましょう|であります|申し|存じ|いただ|頂')
CITADO = re.compile(r'«[^»]*»|"[^"]*"|“[^”]*”')

def _frag(t, m): return re.sub(r'\s+', ' ', t[max(0, m.start() - 20):m.end() + 20]).strip()

def detectar(es, ja=''):
    """-> [(nivel, codigo, fragmento)]"""
    if isinstance(es, list): es = ' '.join(x for x in es if isinstance(x, str))
    if isinstance(ja, list): ja = ' '.join(x for x in ja if isinstance(x, str))
    es = es or ''; ja = ja or ''
    t = CITADO.sub(' ', es); out = []
    m = USTEDES.search(t)
    if m:
        formal = bool(FORMAL_JA.search(ja))
        extra = ' +su/les/los' if PLURAL_USTEDES.search(t) else ''
        out.append(('aviso' if formal else 'error', 'USTEDES', _frag(t, m) + extra))
    m = VOSEO.search(t)
    if m: out.append(('error', 'VOSEO', _frag(t, m)))
    m = LEX_MIN.search(t) or LEX_ANY.search(t) or CELULAR_TEL.search(t)
    if m: out.append(('error', 'LEXICO', _frag(t, m)))
    return out

def errores(es, ja=''): return [d for d in detectar(es, ja) if d[0] == 'error']

if __name__ == '__main__':
    for d in detectar(' '.join(sys.argv[1:])): print(d)
