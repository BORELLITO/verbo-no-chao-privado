"""VNC cover (qualquer episodio, runner only): storm -> light, brand logo, title. Prints JPEGs as base64 (private logs)."""
import base64, io, subprocess, sys, urllib.request
from pathlib import Path
import imageio_ffmpeg, numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FF = imageio_ffmpeg.get_ffmpeg_exe()
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"}
FONT = "assets/fonts/AtkinsonHyperlegibleNext-Bold.ttf"
import json, os
CFG = json.loads(Path(f"episodes/{os.environ.get('VNC_EPISODE', 'E01')}.json").read_text(encoding="utf8"))
TOP, BOT = tuple(CFG["cover"]["top"]), tuple(CFG["cover"]["bottom"])   # tristeza -> luz
TITLE, REF = CFG["title_lines"], CFG["reference"]
KICKER = f"EPISÓDIO {CFG['number']:02d}"


def _selection_clip(cid):
    try:
        sel = json.loads(Path(CFG["selection"]).read_text(encoding="utf8"))
        return next((c for c in sel.get("clips", []) if str(c.get("id")) == str(cid)), None)
    except Exception:  # noqa
        return None


def _urls(cid):
    """URLs candidatas do clipe do quadro da capa, conforme a fonte registrada na selecao do episodio (Coverr so p/ legado do E01)."""
    c = _selection_clip(cid)
    src = (c or {}).get("source", "coverr")
    if src == "mixkit":
        import re
        page = urllib.request.urlopen(urllib.request.Request(c["page"], headers=UA), timeout=60).read().decode("utf8", "ignore")
        us = sorted(set(re.findall(r'https://assets\.mixkit\.co/[^"\'\s<>]+?\.mp4', page)), key=lambda u: -int(re.search(r"-(\d{3,4})\.mp4", u)[1]) if re.search(r"-(\d{3,4})\.mp4", u) else 0)
        return us
    if src == "pexels":
        return [f"https://www.pexels.com/download/video/{cid}/"]
    return [f"https://cdn.coverr.co/videos/{cid}/{q}.mp4" for q in ("1080p", "720p")]


