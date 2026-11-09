#!/usr/bin/env python3
"""Genera los iconos propios del parcheador (originales, sin assets de terceros):
 - 6 iconos de expansion en insignia circular (SVG + ResourceDictionary Avalonia con DrawingImage;
   solo geometrias, degradados lineales/radiales y Pen: nada de filtros, mascaras ni clipPath),
 - hoja de contacto docs/assets/expansiones-contacto.png (38 y 128 px; requiere rsvg-convert),
 - icono de la app (icon.ico, icon.icns, icon.png).
Uso: python3 -I tools/gen-assets/gen_assets.py   (desde la raiz del repo; requiere Pillow)."""
import math, os
from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
APP = os.path.join(ROOT, "src", "FFXIVSpanishPatcher.App")
INK = "#16121A"
OW = 1.5          # grosor de contorno uniforme (unidades de 64)
C, R = 32.0, 29.0  # insignia circular comun

# ---------------------------------------------------------------- modelo
class Lin:
    """Degradado lineal en coordenadas relativas a la caja de la forma (0..1)."""
    def __init__(self, x1, y1, x2, y2, *stops): self.p = (x1, y1, x2, y2); self.stops = stops
class Rad:
    """Degradado radial relativo a la caja de la forma (centro, radio 0..1)."""
    def __init__(self, cx, cy, r, *stops): self.p = (cx, cy, r); self.stops = stops

def S(d, fill, w=OW, stroke=INK): return (d, fill, stroke, w)     # forma con contorno
def F(d, fill): return (d, fill, None, 0)                          # forma sin contorno
def L(d, stroke=INK, w=OW): return (d, None, stroke, w)            # trazo

def f(v): return ("%.2f" % v).rstrip("0").rstrip(".")
def M(pts, close=True):
    """Polilinea simple."""
    s = "M" + " L".join(f"{f(x)},{f(y)}" for x, y in pts)
    return s + (" Z" if close else "")
def circ(cx, cy, r):
    return f"M{f(cx-r)},{f(cy)} A{f(r)},{f(r)} 0 1,1 {f(cx+r)},{f(cy)} A{f(r)},{f(r)} 0 1,1 {f(cx-r)},{f(cy)} Z"
def ell(cx, cy, rx, ry):
    return f"M{f(cx-rx)},{f(cy)} A{f(rx)},{f(ry)} 0 1,1 {f(cx+rx)},{f(cy)} A{f(rx)},{f(ry)} 0 1,1 {f(cx-rx)},{f(cy)} Z"
def on(a, r=R):
    a = math.radians(a); return (C + r*math.cos(a), C + r*math.sin(a))
def arc_to(a, r=R, sweep=1, large=0):
    x, y = on(a, r); return f"A{f(r)},{f(r)} 0 {large},{sweep} {f(x)},{f(y)}"
def star4(cx, cy, r, k=0.28):
    """Destello de 4 puntas con lados curvos."""
    q = r*k
    return (f"M{f(cx)},{f(cy-r)} Q{f(cx+q*0.35)},{f(cy-q*0.35)} {f(cx+r)},{f(cy)} "
            f"Q{f(cx+q*0.35)},{f(cy+q*0.35)} {f(cx)},{f(cy+r)} Q{f(cx-q*0.35)},{f(cy+q*0.35)} {f(cx-r)},{f(cy)} "
            f"Q{f(cx-q*0.35)},{f(cy-q*0.35)} {f(cx)},{f(cy-r)} Z")

def xform(shapes, k, cx=C, cy=C, dx=0.0, dy=0.0):
    """Escala uniforme k alrededor de (cx,cy) + traslacion; solo comandos absolutos M L H V C Q A Z."""
    import re
    def tp(x, y): return (cx + (x - cx)*k + dx, cy + (y - cy)*k + dy)
    out = []
    for d, fl, st, w in shapes:
        toks = re.findall(r"[MLHVCQAZ]|-?\d*\.?\d+(?:e-?\d+)?", d)
        res, i, cmd = [], 0, None
        while i < len(toks):
            t = toks[i]
            if t.isalpha():
                cmd = t; res.append(t); i += 1
                if t == "Z": continue
                continue
            if cmd in "MLCQ":
                x, y = tp(float(toks[i]), float(toks[i+1])); res.append(f"{f(x)},{f(y)}"); i += 2
            elif cmd == "H":
                res.append(f(cx + (float(t) - cx)*k + dx)); i += 1
            elif cmd == "V":
                res.append(f(cy + (float(t) - cy)*k + dy)); i += 1
            elif cmd == "A":
                rx, ry, rot, la, sw = toks[i:i+5]; x, y = tp(float(toks[i+5]), float(toks[i+6]))
                res.append(f"{f(float(rx)*k)},{f(float(ry)*k)} {rot} {la},{sw} {f(x)},{f(y)}"); i += 7
        out.append((" ".join(res).replace("M ", "M").replace("L ", "L").replace("C ", "C").replace("Q ", "Q")
                     .replace("A ", "A").replace("H ", "H").replace("V ", "V"), fl, st, w))
    return out

