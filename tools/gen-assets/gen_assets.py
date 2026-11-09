#!/usr/bin/env python3
"""Genera los iconos propios del parcheador (originales, sin assets de terceros):
 - 6 iconos de expansion (SVG + ResourceDictionary Avalonia con DrawingImage),
 - icono de la app (icon.ico, icon.icns, icon.png).
Uso: python3 -I tools/gen-assets/gen_assets.py   (desde la raiz del repo; requiere Pillow)."""
import math, os
from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
APP = os.path.join(ROOT, "src", "FFXIVSpanishPatcher.App")
INK = "#14110F"
TILE = "M10,2 H54 Q62,2 62,10 V54 Q62,62 54,62 H10 Q2,62 2,54 V10 Q2,2 10,2 Z"

# (path, fill|None, stroke|None, width)
def S(d, fill, w=1.8, stroke=INK): return (d, fill, stroke, w)
def L(d, stroke=INK, w=1.8): return (d, None, stroke, w)

ICONS = [
 ("meteorito", "Meteorito", [
  S(TILE, "#F2C27B", 1.8),
  S("M6,8 Q26,12 38,28 L30,40 Q20,26 6,8 Z", "#E8552B"),
  S("M12,12 Q28,17 36,30 L32,36 Q24,26 12,12 Z", "#FFC857", 1.2),
  S("M34,26 Q44,18 52,26 Q58,34 52,46 Q44,56 34,50 Q26,44 28,34 Q29,29 34,26 Z", "#7A6A5E"),
  S("M45,30 Q53,35 50,45 Q46,52 38,50 Q47,43 45,30 Z", "#54463D", 1.2),
  S("M35,36 a3,3 0 1,0 6,0 a3,3 0 1,0 -6,0 Z", "#54463D", 1.2),
  S("M44,42 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0 Z", "#54463D", 1.0),
 ]),
 ("dragon-blanco", "Dragón blanco", [
  S(TILE, "#A9CDEB", 1.8),
  S("M26,26 L19,9 L33,22 Z", "#D3DCE7"),
  S("M34,24 L39,9 L41,26 Z", "#D3DCE7"),
  S("M11,47 Q13,34 24,28 Q32,23 40,25 Q46,28 50,30 L59,30 L53,38 L57,43 L47,44 Q41,53 28,53 Q16,55 11,47 Z", "#F7F9FB"),
  S("M20,46 Q30,52 42,46 Q34,49 24,44 Z", "#C5D0DE", 1.0),
  S("M38,34 L45,32.5 L43,37.5 Z", "#2F6FD0", 1.2),
  L("M30,44 Q40,46.5 47,44", w=1.5),
  S("M48,38 L50,42.5 L52.5,38 Z", "#FFFFFF", 1.0),
  S("M52,32.5 a1.3,1.3 0 1,0 2.6,0 a1.3,1.3 0 1,0 -2.6,0 Z", INK, 0.5),
 ]),
 ("katana", "Katana ensangrentada", [
  S(TILE, "#6E8096", 1.8),
  S("M19,41 L57,7 L27,47 Z", "#E9EEF3"),
  L("M22,42 L55,9", stroke="#9AA8B6", w=1.2),
  S("M41,24 L47,16 L48,20 L44,27 Z", "#B3121F", 1.0),
  S("M22.2,49.4 L17.8,44.6 L5.8,55.6 L10.2,60.4 Z", "#2B2F4A"),
  L("M14,47 L18,52 M10,51 L14,56", stroke="#8C93C8", w=1.0),
  S("M16,45 a6,6 0 1,0 12,0 a6,6 0 1,0 -12,0 Z", "#D1A94B"),
  S("M34,51 Q30,57 34,60 Q38,57 34,51 Z", "#B3121F", 1.2),
  S("M45,50 Q42.5,54 45,56 Q47.5,54 45,50 Z", "#B3121F", 1.0),
 ]),
 ("luz-y-sombra", "Luz y sombra", [
  S(TILE, "#F6E7B2", 1.8),
  S("M10,2 H30 L26,14 L36,22 L28,32 L38,42 L30,52 L34,62 H10 Q2,62 2,54 V10 Q2,2 10,2 Z", "#2B2350", 1.8),
  S("M32,10 L35.5,27 L52,20 L39,31 L54,40 L37,38 L32,56 L28.5,38 L11,43 L25,32 L13,19 L29,27 Z", "#FFFFFF", 1.6),
  S("M26,32 a6,6 0 1,0 12,0 a6,6 0 1,0 -12,0 Z", "#8B7AE6", 1.4),
 ]),
 ("pluma-azul", "Pluma azul", [
  S(TILE, "#CFE5F6", 1.8),
  S("M11,54 Q7,30 24,16 Q40,3 57,5 Q59,22 46,37 Q32,51 11,54 Z", "#2F7BE0"),
  S("M11,54 Q30,34 57,5 Q59,22 46,37 Q32,51 11,54 Z", "#1F58B5", 1.2),
  L("M8,57 Q30,34 55,8", w=2.2),
  L("M24,42 L17,35 M31,34 L23,26 M38,26 L31,18 M33,43 L40,45 M42,33 L49,34", w=1.3),
 ]),
 ("ruina-piedra", "Ruina de piedra", [
  S(TILE, "#BBD7B2", 1.8),
  S("M3,52 Q12,48 24,52 T46,50 T61,52 V54 Q61,61 54,61 H10 Q3,61 3,54 Z", "#7E9E62", 1.4),
  S("M10,52 V20 H24 V52 Z", "#DAD4C6"),
  S("M20,20 H24 V52 H20 Z", "#B9B1A1", 1.0),
  S("M8,15 H26 V20 H8 Z", "#EAE5D9"),
  L("M14,22 V50", stroke="#A79F8F", w=1.0),
  S("M38,52 V33 L42,28 L46,34 L50,30 L53,34 V52 Z", "#DAD4C6"),
  S("M49,34 L53,34 V52 H49 Z", "#B9B1A1", 1.0),
  S("M27,52 L29,46 L38,46 L40,52 Z", "#BDB5A4", 1.4),
  S("M22,31 Q26,26 29,30 Q25,35 22,31 Z", "#4E7A3A", 1.0),
 ]),
]