def frame(slug, t):
    data = None
    for u in _urls(slug):
        try:
            data = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=180).read()
            if len(data) > 100_000: break
        except Exception: pass
    Path("/tmp/c.mp4").write_bytes(data)
    png = subprocess.run([FF, "-v", "error", "-ss", str(t), "-i", "/tmp/c.mp4", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    return Image.open(io.BytesIO(png)).convert("RGB")


def fill(img, W, H, cx=0.5):
    r = max(W / img.width, H / img.height); im = img.resize((int(img.width * r + .5), int(img.height * r + .5)), Image.LANCZOS)
    x, y = int(min(max(cx * im.width - W / 2, 0), im.width - W)), (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))


METRICS = {}
GOLD = (252, 196, 72, 255); WHITE = (244, 243, 240, 255)


def _pad(im):
    n = int(round(im.width * 0.10)); c = Image.new("RGBA", (im.width + 2 * n, im.height + 2 * n), (0, 0, 0, 0)); c.alpha_composite(im, (n, n)); return c


def logo_layer(size):
    """Logo em alta qualidade: alfa pre-multiplicado + Lanczos + margem (sem franja, sem corte)."""
    src = _pad(Image.open("assets/vnc_logo.png").convert("RGBA"))
    lg = src.convert("RGBa").resize((size, size), Image.LANCZOS).convert("RGBA")
    glow = Image.new("RGBA", lg.size, (255, 255, 255, 0)); glow.putalpha(lg.split()[3].filter(ImageFilter.GaussianBlur(size * 0.012)).point(lambda v: int(v * .45)))
    return Image.alpha_composite(glow, lg)


def tracked(d, text, font, cx, y, fill, track):
    ws = [d.textlength(c, font=font) for c in text]; tot = sum(ws) + track * (len(text) - 1); x = cx - tot / 2
    for c, w in zip(text, ws): d.text((x, y), c, font=font, fill=fill); x += w + track
    return tot


def build(W, H, L):
    a, b = fill(frame(*TOP), W, H), fill(frame(*BOT), W, H, 0.56)
    yy = np.linspace(0, 1, H)[:, None]; s = np.clip((yy - L["t0"]) / L["tw"], 0, 1); s = s * s * (3 - 2 * s)
    arr = np.asarray(a, dtype=float) * (1 - s[..., None]) + np.asarray(b, dtype=float) * s[..., None]
    arr = arr * (1 - 0.30 * (1 - s[..., None]))
    arr = arr * (1 - 0.34 * np.exp(-((yy - L["scrim"]) / 0.17) ** 2)[..., None])      # base escura suave atras do titulo
    xx = np.linspace(-1, 1, W)[None, :]; vig = 1 - 0.30 * np.clip((xx ** 2) * 0.9 + ((yy - 0.5) * 2) ** 2 * 0.35 - 0.25, 0, 1)
    arr = arr * vig[..., None]
    img = Image.fromarray(arr.clip(0, 255).astype("uint8")).convert("RGBA")
    # brilho suave atras do logo (leitura do azul-marinho)
    lw = L["logo"]; cy = L["logo_y"] + lw // 2
    gy, gx = np.mgrid[0:H, 0:W]; r2 = ((gx - W / 2) / (lw * 0.78)) ** 2 + ((gy - cy) / (lw * 0.70)) ** 2
    ga = (np.exp(-r2 * 1.6) * 0.34 * 255).astype("uint8")
    glow = Image.new("RGBA", (W, H), (206, 212, 238, 0)); glow.putalpha(Image.fromarray(ga)); img = Image.alpha_composite(img, glow)
    img.alpha_composite(logo_layer(lw), ((W - lw) // 2, L["logo_y"]))
    base_rgba = img.copy()
    # texto
    ts = L["ts"]; ft = ImageFont.truetype(FONT, ts); fk = ImageFont.truetype(FONT, int(ts * 0.27)); fr = ImageFont.truetype(FONT, int(ts * 0.40))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); mn = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ds, dm = ImageDraw.Draw(sh), ImageDraw.Draw(mn)
    ky = L["ky"]; kt = KICKER; kw = tracked(dm, kt, fk, W / 2, ky, GOLD, ts * 0.07); tracked(ds, kt, fk, W / 2, ky + 3, (0, 0, 0, 200), ts * 0.07)
    lh = int(ts * 1.12); y = L["ty"]; hh = int(fk.size * 0.62)
    for x0, x1 in ((W / 2 - kw / 2 - ts * 0.9, W / 2 - kw / 2 - ts * 0.25), (W / 2 + kw / 2 + ts * 0.25, W / 2 + kw / 2 + ts * 0.9)):
        dm.line([(x0, ky + hh + 2), (x1, ky + hh + 2)], fill=GOLD, width=max(2, int(ts * 0.025)))
    for i, ln in enumerate(TITLE):
        w = ds.textlength(ln, font=ft); x = (W - w) / 2; col = GOLD if i == len(TITLE) - 1 else WHITE
        ds.text((x, y + ts * 0.05), ln, font=ft, fill=(0, 0, 0, 205)); dm.text((x, y), ln, font=ft, fill=col); y += lh
    w = ds.textlength(REF, font=fr); ry = y + ts * 0.10
    ds.text(((W - w) / 2, ry + 2), REF, font=fr, fill=(0, 0, 0, 190)); dm.text(((W - w) / 2, ry), REF, font=fr, fill=(236, 232, 250, 240))
    ys = L["ty"] - 6; ye = int(ry + fr.size * 1.25)
    from agents.vnc_cover_gate import rel_lum
    METRICS.update({"y_top": ky, "y_bottom": ye, "widths": [ds.textlength(l, font=ft) for l in TITLE] + [kw, w], "kicker": KICKER, "lines": len(TITLE),
                    "band_lum": rel_lum(np.asarray(base_rgba.convert("RGB"), dtype=float)[ys:ye, int(W * 0.08):int(W * 0.92)]), "cover_ids": [str(TOP[0]), str(BOT[0])]})
    img = Image.alpha_composite(img, Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(ts * 0.07)), mn))
    out = img.convert("RGB")
    g = np.random.default_rng(7).normal(0, 2.0, (H, W, 1)); return Image.fromarray((np.asarray(out, dtype=float) + g).clip(0, 255).astype("uint8"))


LAYOUT = {
    # vertical 1080x1920: tudo dentro da area segura da grade do Instagram (y 300-1620)
    "vertical": (1080, 1920, dict(logo=440, logo_y=300, ky=880, ty=950, ts=124, t0=0.40, tw=0.34, scrim=0.57)),
    "wide": (1280, 720, dict(logo=230, logo_y=14, ky=232, ty=272, ts=80, t0=0.30, tw=0.42, scrim=0.58)),
}
FORMATS = CFG.get("cover_formats", ["vertical"])   # decisao do dono (2026-11-21): so capa vertical (Shorts/TikTok/Instagram); "wide" so se pedido
for name, (W, H, L) in LAYOUT.items():
    if name not in FORMATS: continue
    im = build(W, H, L)
    if name == "vertical":   # PORTAO NUMERICO: capa reprovada nao e impressa (nao entregar)
        from agents import vnc_cover_gate as CG
        errs = CG.check(CFG, im, METRICS, strict=CFG["number"] >= 3)
        for e in errs: print("VNC_COVER_GATE_FAIL", e)
        print("VNC_COVER_GATE", "OK" if not errs else f"BLOQUEADA {len(errs)}", json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in METRICS.items() if k != "widths"}, ensure_ascii=False))
        if errs: sys.exit(9)
    b = io.BytesIO(); im.save(b, "JPEG", quality=95, subsampling=0); sb = base64.b64encode(b.getvalue()).decode()
    print("VNC_COVER", name, len(sb))
    for n in range(0, len(sb), 1800): print("VNC_COVERB64", name, n // 1800, sb[n:n + 1800])
print("VNC_COVER_END")