def badge(c0, c1, rim):
    """Fondo comun: disco con degradado radial + aro interior de luz."""
    return [
        S(circ(C, C, R), Rad(0.42, 0.36, 0.72, (0, c0), (1, c1)), 1.8),
        L(circ(C, C, R - 2.3), stroke=rim, w=0.9),
    ]
def rim_over():
    """Contorno final por encima de todo, para cerrar las figuras que tocan el borde."""
    return [L(circ(C, C, R), w=1.8)]

# ---------------------------------------------------------------- 1 meteorito
def meteorito():
    sh = badge("#4B4C9A", "#17183F", ("#FFFFFF", 0.16))
    for x, y, r in ((15, 41, 1.6), (21, 50, 1.1), (46, 13, 1.4), (52, 22, 1.0), (40, 54, 0.9), (11, 30, 0.9)):
        sh.append(F(star4(x, y, r*1.7), ("#FFF4D6", 0.85)))
    # estela: tres capas que se afilan hacia arriba-izquierda
    sh.append(S("M13,13 C21,16 30,19 44,27 C47,33 44,40 38,42 C27,33 18,22 9,9 Z",
                Lin(0, 0, 1, 1, (0, ("#E8432A", 0.0)), (0.35, "#E8552B"), (1, "#C2311F")), 1.4))
    sh.append(F("M13,12 C23,17 31,22 42,29 C44,33 42,37 38,39 C29,31 21,22 13,12 Z",
                Lin(0, 0, 1, 1, (0, ("#FF9A3C", 0.0)), (0.45, "#FF9A3C"), (1, "#FFB347"))))
    sh.append(F("M19,17 C27,22 33,26 40,31 C41,34 40,36 38,37 C32,31 26,24 19,17 Z",
                Lin(0, 0, 1, 1, (0, ("#FFF3C4", 0.0)), (0.5, "#FFE9A0"), (1, "#FFF8E0"))))
    # roca
    rock = ("M37,30 C40,25.5 47,24.5 51,28 C55.5,31.5 56,38 53,43 C50,48 43,50 38.5,47 "
            "C34,44.5 33,38.5 34.5,34.5 C35,33 36,31.5 37,30 Z")
    sh.append(S(rock, Lin(0.15, 0.1, 0.85, 0.95, (0, "#B39A86"), (0.55, "#7D6555"), (1, "#4A3A33"))))
    sh.append(F("M44,46.5 C49,46 52.5,42 53,37 C54,42 50.5,48 44,46.5 Z", ("#2E2420", 0.55)))
    sh.append(F("M39.5,30 C42,27.5 46,26.8 48.5,28.2 C45,28.5 42,30 40.5,32.5 Z", ("#F4E3D0", 0.75)))
    sh.append(S(ell(46.5, 34.5, 2.6, 2.1), Lin(0, 0, 0, 1, (0, "#4E3D35"), (1, "#8C7464")), 1.0))
    sh.append(S(ell(41.5, 41.5, 1.9, 1.6), Lin(0, 0, 0, 1, (0, "#4E3D35"), (1, "#8C7464")), 1.0))
    sh.append(S(ell(50.2, 41.2, 1.3, 1.1), Lin(0, 0, 0, 1, (0, "#4E3D35"), (1, "#8C7464")), 0.9))
    # brasas
    sh.append(S(ell(30.5, 38.5, 1.3, 1.3), "#FFB347", 0.9))
    sh.append(S(ell(26, 31, 0.9, 0.9), "#FFD27A", 0.8))
    return sh + rim_over()

# ---------------------------------------------------------------- utilidades de cinta
def ribbon(center, widths):
    """Contorno cerrado alrededor de una linea central con anchuras variables (poligono denso)."""
    L_, Rr = [], []
    n = len(center)
    for i, (x, y) in enumerate(center):
        x0, y0 = center[max(i-1, 0)]; x1, y1 = center[min(i+1, n-1)]
        dx, dy = x1-x0, y1-y0; l = math.hypot(dx, dy) or 1
        nx, ny = -dy/l, dx/l; w = widths[i]
        L_.append((x + nx*w[0], y + ny*w[0])); Rr.append((x - nx*w[1], y - ny*w[1]))
    return L_ + Rr[::-1]
def qcurve(p0, p1, p2, n=24):
    return [((1-t)**2*p0[0]+2*(1-t)*t*p1[0]+t*t*p2[0], (1-t)**2*p0[1]+2*(1-t)*t*p1[1]+t*t*p2[1])
            for t in [i/n for i in range(n+1)]]

