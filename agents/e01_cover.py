"""E01 cover (runner only): storm -> light, brand logo, title. Prints JPEGs as base64 (private logs)."""
import base64, io, subprocess, sys, urllib.request
from pathlib import Path
import imageio_ffmpeg, numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FF = imageio_ffmpeg.get_ffmpeg_exe()
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"}
FONT = "assets/fonts/AtkinsonHyperlegibleNext-Bold.ttf"
TOP = ("coverr-raindrops-on-the-window-7102", 3.0)   # tristeza / pergunta sem resposta
BOT = ("coverr-mountain-top-trail-9791", 10.0)      # luz / esperança
TITLE = ["Quando você", "pergunta e", "nada muda"]
REF = "Habacuque 1:2–4"


def frame(slug, t):
    data = None
    for q in ("1080p", "720p"):
        try:
            data = urllib.request.urlopen(urllib.request.Request(f"https://cdn.coverr.co/videos/{slug}/{q}.mp4", headers=UA), timeout=180).read(); break
        except Exception: pass
    Path("/tmp/c.mp4").write_bytes(data)
    png = subprocess.run([FF, "-v", "error", "-ss", str(t), "-i", "/tmp/c.mp4", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    return Image.open(io.BytesIO(png)).convert("RGB")


def fill(img, W, H, cx=0.5):
    r = max(W / img.width, H / img.height); im = img.resize((int(img.width * r + .5), int(img.height * r + .5)), Image.LANCZOS)
    x, y = int(min(max(cx * im.width - W / 2, 0), im.width - W)), (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))


def text_block(W, H, lines, size, y0, accent_last=True):
    f = ImageFont.truetype(FONT, size)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); main = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ds, dm = ImageDraw.Draw(shadow), ImageDraw.Draw(main); y = y0; lh = int(size * 1.12)
    for i, ln in enumerate(lines):
        w = ds.textlength(ln, font=f); x = (W - w) / 2
        col = (242, 176, 196, 255) if (accent_last and i == len(lines) - 1) else (242, 241, 238, 255)
        ds.text((x, y + size * 0.05), ln, font=f, fill=(0, 0, 0, 190)); dm.text((x, y), ln, font=f, fill=col); y += lh
    return Image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(size * 0.08)), main), y


def build(W, H, logo_w, title_size, vertical):
    a, b = fill(frame(*TOP), W, H), fill(frame(*BOT), W, H, 0.56)
    yy = np.linspace(0, 1, H)[:, None]; s = np.clip((yy - 0.36) / 0.34, 0, 1); s = s * s * (3 - 2 * s)
    arr = np.asarray(a, dtype=float) * (1 - s[..., None]) + np.asarray(b, dtype=float) * s[..., None]
    arr = arr * (1 - 0.30 * (1 - s[..., None]))  # escurece suavemente a parte da tristeza
    cyy = 0.50 if vertical else 0.55; arr = arr * (1 - 0.28 * np.exp(-((yy - cyy) / 0.16) ** 2)[..., None])  # suaviza atrás do título
    img = Image.fromarray(arr.clip(0, 255).astype('uint8')).convert('RGBA')
    # logo
    lg = Image.open("assets/vnc_logo.png").convert("RGBA").resize((logo_w, logo_w), Image.LANCZOS)
    al = lg.split()[3]; glow = Image.new("RGBA", lg.size, (255, 255, 255, 0)); glow.putalpha(al.filter(ImageFilter.GaussianBlur(logo_w * .014)).point(lambda v: int(v * .55)))
    lgx = Image.alpha_composite(glow, lg)
    ly = int(H * (0.06 if vertical else 0.05))
    img.alpha_composite(lgx, ((W - logo_w) // 2, ly))
    # titulo
    tb, yend = text_block(W, H, TITLE, title_size, int(H * (0.37 if vertical else 0.30)) if vertical else int(H * 0.36))
    img = Image.alpha_composite(img, tb)
    f = ImageFont.truetype(FONT, int(title_size * 0.42)); d = ImageDraw.Draw(img)
    w = d.textlength(REF, font=f); d.text(((W - w) / 2, yend + title_size * 0.12), REF, font=f, fill=(236, 232, 250, 235))
    out = img.convert("RGB")
    g = np.random.default_rng(7).normal(0, 2.2, (H, W, 1)); out = Image.fromarray((np.asarray(out, dtype=float) + g).clip(0, 255).astype("uint8"))
    return out


for name, (W, H, lw, ts, v) in {"vertical": (1080, 1920, 320, 118, True), "wide": (1280, 720, 190, 92, False)}.items():
    im = build(W, H, lw, ts, v); b = io.BytesIO(); im.save(b, "JPEG", quality=95, subsampling=0); sb = base64.b64encode(b.getvalue()).decode()
    print("VNC_COVER", name, len(sb))
    for n in range(0, len(sb), 1800): print("VNC_COVERB64", name, n // 1800, sb[n:n + 1800])
print("VNC_COVER_END")
