"""Sondagem SOMENTE-LEITURA de camadas de luz filmadas (light leak, flare, bokeh, poeira, nascer do sol) para o final de cinema.
Fontes: apenas Mixkit e Wikimedia (CC0), com a mesma trava de direitos do motor. Nao grava no repositorio, nao registra clipes, nao entra em episodio.
Saida (artefato): /tmp/overlay_out/{report.json, sheet_<consulta>.jpg, previews/*.mp4}"""
import json, os, sys, time, subprocess
from pathlib import Path
from agents import vnc_sources, vnc_curate

OUT = Path("/tmp/overlay_out"); OUT.mkdir(parents=True, exist_ok=True); (OUT / "previews").mkdir(exist_ok=True)


def frame(ffmpeg, mp4, png, t=1.0):
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", str(t), "-i", str(mp4), "-frames:v", "1", "-vf", "scale=240:-2", str(png)], check=False)


def main():
    import imageio_ffmpeg
    from PIL import Image, ImageDraw
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cfg = json.load(open("run/overlays.json")); per = int(cfg.get("per_query", 8))
    ctx = {"get": vnc_curate.get, "cache": {}, "env": os.environ, "ua": vnc_curate.UA, "sleep": time.sleep, "budget": {}}
    report, seen = [], set()
    for q in cfg["queries"]:
        ents = [e for s in ("mixkit", "wikimedia") for e in vnc_sources.discover(s, q, ctx)]
        rows = []
        for e in ents:
            k = (e["source"], e["id"])
            if k in seen or len(rows) >= per:
                continue
            seen.add(k)
            ok, ev, hd = vnc_sources.rights(e, ctx)
            if not ok:
                print("VNC_OVERLAY_SKIP", e["source"], e["id"], ev); continue
            f = OUT / "previews" / f"{e['source']}-{e['id']}.mp4"
            try:
                f.write_bytes(vnc_curate.get(e["preview"], True, limit=12_000_000))
            except Exception as x:  # noqa
                print("VNC_OVERLAY_WARN preview", e["id"], repr(x)[:50]); continue
            png = OUT / "previews" / f"{e['source']}-{e['id']}.png"; frame(ff, f, png)
            rows.append(dict(source=e["source"], id=e["id"], title=e["title"], page=e["page"], license=e["license"], rights=ev, hd=hd, query=q, thumb=png.name, preview=f.name))
            time.sleep(0.4)
        report += rows
        if rows:
            w = 240; sh = Image.new("RGB", (w * min(4, len(rows)), 440 * ((len(rows) + 3) // 4)), (20, 20, 20)); d = ImageDraw.Draw(sh)
            for i, r in enumerate(rows):
                try:
                    im = Image.open(OUT / "previews" / r["thumb"]).convert("RGB"); im.thumbnail((w, 400)); sh.paste(im, ((i % 4) * w, (i // 4) * 440)); d.text(((i % 4) * w + 4, (i // 4) * 440 + 405), f"{r['id']} {r['title'][:34]}", fill=(255, 255, 255))
                except Exception:  # noqa
                    pass
            sh.save(OUT / f"sheet_{q.replace(' ', '-')}.jpg", quality=85)
    json.dump(report, open(OUT / "report.json", "w"), ensure_ascii=False, indent=1)
    print("VNC_OVERLAY_OK", len(report), "clipes com licenca confirmada")


if __name__ == "__main__":
    sys.exit(main())