# ---------------------------------------------------------------- 2 dragon blanco
def dragon():
    sh = badge("#7DB2E3", "#1B3A68", ("#FFFFFF", 0.22))
    WHITE = Lin(0.2, 0, 0.8, 1, (0, "#FFFFFF"), (0.55, "#EEF3F9"), (1, "#C3D2E4"))
    SHADE = "#AFC0D6"
    MEMB = Lin(0, 0, 1, 1, (0, "#E6EEF8"), (1, "#9DB3CF"))
    # ala detras: brazo grueso hasta la muneca, tres dedos y membrana festoneada
    wing = ("M31,33 C28,25 25.5,17 24,9.5 C21,11.8 15.5,13.6 10.2,15 "
            "C11.6,16.6 12,19 11.2,21 C12.5,21.5 13.5,23.5 13.5,26 C15.5,26.5 17,28 17.5,30.5 "
            "C20.5,30.5 23.5,32.5 25.5,36 Z")
    sh.append(S(wing, MEMB))
    sh.append(L("M24,10 L11.2,21 M24,10 L13.5,26 M24,10 L17.5,30.5", stroke="#7F98B9", w=0.9))
    sh.append(S("M31,33 C28,25 25.5,17 24,9.5 C26,10 27.5,11.5 28,13.5 C29.5,20 31.5,26 34,31 Z", WHITE, 1.2))
    sh.append(S("M24,9.5 C23.5,7.5 24.5,6 26,5.2 C25.6,6.8 25.8,8 26.6,9.2 Z", "#E9DFC6", 0.9))  # garra
    # cuello y pecho que salen por abajo
    a1, a2 = 130, 64
    x1, y1 = on(a1); x2, y2 = on(a2)
    body = (f"M{f(x1)},{f(y1)} C17,47 21.5,40.5 26.5,35 C30,31 31.5,26 33,22 C35,18 39,16 43,17 "
            f"C46,18 47.5,21.5 46,25 C43.5,29 38.6,32.5 37.6,38.5 C36.8,44 39.2,50.5 {f(x2)},{f(y2)} "
            f"{arc_to(a1, sweep=1)} Z")
    sh.append(S(body, WHITE))
    # pinchos dorsales a lo largo de la nuca (base sobre el borde del cuello)
    for (x, y, nx, ny) in ((32.2, 25.5, -1, -0.15), (29.6, 31.2, -1, 0.1), (25.4, 36.4, -1, 0.45), (21.2, 41.6, -1, 0.7)):
        l = math.hypot(nx, ny); nx, ny = nx/l, ny/l; tx, ty = -ny, nx
        sh.append(S(f"M{f(x+tx*1.8)},{f(y+ty*1.8)} L{f(x+nx*3.6-tx*0.6)},{f(y+ny*3.6-ty*0.6)} L{f(x-tx*1.8)},{f(y-ty*1.8)} Z",
                    "#D9E3EF", 1.0))
    sh.append(F("M37.6,38.5 C38.6,32.5 43.5,29 46,25 C46,30 41.5,33.6 40,38.6 C39,44 40.8,50 44.2,56.6 C40,51.6 37,45 37.6,38.5 Z",
                (SHADE, 0.8)))
    sh.append(L("M28.5,51 C31,49.2 34,49.2 36.6,51 M27.5,45 C29.8,43.3 32.7,43.3 35.1,45 M28.6,39.3 C30.6,37.8 33,37.8 35,39.3",
                stroke="#93A8C3", w=0.9))
    # cuernos largos hacia atras
    HORN = Lin(0, 0, 1, 1, (0, "#FBF2DC"), (1, "#BFA67A"))
    sh.append(S("M38.5,18.5 C35,14.5 30.5,11.5 25.5,10.8 C30,13 33,15.8 35.6,20.3 Z", HORN, 1.2))
    sh.append(S("M42,16.8 C40.5,12 37.5,8.5 33,6.5 C36.4,9.6 38.4,13 39,17.6 Z", HORN, 1.2))
    # interior de la boca
    sh.append(S("M47,25.5 L57.5,24.2 L56.5,28.3 Z", "#7A1A2E", 1.0))
    # cabeza: craneo, hocico en cuna, mandibula abierta
    head = ("M36.8,20.5 C38.5,16.5 43,14.6 47.5,15.6 C50.5,16.3 53,18 55.5,19.6 L58.6,21.4 "
            "C59.6,22 59.4,23.8 58.2,24.2 L48.5,25.8 L56.8,27.6 C57.6,27.9 57.4,28.8 56.6,29 "
            "C53,30 49,30.4 46,29.8 C42.3,29.2 39.3,27.7 37.6,25.4 C36.6,24 36.3,22.2 36.8,20.5 Z")
    sh.append(S(head, WHITE))
    sh.append(F("M46,29.8 C49,30.4 53,30 56.6,29 C53,28.6 50,28.4 47.5,27.6 Z", (SHADE, 0.9)))
    sh.append(S("M53.6,24.7 L54.5,26.6 L55.4,24.5 Z", "#FFFFFF", 0.7))   # colmillo
    sh.append(S("M43.6,20.6 C45.2,19.3 47.6,19.4 48.8,20.8 C47.2,21.9 45.2,21.9 43.6,20.6 Z", "#3A9BFF", 0.9))  # ojo
    sh.append(F(ell(46.3, 20.6, 0.45, 0.75), "#08214A"))
    sh.append(L("M42.6,19 C44.6,17.6 47.6,17.4 50,18.8", w=1.1))                 # ceja
    sh.append(F(ell(56.6, 21.9, 0.6, 0.42), INK))                                # fosa nasal
    sh.append(S("M38,23.5 C35.6,23.8 34.4,25.6 34.4,27.8 C36,27 37.3,27 38.6,27.5 Z", "#DCE5F0", 1.0))  # aleta
    return sh + rim_over()

