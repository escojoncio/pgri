#!/usr/bin/env python3
"""Genera el icono de la app (icon.ico, icon.icns, icon.png). Los iconos de expansion son PNG
aportados (Assets/Icons/exp*.png), ya no se generan.
Uso: python3 -I tools/gen-assets/gen_assets.py   (desde la raiz del repo; requiere Pillow)."""
import os
from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
APP = os.path.join(ROOT, "src", "FFXIVSpanishPatcher.App")

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
    import shutil
    big = app_icon(1024)
    big.resize((512, 512), Image.LANCZOS).save(os.path.join(APP, "Assets", "icon.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.save(os.path.join(APP, "Assets", "icon.ico"), format="ICO", sizes=[(s, s) for s in sizes])
    big.resize((512, 512), Image.LANCZOS).save(os.path.join(APP, "Assets", "icon.icns"), format="ICNS")

if __name__ == "__main__":
    main()
