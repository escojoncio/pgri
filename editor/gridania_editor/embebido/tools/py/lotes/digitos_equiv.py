"""Equivalencias de digitos ja/es (numeral kanji, G5/7世 -> romano, ancho completo, el fr manda). Compartido por auditar_glosario_items.py y aplicar_resultados.py.
Solo biblioteca estandar."""
import re, unicodedata
from collections import Counter
CJK = re.compile(r'[぀-ヿ㐀-鿿ｦ-ﾟ　]')

KNUM = '〇一二三四五六七八九'
ROMANO = {1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI', 7: 'VII', 8: 'VIII', 9: 'IX'}

def _kanji_valor(run):
    """candidatos (cadenas de digitos) de una racha de numerales kanji: posicional (五一 -> 51) y aditiva (十四 -> 14, 二十 -> 20)"""
    c = set()
    if all(ch in KNUM for ch in run): c.add(''.join(str(KNUM.index(ch)) for ch in run))
    if any(ch in '十百' for ch in run):
        n = 0; act = 0
        for ch in run:
            if ch in KNUM: act = KNUM.index(ch)
            else: n += (act or 1) * (10 if ch == '十' else 100); act = 0
        c.add(str(n + act))
    return c

def romano(n):
    r = ''
    for v, c in ((10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')):
        while n >= v: r += c; n -= v
    return r

def digitos_discrepantes(ja, es, fr=''):
    """-> (faltan, sobran) como cadenas. Equivalencias NO discrepantes: ancho completo (NFKC), numeral kanji en ja = mismo numero en cifras en es (五一 -> 51, 第二次 -> 2.ª),
    numero 1..20 en ja = numeral romano en es (G5 / 7世 / 第1種 -> V / VII / I); si el fr (sin japones) tiene los mismos digitos que el es, manda el fr (Stigma-1, 2.0)."""
    ja = unicodedata.normalize('NFKC', ja); es = unicodedata.normalize('NFKC', es)
    dj = Counter(re.findall(r'\d', ja)); de = Counter(re.findall(r'\d', es))
    falta = dj - de; sobra = de - dj
    for m in re.finditer(r'(?<!\d)(\d{1,2})(?!\d)', ja):          # numero arabigo en ja -> romano en es
        n = int(m.group(1))
        if 1 <= n <= 20 and not (Counter(m.group(1)) - falta) and re.search(r'(?<![A-Za-z])%s(?![A-Za-z])' % romano(n), es): falta -= Counter(m.group(1))
    if sobra:
        for m in re.finditer('[%s十百]+' % KNUM, ja):
            for cand in _kanji_valor(m.group(0)):
                cc = Counter(cand)
                if cc and not (cc - sobra) and re.search(r'(?<!\d)%s(?!\d)' % cand, es): sobra -= cc; break
    falta = +falta; sobra = +sobra
    if (falta or sobra) and (de or re.search(r'G\d', ja)) and fr and not CJK.search(fr) and Counter(re.findall(r'\d', unicodedata.normalize('NFKC', fr))) == de: return '', ''
    return ''.join(sorted(falta.elements())), ''.join(sorted(sobra.elements()))