# ---------------------------------------------------------------- 3 katana
def katana():
    sh = badge("#4D5470", "#14162A", ("#FFFFFF", 0.14))
    sh.append(F(circ(21.5, 21.5, 11), Rad(0.5, 0.5, 0.5, (0, ("#FFF6DA", 0.35)), (1, ("#FFF6DA", 0.0)))))
    sh.append(S(circ(21.5, 21.5, 8), Rad(0.4, 0.38, 0.65, (0, "#FFFBEA"), (1, "#E9D9A8")), 1.2))  # luna
    sh.append(F("M16.6,19.6 C17.4,17.6 19,16.8 20.6,17.4 C19,18 18,19.2 17.8,20.8 Z", ("#FFFFFF", 0.7)))
    # hoja: linea central curva, punta kissaki
    cl = qcurve((24.5, 40.5), (37, 29), (48.2, 16), 30)
    wd = [(2.4, 2.4) for _ in cl]
    pts = ribbon(cl, wd)
    ex, ey = cl[-1]; dx, dy = ex - cl[-2][0], ey - cl[-2][1]; l = math.hypot(dx, dy); dx, dy = dx/l, dy/l
    nx, ny = -dy, dx
    tip = (ex + dx*3.4 - nx*1.9, ey + dy*3.4 - ny*1.9)
    blade = M(pts[:len(cl)] + [tip] + pts[len(cl):])
    sh.append(S(blade, Lin(0, 0, 1, 1, (0, "#FFFFFF"), (0.5, "#E6ECF3"), (1, "#A9B7C8"))))
    sh.append(L(M([(x + 0.55*0.7, y + 0.55*0.7) for x, y in cl[1:-3]], close=False), stroke="#7A8BA2", w=0.8))  # shinogi
    # sangre en el filo (lado inferior-derecho) con chorreones
    edge = ribbon(cl, [(2.4, 0)] * len(cl))[:len(cl)]  # borde del filo (lado convexo)
    i0, i1 = 9, 21
    seg = edge[i0:i1]
    inner = [(x - 1.9*0.7*math.sin(math.pi*(k+0.5)/len(seg))**0.6, y - 1.9*0.7*math.sin(math.pi*(k+0.5)/len(seg))**0.6) for k, (x, y) in enumerate(seg)]
    blood = seg + inner[::-1]
    BL = Lin(0, 0, 1, 1, (0, "#E3242B"), (1, "#9A0E16"))
    for j, ln in ((13, 4.6), (18, 2.8)):
        x, y = edge[j]
        sh.append(S(f"M{f(x-0.8)},{f(y-1)} C{f(x-0.4)},{f(y+ln*0.6)} {f(x-1.3)},{f(y+ln*0.75)} {f(x-1.2)},{f(y+ln+0.2)} "
                    f"C{f(x-1.2)},{f(y+ln+1.6)} {f(x+1.2)},{f(y+ln+1.6)} {f(x+1.2)},{f(y+ln+0.2)} "
                    f"C{f(x+1.3)},{f(y+ln*0.75)} {f(x+0.5)},{f(y+ln*0.6)} {f(x+0.9)},{f(y-1.2)} Z", BL, 0.9))
    sh.append(S(M(blood), BL, 1.0))
    x, y = edge[13]
    sh.append(S(f"M{f(x)},{f(y+8.6)} C{f(x-1.3)},{f(y+9.8)} {f(x-1.1)},{f(y+11.2)} {f(x)},{f(y+11.4)} "
                f"C{f(x+1.1)},{f(y+11.2)} {f(x+1.3)},{f(y+9.8)} {f(x)},{f(y+8.6)} Z", "#D81E28", 0.9))
    # habaki dorado
    sh.append(S("M22.6,39.6 L24.6,38 L27,41.2 L25,42.8 Z", Lin(0, 0, 1, 1, (0, "#F8D98A"), (1, "#B8892F")), 1.0))
    # tsuba: hierro oscuro con aro dorado
    sh.append(S("M18.6,39.2 C20.6,36.8 24.6,37.6 26.8,40.6 C28.8,43.4 28.3,46.8 25.8,48 "
                "C23.2,49.2 19.6,47.6 18,44.6 C17,42.6 17.4,40.6 18.6,39.2 Z",
                Lin(0, 0, 1, 1, (0, "#E6BE62"), (0.5, "#A9782A"), (1, "#5E4214"))))
    sh.append(S("M20.4,40.6 C21.8,39.4 24.2,39.9 25.5,41.8 C26.8,43.6 26.6,45.6 25.2,46.3 "
                "C23.6,47 21.4,46 20.3,44.2 C19.6,43 19.6,41.6 20.4,40.6 Z", "#2B2A33", 0.8))
    # tsuka con trenzado en rombos
    grip = ribbon([(21.6, 46.6), (15.8, 52.4)], [(2.1, 2.1), (2.1, 2.1)])
    sh.append(S(M(grip), Lin(0, 0, 1, 1, (0, "#3C3F70"), (1, "#1B1C3A"))))
    for t in (0.22, 0.6):
        x = 21.6 + (15.8 - 21.6) * t; y = 46.6 + (52.4 - 46.6) * t
        sh.append(S(f"M{f(x-1.25)},{f(y-1.25)} L{f(x+0.55)},{f(y-0.55)} L{f(x+1.25)},{f(y+1.25)} L{f(x-0.55)},{f(y+0.55)} Z",
                    "#D4D7F0", 0.6))
    sh.append(S(circ(15.4, 52.8, 2.1), Lin(0, 0, 1, 1, (0, "#E6BE62"), (1, "#6E4E17")), 1.0))  # kashira
    return sh + rim_over()

