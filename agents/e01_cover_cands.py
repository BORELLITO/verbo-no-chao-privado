import base64, io, subprocess, urllib.request
from pathlib import Path
import imageio_ffmpeg
from PIL import Image
FF = imageio_ffmpeg.get_ffmpeg_exe(); UA = {"User-Agent": "Mozilla/5.0"}
cands = {"coverr-sunrise-on-the-beach-9704": [3, 6, 10, 13, 16, 19, 22, 25], "coverr-mountains-in-lake-tekapo-new-zealand-5006": [2, 6, 10, 14], "coverr-mountain-top-trail-9791": [3, 10, 20, 30], "coverr-beautiful-valley-at-golden-hour-3055": [3, 8, 12]}
tiles = []
for slug, ts in cands.items():
    try: Path("/tmp/c.mp4").write_bytes(urllib.request.urlopen(urllib.request.Request(f"https://cdn.coverr.co/videos/{slug}/720p.mp4", headers=UA), timeout=180).read())
    except Exception as e: print("fail", slug, e); continue
    for t in ts:
        png = subprocess.run([FF, "-v", "error", "-ss", str(t), "-i", "/tmp/c.mp4", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
        if png: tiles.append((slug[7:26], t, Image.open(io.BytesIO(png)).convert("RGB").resize((320, 180))))
from PIL import ImageDraw
sheet = Image.new("RGB", (5 * 320, ((len(tiles) + 4) // 5) * 200), (20, 20, 20)); d = ImageDraw.Draw(sheet)
for i, (n, t, im) in enumerate(tiles):
    x, y = (i % 5) * 320, (i // 5) * 200; sheet.paste(im, (x, y)); d.text((x + 2, y + 182), f"{i} {n} t={t}", fill=(255, 255, 0))
b = io.BytesIO(); sheet.save(b, "JPEG", quality=80); sb = base64.b64encode(b.getvalue()).decode()
for n in range(0, len(sb), 1800): print("VNC_CAND", n // 1800, sb[n:n + 1800])
