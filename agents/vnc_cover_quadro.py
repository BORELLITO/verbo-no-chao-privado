"""Capa do QUADRO 'Fora do Contexto' (identidade propria; o padrao de episodio em vnc_cover.py nao muda).
Conceito: um RECORTE (marcas de corte laranja) mostra so a frase famosa; fora do recorte a imagem fica escura e desfocada = o resto do contexto.
Ativado por episodes/EXX.json: "cover_style": "quadro", "cover_quadro": {"kicker", "big": [..], "tagline"}. Funcao pura, testavel sem rede."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from agents import vnc_cover_gate as CG

W, H = 1080, 1920
ORANGE = (255, 179, 102, 255); WHITE = (246, 244, 240, 255); SOFT = (236, 232, 250, 235)
FRAME = (110, 800, 970, 1340)          # recorte: x0, y0, x1, y1 (tudo dentro da area segura y 300-1620)
FONT = "assets/fonts/AtkinsonHyperlegibleNext-Bold.ttf"


def _fill(img):
    r = max(W / img.width, H / img.height); im = img.resize((int(img.width * r + .5), int(img.height * r + .5)), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))


def _tracked(d, text, font, cx, y, fill, track):
    ws = [d.textlength(c, font=font) for c in text]; tot = sum(ws) + track * (len(text) - 1); x = cx - tot / 2
    for c, w in zip(text, ws): d.text((x, y), c, font=font, fill=fill); x += w + track
    return tot


def _fit_big(big, size=205, limite=0.88):
    """Fonte do titulo grande: 205 px; encolhe so se a linha mais larga passar de 88% da capa (E06/E07 seguem em 205)."""
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    while size > 120 and max(d.textlength(ln, font=ImageFont.truetype(FONT, size)) for ln in big) > W * limite: size -= 5
    return ImageFont.truetype(FONT, size)


def build(bg, logo, kicker, big, tagline, ref):
    """bg: PIL RGB (qualquer tamanho), logo: PIL RGBA ja no tamanho final. Retorna (imagem RGB 1080x1920, metricas)."""
    base = _fill(bg.convert("RGB")); x0, y0, x1, y1 = FRAME
    a = np.asarray(base, dtype=float)
    lum = a.mean(axis=2, keepdims=True); a = a * 0.55 + lum * 0.45                    # dessatura de leve: unifica o visual do quadro
    out_img = Image.fromarray(a.clip(0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(7))
    out = np.asarray(out_img, dtype=float) * 0.36                                      # FORA do recorte: escuro e desfocado
    inside = (a * 0.62)                                                                # DENTRO: nitido, so escurecido para o texto
    m = np.zeros((H, W, 1)); m[y0:y1, x0:x1] = 1
    arr = out * (1 - m) + inside * m
    yy = np.linspace(0, 1, H)[:, None]; xx = np.linspace(-1, 1, W)[None, :]
    arr = arr * (1 - 0.30 * np.clip(xx ** 2 * 0.9 + ((yy - 0.5) * 2) ** 2 * 0.35 - 0.25, 0, 1))[..., None]
    img = Image.fromarray(arr.clip(0, 255).astype("uint8")).convert("RGBA")
    lw = logo.width; cy = 300 + lw // 2   # brilho suave atras do logo (leitura do azul-marinho), como na capa padrao
    gy, gx = np.mgrid[0:H, 0:W]; ga = (np.exp(-(((gx - W / 2) / (lw * 0.78)) ** 2 + ((gy - cy) / (lw * 0.70)) ** 2) * 1.6) * 0.34 * 255).astype("uint8")
    glow = Image.new("RGBA", (W, H), (206, 212, 238, 0)); glow.putalpha(Image.fromarray(ga)); img = Image.alpha_composite(img, glow)
    img.alpha_composite(logo, ((W - lw) // 2, 300))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); mn = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ds, dm = ImageDraw.Draw(sh), ImageDraw.Draw(mn)
    fk = ImageFont.truetype(FONT, 40); fb = _fit_big(big); ft = ImageFont.truetype(FONT, 62); fr = ImageFont.truetype(FONT, 46)
    ky = 735; _tracked(ds, kicker, fk, W / 2, ky + 3, (0, 0, 0, 210), 7); kw = _tracked(dm, kicker, fk, W / 2, ky, ORANGE, 7)
    # marcas de corte (cantos) do recorte
    L, T = 70, 9
    for (cx, cy, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        dm.line([(cx, cy), (cx + sx * L, cy)], fill=ORANGE, width=T); dm.line([(cx, cy), (cx, cy + sy * L)], fill=ORANGE, width=T)
    # frase famosa dentro do recorte
    lh = 200; ty = y0 + (y1 - y0 - lh * len(big)) / 2 - 12; widths = []
    for i, ln in enumerate(big):
        w = ds.textlength(ln, font=fb); widths.append(w); x = (W - w) / 2
        ds.text((x, ty + 6), ln, font=fb, fill=(0, 0, 0, 215)); dm.text((x, ty), ln, font=fb, fill=ORANGE if i == len(big) - 1 else WHITE); ty += lh
    w = ds.textlength(tagline, font=ft); ty2 = y1 + 62
    ds.text(((W - w) / 2, ty2 + 3), tagline, font=ft, fill=(0, 0, 0, 200)); dm.text(((W - w) / 2, ty2), tagline, font=ft, fill=ORANGE)
    w2 = ds.textlength(ref, font=fr); ry = ty2 + 96
    ds.text(((W - w2) / 2, ry + 2), ref, font=fr, fill=(0, 0, 0, 190)); dm.text(((W - w2) / 2, ry), ref, font=fr, fill=SOFT)
    base_rgb = np.asarray(img.convert("RGB"), dtype=float)
    img = Image.alpha_composite(img, Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5)), mn))
    met = {"y_top": ky, "y_bottom": int(ry + fr.size * 1.25), "frame_lum": CG.rel_lum(base_rgb[y0:y1, x0:x1]), "frame_sharp": CG.sharp(base_rgb[y0:y1, x0:x1]),
           "widths": widths + [w, w2, kw], "lines": len(big)}
    o = img.convert("RGB"); g = np.random.default_rng(7).normal(0, 2.0, (H, W, 1))
    return Image.fromarray((np.asarray(o, dtype=float) + g).clip(0, 255).astype("uint8")), met


def check(img, met):
    errs = []
    if img.size != (W, H): errs.append(f"formato {img.size} (exige {W}x{H})")
    if met["y_top"] < CG.SAFE_Y[0] or met["y_bottom"] > CG.SAFE_Y[1]: errs.append(f"texto fora da area segura ({met['y_top']}-{met['y_bottom']})")
    if max(met["widths"]) > W * 0.90: errs.append("texto largo demais para a capa")
    cw, co = CG.contrast(CG.WHITE_LUM, met["frame_lum"]), CG.contrast(CG.rel_lum(np.array(ORANGE[:3])), met["frame_lum"])
    if cw < CG.MIN_CONTRAST_WHITE or co < CG.MIN_CONTRAST_GOLD: errs.append(f"contraste baixo no recorte (branco {cw:.1f}, laranja {co:.1f})")
    if met["frame_sharp"] < CG.MIN_SHARP: errs.append(f"recorte sem nitidez ({met['frame_sharp']:.1f})")
    return errs


def load_logo(size=380):
    """Mesmo tratamento do logo padrao (alfa pre-multiplicado + Lanczos + margem + brilho leve)."""
    s = Image.open("assets/vnc_logo.png").convert("RGBA"); n = int(round(s.width * 0.10))
    c = Image.new("RGBA", (s.width + 2 * n, s.height + 2 * n), (0, 0, 0, 0)); c.alpha_composite(s, (n, n))
    lg = c.convert("RGBa").resize((size, size), Image.LANCZOS).convert("RGBA")
    glow = Image.new("RGBA", lg.size, (255, 255, 255, 0)); glow.putalpha(lg.split()[3].filter(ImageFilter.GaussianBlur(size * 0.012)).point(lambda v: int(v * .45)))
    return Image.alpha_composite(glow, lg)