# ---------------------------------------------------------------- 4 luz y sombra
def luz_sombra():
    sh = badge("#FFF4CF", "#E0A63A", ("#FFFFFF", 0.45))
    a1, a2 = -84, 96
    x1, y1 = on(a1, R); x2, y2 = on(a2, R)
    dark = (f"M{f(x1)},{f(y1)} C27,12 36,17 31,24 C27,29.5 36.5,34.5 31.5,41 C28,46 34,52 {f(x2)},{f(y2)} "
            f"{arc_to(a1, sweep=1)} Z")
    sh.append(S(dark, Rad(0.35, 0.5, 0.85, (0, "#5A3DA6"), (1, "#190E33")), 1.4))
    # zarcillos de sombra que invaden la luz
    sh.append(S("M30,22 C34,19 39,18 42,20.5 C39,20 36.5,21.5 35.8,24 C35,22.6 32.6,22 30,22 Z", "#3A2675", 1.1))
    sh.append(S("M31.5,42 C35,44.5 39.5,45.5 42.5,43.5 C40,46.5 35.5,47.5 32,46.5 Z", "#3A2675", 1.1))
    sh.append(F("M9,31 C12.5,24 19,22 23.5,24.5 C18.5,25 14.5,27.5 11.5,32.5 Z", ("#A08CF5", 0.5)))
    sh.append(F("M11,44 C14.5,40.5 19.5,40 23,42.5 C19,42.8 15.5,44.5 13,47.5 Z", ("#A08CF5", 0.4)))
    # resplandor
    sh.append(F(circ(32, 32, 16), Rad(0.5, 0.5, 0.5, (0, ("#FFFFFF", 0.95)), (0.45, ("#FFF3C0", 0.6)), (1, ("#FFE08A", 0.0)))))
    # destello en cruz (dos estrellas de 4 puntas)
    sh.append(S(star4(32, 32, 9.5, 0.55).replace("Z", "Z"), Lin(0, 0, 1, 1, (0, "#FFF7D6"), (1, "#FFC44D")), 1.1))
    sh.append(S(star4(32, 32, 15.5, 0.38), Rad(0.5, 0.5, 0.5, (0, "#FFFFFF"), (0.6, "#FFF6D2"), (1, "#FFD46B")), 1.4))
    sh.append(F(circ(32, 32, 2.6), "#FFFFFF"))
    # esquirlas: luz en la sombra y sombra en la luz
    for x, y, r, col in ((15, 22, 1.8, "#FFE9A6"), (13, 38, 1.4, "#FFE9A6"), (20, 49, 1.2, "#FFE9A6"),
                          (48, 21, 1.6, "#3A2675"), (51, 40, 1.8, "#3A2675"), (44, 50, 1.2, "#3A2675")):
        sh.append(S(f"M{f(x)},{f(y-r*1.4)} L{f(x+r)},{f(y)} L{f(x)},{f(y+r*1.4)} L{f(x-r)},{f(y)} Z", col, 0.8))
    return sh + rim_over()