def svg(name, shapes):
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" '
           'stroke-linejoin="round" stroke-linecap="round">']
    for d, f, s, w in shapes:
        out.append(f'  <path d="{d}" fill="{f or "none"}"' + (f' stroke="{s}" stroke-width="{w}"' if s else '') + '/>')
    out.append('</svg>')
    return "\n".join(out) + "\n"

def xaml():
    o = ['<ResourceDictionary xmlns="https://github.com/avaloniaui"',
         '                    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">',
         '  <!-- Generado por tools/gen-assets/gen_assets.py. No editar a mano. -->']
    for key, label, shapes in ICONS:
        k = "".join(p.capitalize() for p in key.split("-"))
        o.append(f'  <DrawingImage x:Key="Exp{k}">')
        o.append('    <DrawingGroup>')
        o.append('      <GeometryDrawing Brush="Transparent" Geometry="M0,0 L64,0 L64,64 L0,64 Z"/>')
        for d, f, s, w in shapes:
            attrs = f'Geometry="{d}"' + (f' Brush="{f}"' if f else '')
            if s:
                o.append(f'      <GeometryDrawing {attrs}>')
                o.append(f'        <GeometryDrawing.Pen><Pen Brush="{s}" Thickness="{w}" LineJoin="Round" LineCap="Round"/></GeometryDrawing.Pen>')
                o.append('      </GeometryDrawing>')
            else:
                o.append(f'      <GeometryDrawing {attrs}/>')
        o.append('    </DrawingGroup>')
        o.append('  </DrawingImage>')
    o.append('</ResourceDictionary>')
    return "\n".join(o) + "\n"

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
    big = app_icon(1024)
    big.resize((512, 512), Image.LANCZOS).save(os.path.join(APP, "Assets", "icon.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.save(os.path.join(APP, "Assets", "icon.ico"), format="ICO", sizes=[(s, s) for s in sizes])
    big.resize((512, 512), Image.LANCZOS).save(os.path.join(APP, "Assets", "icon.icns"), format="ICNS")

if __name__ == "__main__":
    main()