# ---------------------------------------------------------------- 5 pluma azul
def pluma():
    bg = badge("#F2C46B", "#8A4C17", ("#FFFFFF", 0.3))
    sh = []
    for x, y, r in ((14, 18, 1.6), (50, 48, 1.4), (47, 13, 1.0), (19, 50, 1.0)):
        sh.append(F(star4(x, y, r*1.8), ("#FFF7DF", 0.9)))
    # vane izquierdo y derecho separados por el raquis curvo (de abajo-izquierda a arriba-derecha)
    left = ("M15,50 C14,40 18,29 26,21 C33,14 42,10 51,9 C47,12 44,15 42.5,17.5 C44,17.5 45.5,17.6 46.5,18 "
            "C42,24 37,30 31,35 C27,38.5 21,44 15,50 Z")
    right = ("M15,50 C21,44 27,38.5 31,35 C37,30 42,24 46.5,18 C49,15.5 50.5,12 51,9 C53,14 53.5,21 50,28 "
             "C48.5,31 46,33.5 43,35 C44.5,35.5 46,35.6 47,35.5 C42,41 35,45 27,47.5 C23,48.8 19,49.6 15,50 Z")
    sh.append(S(left, Lin(0, 0, 1, 1, (0, "#9FD4FF"), (0.5, "#3F8EF0"), (1, "#1F5FCC"))))
    sh.append(S(right, Lin(0, 0, 1, 1, (0, "#3E7FE0"), (0.6, "#1D4FB0"), (1, "#16337A"))))
    # barbas
    sh.append(L("M22,42 C21,37 22.5,32 25.5,28 M27,37 C26.5,32 28.5,26.5 32,22.5 M33,31.5 C33,27 35,22 39,18",
                stroke=("#D8EEFF", 0.85), w=0.9))
    sh.append(L("M25,45.5 C30,45 35,43 39,40 M31,40.5 C36,40 40,37.5 43.5,34 M37,34.5 C41.5,33.5 45,31 47.5,27.5",
                stroke=("#0F2E6E", 0.7), w=0.9))
    # raquis + calamo
    sh.append(L("M12.8,52.8 C15,50.5 18,47 23,42 C31,34 40,26 51,9", stroke=INK, w=2.4))
    sh.append(L("M13.4,52.2 C15.5,50 18,47 23,42 C31,34 40,26 50.4,10", stroke="#FFF3D6", w=0.9))
    return bg + xform(sh, 0.9, dx=0.6, dy=1.4) + rim_over()

# ---------------------------------------------------------------- 6 ruina de piedra
def ruina():
    sh = badge("#F6B26B", "#9E3F3A", ("#FFFFFF", 0.25))
    sh.append(S(circ(32, 30, 9.5), Rad(0.45, 0.4, 0.6, (0, "#FFF6D0"), (1, "#FFC65A")), 1.0))  # sol del alba
    # selva al fondo
    a1, a2 = 172, 8
    x1, y1 = on(a1); x2, y2 = on(a2)
    sh.append(S(f"M{f(x1)},{f(y1)} C8,32 12,30 15,32 C17,28 22,29 23,32 L41,32 C43,28.5 47,28.5 49,31 "
                f"C51,29 55,29 57,31 C58.5,31 60,32 {f(x2)},{f(y2)} {arc_to(a1)} Z",
                Lin(0, 0, 0, 1, (0, "#3E8A55"), (1, "#173D2A")), 1.2))
    STONE = Lin(0, 0, 1, 1, (0, "#E9E1CC"), (0.6, "#C4B79A"), (1, "#8F8169"))
    SHADOW = ("#5E5242", 0.45)
    # columna izquierda (completa) con capitel
    sh.append(S("M13,23 H27 V27 H13 Z", STONE, 1.3))
    for y0 in (27, 34, 41, 48):
        sh.append(S(f"M15,{y0} H25 V{y0+7} H15 Z", STONE, 1.2))
    sh.append(F("M22,27 H25 V55 H22 Z", SHADOW))
    # arco roto que sale de la columna
    sh.append(S("M27,23 C33,17.5 39,16 44,17 L43,21.5 C39,21 34,22.5 31,25.5 L27,27 Z", STONE, 1.3))
    sh.append(L("M33.5,19.2 L35,23.4 M39,17.3 L39.4,21.4", stroke="#7C6F59", w=0.9))
    # columna derecha (rota)
    sh.append(S("M39,41 H49 V55 H39 Z", STONE, 1.2))
    sh.append(S("M39,34 L42,31.5 L44.5,34 L47,32 L49,34.5 V41 H39 Z", STONE, 1.2))
    sh.append(F("M46,34 L49,34.5 V55 H46 Z", SHADOW))
    # suelo
    a3, a4 = 150, 30
    x3, y3 = on(a3); x4, y4 = on(a4)
    sh.append(S(f"M{f(x3)},{f(y3)} C14,52 22,54.5 32,54 C42,53.5 50,52 {f(x4)},{f(y4)} {arc_to(a3)} Z",
                Lin(0, 0, 0, 1, (0, "#6E9A4E"), (1, "#2F5A2C")), 1.3))
    # bloque caido
    sh.append(S("M28,55 L29.5,49.5 L35.5,49 L36.5,54.5 Z", STONE, 1.2))
    # enredadera con hojas sobre la columna
    sh.append(L("M17,24 C20,30 15,36 19,42 C22,47 18,51 20,55", stroke="#1F5A2E", w=1.2))
    for x, y, a in ((18.5, 29, -30), (16.5, 37, 200), (20.2, 44.5, -20), (19, 51.5, 210)):
        dx, dy = 3*math.cos(math.radians(a)), 3*math.sin(math.radians(a))
        sh.append(S(f"M{f(x)},{f(y)} Q{f(x+dx*0.5-dy*0.6)},{f(y+dy*0.5+dx*0.6)} {f(x+dx)},{f(y+dy)} "
                    f"Q{f(x+dx*0.5+dy*0.6)},{f(y+dy*0.5-dx*0.6)} {f(x)},{f(y)} Z", "#4FAE5A", 0.8))
    return sh + rim_over()

ICONS = [
    ("meteorito", "Meteorito", meteorito()),
    ("dragon-blanco", "Dragón blanco", dragon()),
    ("katana", "Katana ensangrentada", katana()),
    ("luz-y-sombra", "Luz y sombra", luz_sombra()),
    ("pluma-azul", "Pluma azul", pluma()),
    ("ruina-piedra", "Ruina de piedra", ruina()),
]

# ---------------------------------------------------------------- salida
def _col(c):
    """-> (#RRGGBB, alpha)"""
    return (c[0], c[1]) if isinstance(c, tuple) else (c, 1.0)
def _argb(c):
    h, a = _col(c)
    return h if a >= 1 else "#%02X%s" % (round(a * 255), h[1:])

def svg(name, shapes):
    defs, body = [], []
    for i, (d, fl, s, w) in enumerate(shapes):
        attrs = f'd="{d}"'
        if fl is None:
            attrs += ' fill="none"'
        elif isinstance(fl, (Lin, Rad)):
            gid = f"g{i}"
            st = "".join(f'<stop offset="{f(o)}" stop-color="{_col(c)[0]}"'
                         + (f' stop-opacity="{f(_col(c)[1])}"' if _col(c)[1] < 1 else "") + "/>" for o, c in fl.stops)
            if isinstance(fl, Lin):
                x1, y1, x2, y2 = fl.p
                defs.append(f'<linearGradient id="{gid}" x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}">{st}</linearGradient>')
            else:
                cx, cy, r = fl.p
                defs.append(f'<radialGradient id="{gid}" cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}">{st}</radialGradient>')
            attrs += f' fill="url(#{gid})"'
        else:
            h, a = _col(fl)
            attrs += f' fill="{h}"' + (f' fill-opacity="{f(a)}"' if a < 1 else "")
        if s:
            h, a = _col(s)
            attrs += f' stroke="{h}" stroke-width="{f(w)}"' + (f' stroke-opacity="{f(a)}"' if a < 1 else "")
        body.append(f"  <path {attrs}/>")
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" '
           'stroke-linejoin="round" stroke-linecap="round">']
    if defs:
        out.append("  <defs>" + "".join(defs) + "</defs>")
    return "\n".join(out + body + ["</svg>"]) + "\n"

def _brush_xaml(fl, ind):
    st = "".join(f'<GradientStop Offset="{f(o)}" Color="{_argb(c)}"/>' for o, c in fl.stops)
    if isinstance(fl, Lin):
        x1, y1, x2, y2 = fl.p
        return (f'{ind}<GeometryDrawing.Brush><LinearGradientBrush StartPoint="{f(x1*100)}%,{f(y1*100)}%" '
                f'EndPoint="{f(x2*100)}%,{f(y2*100)}%">{st}</LinearGradientBrush></GeometryDrawing.Brush>')
    cx, cy, r = fl.p
    return (f'{ind}<GeometryDrawing.Brush><RadialGradientBrush Center="{f(cx*100)}%,{f(cy*100)}%" '
            f'GradientOrigin="{f(cx*100)}%,{f(cy*100)}%" RadiusX="{f(r*100)}%" RadiusY="{f(r*100)}%">{st}'
            f'</RadialGradientBrush></GeometryDrawing.Brush>')

def xaml():
    o = ['<ResourceDictionary xmlns="https://github.com/avaloniaui"',
         '                    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">',
         '  <!-- Generado por tools/gen-assets/gen_assets.py. No editar a mano. -->']
    for key, label, shapes in ICONS:
        k = "".join(p.capitalize() for p in key.split("-"))
        o.append(f'  <DrawingImage x:Key="Exp{k}">')
        o.append('    <DrawingGroup>')
        o.append('      <GeometryDrawing Brush="Transparent" Geometry="M0,0 L64,0 L64,64 L0,64 Z"/>')
        for d, fl, s, w in shapes:
            attrs = f'Geometry="{d}"'
            if fl is not None and not isinstance(fl, (Lin, Rad)):
                attrs += f' Brush="{_argb(fl)}"'
            inner = []
            if isinstance(fl, (Lin, Rad)):
                inner.append(_brush_xaml(fl, "        "))
            if s:
                inner.append(f'        <GeometryDrawing.Pen><Pen Brush="{_argb(s)}" Thickness="{f(w)}" '
                             'LineJoin="Round" LineCap="Round"/></GeometryDrawing.Pen>')
            if inner:
                o.append(f'      <GeometryDrawing {attrs}>')
                o.extend(inner)
                o.append('      </GeometryDrawing>')
            else:
                o.append(f'      <GeometryDrawing {attrs}/>')
        o.append('    </DrawingGroup>')
        o.append('  </DrawingImage>')
    o.append('</ResourceDictionary>')
    return "\n".join(o) + "\n"

def contact_sheet(path):
    """Hoja de contacto (requiere rsvg-convert): fila a 38 px y fila a 128 px sobre el fondo de la barra."""
    import subprocess, tempfile
    tmp = tempfile.mkdtemp()
    tiles = {}
    for i, (key, label, shapes) in enumerate(ICONS, 1):
        p = os.path.join(tmp, f"{i}.svg"); open(p, "w").write(svg(key, shapes))
        for s in (38, 128):
            q = os.path.join(tmp, f"{i}_{s}.png")
            subprocess.run(["rsvg-convert", "-w", str(s), "-h", str(s), p, "-o", q], check=True)
            tiles[(i, s)] = Image.open(q).convert("RGBA")
    W = 6 * 140 + 20; H = 20 + 48 + 20 + 140
    sheet = Image.new("RGBA", (W, H), "#17161A")
    for i in range(1, 7):
        x = 20 + (i - 1) * 140
        sheet.alpha_composite(tiles[(i, 38)], (x + 45, 20))
        sheet.alpha_composite(tiles[(i, 128)], (x, 88))
    sheet.save(path)

def bez(p0, p1, p2, n=24):
    return [((1-t)**2*p0[0]+2*(1-t)*t*p1[0]+t*t*p2[0], (1-t)**2*p0[1]+2*(1-t)*t*p1[1]+t*t*p2[1])
            for t in [i/n for i in range(n+1)]]

def app_icon(size=1024):
    """Ficha grafito con una N tildada (Ñ) dibujada con trazos; naranja sobre carbon."""
    k = size/64.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size-1, size-1], radius=int(14*k), fill="#17161A")
    d.rounded_rectangle([int(2.5*k), int(2.5*k), size-1-int(2.5*k), size-1-int(2.5*k)], radius=int(12*k),
                        outline="#FF8A3D", width=int(1.6*k))
    w = int(6.2*k); col = "#FF8A3D"
    def stroke(pts):
        P = [(x*k, y*k) for x, y in pts]
        d.line(P, fill=col, width=w, joint="curve")
        for x, y in (P[0], P[-1]):
            d.ellipse([x-w/2, y-w/2, x+w/2, y+w/2], fill=col)
    stroke([(19, 50), (19, 25), (45, 50), (45, 25)])
    d.polygon([(19*k, 25*k), (19*k, 50*k)], fill=col)
    tilde = bez((19, 17), (26, 8), (32, 14), 20) + bez((32, 14), (38, 20), (45, 11), 20)[1:]
    stroke(tilde)
    return img

def main():
    icd = os.path.join(APP, "Assets", "Icons")
    os.makedirs(icd, exist_ok=True)
    for i, (key, label, shapes) in enumerate(ICONS, 1):
        open(os.path.join(icd, f"exp{i}-{key}.svg"), "w").write(svg(key, shapes))
    open(os.path.join(APP, "Styles", "ExpansionIcons.axaml"), "w").write(xaml())
    import shutil
    if shutil.which("rsvg-convert"):
        os.makedirs(os.path.join(ROOT, "docs", "assets"), exist_ok=True)
        contact_sheet(os.path.join(ROOT, "docs", "assets", "expansiones-contacto.png"))
    big = app_icon(1024)
    big.resize((512, 512), Image.LANCZOS).save(os.path.join(APP, "Assets", "icon.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.save(os.path.join(APP, "Assets", "icon.ico"), format="ICO", sizes=[(s, s) for s in sizes])
    big.resize((512, 512), Image.LANCZOS).save(os.path.join(APP, "Assets", "icon.icns"), format="ICNS")

if __name__ == "__main__":
    main()
