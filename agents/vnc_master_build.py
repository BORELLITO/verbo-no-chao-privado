"""VNC master builder (qualquer episodio, config em episodes/<ID>.json). Runs on a GitHub runner only.

Downloads the 12 selected free clips (Pexels, Mixkit, Coverr), crops each to 9:16 around the motion centroid,
cuts them to the scene timings, burns the approved karaoke captions and muxes the existing Johnes Bittar narration
(downloaded from the already generated take; no new voice, no spend). Output is printed as base64 chunks for the
owner's private copy; nothing is uploaded, committed or published."""
import base64, hashlib, io, json, os, re, subprocess, sys, urllib.request
from pathlib import Path
import imageio_ffmpeg, numpy as np
from PIL import Image

from agents.e01_v3_voice_captions import build as build_captions
from agents import vnc_align
from agents import vnc_style as ST

FF = imageio_ffmpeg.get_ffmpeg_exe()
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"}
W, H = 1080, 1920
AUDIO_SHA_PREFIX, AUDIO_SHA_SUFFIX = "35f43519", "b5685"
MAX_BYTES = 150_000_000
WORK = Path("/tmp/master"); WORK.mkdir(exist_ok=True)


def get(url, binary=True, timeout=180):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES: raise RuntimeError("too_large")
    return data if binary else data.decode("utf8", "ignore")


def probe(p):
    e = subprocess.run([FF, "-hide_banner", "-i", str(p)], capture_output=True, text=True).stderr
    d = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", e); v = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", e)
    return {"dur": int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]) if d else 0.0, "w": int(v[1]) if v else 0, "h": int(v[2]) if v else 0}


def fetch_clip(c, dest):
    s, i = c["source"], c["id"]
    if s == "pexels":
        urls = [f"https://www.pexels.com/download/video/{i}/"]
    elif s == "mixkit":
        page = get(c["page"], False)
        urls = sorted(set(re.findall(r'https://assets\.mixkit\.co/[^"\'\s<>]+?\.mp4', page)), key=lambda u: -int(re.search(r"-(\d{3,4})\.mp4", u)[1]) if re.search(r"-(\d{3,4})\.mp4", u) else 0)
    elif s == "coverr":
        urls = [f"https://cdn.coverr.co/videos/{i}/{q}.mp4" for q in ("1080p", "720p", "360p")]
    else:
        raise RuntimeError("unknown_source")
    last = None
    for u in urls:
        try:
            data = get(u)
            if len(data) < 100_000 or b"ftyp" not in data[:64]: raise RuntimeError("not_mp4")
            dest.write_bytes(data)
            return {"url_host": re.match(r"https://([^/]+)/", u)[1], "bytes": len(data)}
        except Exception as e:
            last = repr(e)[:80]
    raise RuntimeError(f"download_failed:{last}")


def motion_center(p, dur):
    frames = []
    for k in range(8):
        t = dur * (k + 0.5) / 8
        png = subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-i", str(p), "-frames:v", "1", "-vf", "scale=160:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
        if png: frames.append(np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=float))
    if len(frames) < 2: return 0.5
    col = sum(np.abs(frames[k + 1] - frames[k]).sum(axis=0) for k in range(len(frames) - 1))
    col = np.convolve(col, np.ones(9) / 9, mode="same")
    if col.sum() <= 0: return 0.5
    return float((col * np.arange(len(col))).sum() / col.sum() / len(col))


MUSIC_PAGE = "https://mixkit.co/free-stock-music/a-new-life/"


def load_cfg(ep):
    return json.loads(Path(f"episodes/{ep}.json").read_text(encoding="utf8"))
TAIL_HOLD, TAIL_BLACK = ST.TAIL_HOLD, ST.TAIL_BLACK
CAP_LEAD_CONTRACT = 0.07  # (timing por contrato/Scribe) # legenda 70 ms antes: checagem independente (Whisper) mostrou destaque ~100 ms atrasado em mediana


def fetch_music(dest, MUSIC_PAGE):
    page = get(MUSIC_PAGE, False)
    m = re.search(r"assets\.mixkit\.co/music/(?:preview/)?mixkit-[a-z0-9-]*?-(\d+)\.mp3", page) or re.search(r"assets\.mixkit\.co/music/(\d+)/\d+\.mp3", page)
    if not m: raise RuntimeError("music_id_not_found")
    mid = m[1]; urls = [f"https://assets.mixkit.co/music/{mid}/{mid}.mp3"]
    pv = re.search(r"https://assets\.mixkit\.co/music/preview/[^\"'\s<>]+?\.mp3", page)
    if pv: urls.append(pv[0])
    last = None
    for u in urls:
        try:
            data = get(u)
            if len(data) < 200_000: raise RuntimeError("too_small")
            dest.write_bytes(data)
            return {"page": MUSIC_PAGE, "asset_url": u, "mixkit_id": mid, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "license": "Mixkit Music Free License (https://mixkit.co/license/#musicFree)", "content_id_checked": False}
        except Exception as e:
            last = repr(e)[:80]
    raise RuntimeError(f"music_download_failed:{last}")


PADF = 0.10  # margem transparente: evita cortar o brilho/borda da arte que encosta na borda do PNG


def _pad(im):
    n = int(round(im.width * PADF)); c = Image.new("RGBA", (im.width + 2 * n, im.height + 2 * n), (0, 0, 0, 0)); c.alpha_composite(im, (n, n)); return c


def _hq(img, size):
    """Redimensiona RGBA com alfa pré-multiplicado (sem franja escura) e Lanczos."""
    return img.convert("RGBa").resize((size, size), Image.LANCZOS).convert("RGBA")


def _logo_dark(src, s):
    from PIL import ImageFilter
    lg = _hq(src, s); glow = Image.new("RGBA", lg.size, (255, 255, 255, 0))
    glow.putalpha(lg.split()[3].filter(ImageFilter.GaussianBlur(0.016 * s)).point(lambda v: int(v * 0.55)))
    return Image.alpha_composite(glow, lg)


def _scale_alpha(im, k):
    r, g, b, a = im.split(); return Image.merge("RGBA", (r, g, b, a.point(lambda v: int(v * k))))


def make_logo_layers(adur, T, t0, outdir):
    """Camada estática (topo) + sequência de quadros (descida/crescimento até o centro), tudo renderizado em alta qualidade."""
    import numpy as _np
    src = _pad(Image.open("assets/vnc_logo.png").convert("RGBA"))
    arr = _np.asarray(src).copy(); dark = arr[..., :3].max(axis=2) < 110; arr[dark, :3] = (236, 232, 250)
    light = Image.fromarray(arr, "RGBA")
    outdir.mkdir(exist_ok=True)
    sp_of = lambda s: int(round(s * (1 + 2 * PADF) / 2)) * 2
    def put(c, im, s, y):
        sp = im.width; c.alpha_composite(im, ((W - sp) // 2, int(round(y - (sp - s) / 2))))
    c0 = Image.new("RGBA", (W, H), (0, 0, 0, 0)); put(c0, _scale_alpha(_logo_dark(src, sp_of(ST.LOGO_TOP_SIZE)), ST.LOGO_TOP_ALPHA), ST.LOGO_TOP_SIZE, ST.LOGO_TOP_Y); c0.save(outdir / "static.png")
    n = int((T - t0) * 30) + 2
    for k in range(n):
        t = t0 + k / 30; p = min(max((t - t0) / ST.LOGO_GROW_DUR, 0), 1); e = p * p * (3 - 2 * p)
        s = int(round((ST.LOGO_TOP_SIZE + (ST.LOGO_END_SIZE - ST.LOGO_TOP_SIZE) * e) / 2)) * 2; y = ST.LOGO_TOP_Y + ((H * ST.LOGO_END_CENTER_Y - s / 2) - ST.LOGO_TOP_Y) * e
        wd = ST.LOGO_TOP_ALPHA * (1 - min(max((t - (adur + ST.LOGO_DARK_FADE_START)) / ST.LOGO_DARK_FADE_DUR, 0), 1)); wl = min(max((t - (adur + ST.LOGO_LIGHT_FADE_START)) / ST.LOGO_LIGHT_FADE_DUR, 0), 1)
        c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if wd > 0: put(c, _scale_alpha(_logo_dark(src, sp_of(s)), wd), s, y)
        if wl > 0: put(c, _scale_alpha(_hq(light, sp_of(s)), wl), s, y)
        c.save(outdir / f"f_{k:04d}.png", compress_level=1)
    return n


def main(ep=None):
    ep = ep or os.environ.get("VNC_EPISODE", "E01"); cfg = load_cfg(ep)
    mode = os.environ.get("VNC_TIMING_OVERRIDE") or cfg["timing"]  # override = autoteste de regressao (so muda o metodo de tempo)
    vfile = Path(f"assets/voice/{ep}.mp3")
    if vfile.exists():
        audio = vfile.read_bytes()
    else:
        audio_link = (os.environ.get("VNC_AUDIO_URL") or os.environ.get("VNC_E01_AUDIO_URL") or Path(cfg["audio_link_file"]).read_text()).strip()
        if not audio_link.startswith("https://elevenlabsusercontent.com/"):
            print("VNC_MASTER_ABORT no_audio_secret"); sys.exit(4)
        audio = get(audio_link)
    sel = json.loads(Path(os.environ["VNC_SELECTION"]).read_text())["clips"]
    report = {"episode": ep, "timing_mode": mode, "self_test": bool(os.environ.get("VNC_TIMING_OVERRIDE")), "scenes": [], "errors": []}
    (WORK / "voice.mp3").write_bytes(audio)
    sha = hashlib.sha256(audio).hexdigest(); report["audio_sha256"] = sha
    ok = sha == cfg["audio_sha256"] if cfg.get("audio_sha256") else (sha.startswith(cfg["audio_sha256_prefix"]) and sha.endswith(cfg["audio_sha256_suffix"]))
    if not ok:
        print("VNC_MASTER_ABORT audio_sha_mismatch", sha); sys.exit(2)
    adur = probe(WORK / "voice.mp3")["dur"]; report["audio_seconds"] = round(adur, 2)
    caps = WORK / "caps"
    if mode == "contract":
        refit = {x["id"][-3:]: x for x in json.loads(Path("contracts/e01_v3_12_scene_refit_v1.json").read_text())["scenes"]}
        build_captions(caps); ass_path = caps / "e01-v3-johnes-karaoke-qa.ass"; srt = caps / "e01-v3-johnes-captions.srt"; CAP_LEAD = CAP_LEAD_CONTRACT
    else:
        refit, ass_path, srt, CAP_LEAD = build_whisper_timing(cfg, adur, caps, report)
    segs = []
    XF = 0.5  # dissolve entre cenas, centrada na fronteira da narração
    for i, c in enumerate(sel):
        sc = c["scene"]; sd0 = refit[sc]["duration_seconds"]; sd = sd0 + (XF / 2 if i == 0 else XF if i < len(sel) - 1 else XF / 2) + (TAIL_HOLD if sc == "S12" else 0); r = {"scene": sc, "source": c["source"], "id": c["id"], "need_s": sd0}
        try:
            src = WORK / f"{sc}.src.mp4"; r.update(fetch_clip(c, src)); pr = probe(src); r.update({"src_w": pr["w"], "src_h": pr["h"], "src_s": round(pr["dur"], 2)})
            start = min(max(0.4, pr["dur"] * 0.08), max(0.0, pr["dur"] - sd - 0.2)); r["start"] = round(start, 2)
            if pr["w"] > pr["h"] * 0.6:
                cx = c.get("crop_cx") or motion_center(src, pr["dur"]); cw = int(pr["h"] * 9 / 16) // 2 * 2; x0 = int(min(max(cx * pr["w"] - cw / 2, 0), pr["w"] - cw)); r["crop_cx"] = round(cx, 2)
                vf = f"crop={cw}:{pr['h']}:{x0}:0,scale={W}:{H}:flags=lanczos,setsar=1,fps=30"
            else:
                vf = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1,fps=30"
            out = WORK / f"{sc}.seg.mp4"
            vf += ",unsharp=5:5:0.45:5:5:0.0"
            if sc == "S02": vf += ",eq=saturation=0.6:brightness=-0.03"
            if sc == "S12":
                vf += f",scale=2160:3840:flags=lanczos,zoompan=z='min(1+0.00028*on,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps=30"
            subprocess.run([FF, "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{sd:.3f}", "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out)], check=True)
            r["seg_s"] = round(probe(out)["dur"], 2); segs.append(out)
        except Exception as e:
            r["error"] = repr(e)[:160]; report["errors"].append(sc)
        report["scenes"].append(r)
    if report["errors"]:
        print("VNC_MASTER_ABORT scenes_failed", report["errors"]); print("VNC_MASTER_REPORT", json.dumps(report, ensure_ascii=False)); sys.exit(3)
    lens = [probe(p)["dur"] for p in segs]
    ins = []; fcx = []; Lc = lens[0]; prev = "[0:v]"
    for k, p in enumerate(segs): ins += ["-i", str(p)]
    for k in range(1, len(segs)):
        lab = f"[x{k}]"; fcx.append(f"{prev}[{k}:v]xfade=transition=fade:duration={XF}:offset={Lc - XF:.3f}{lab}"); prev = lab; Lc += lens[k] - XF
    subprocess.run([FF, "-v", "error", "-y"] + ins + ["-filter_complex", ";".join(fcx), "-map", prev, "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", str(WORK / "video.mp4")], check=True)
    report["video_seconds"] = round(probe(WORK / "video.mp4")["dur"], 2)
    final = WORK / "master.mp4"
    T = adur + TAIL_HOLD + TAIL_BLACK
    music = fetch_music(WORK / "music.mp3", cfg["music_page"]); mp = probe(WORK / "music.mp3"); music["seconds"] = round(mp["dur"], 2); report["music"] = music
    if mp["dur"] < T + 0.5: print("VNC_MASTER_ABORT music_too_short", mp["dur"]); sys.exit(5)
    at = ass_path.read_text(encoding="utf8")
    at = ST.finalize_ass(at, adur, T, cfg["reference"], cfg["cta"], CAP_LEAD, os.environ.get("VNC_FINAL") == "1")
    report["final_mode"] = os.environ.get("VNC_FINAL") == "1"
    lock_errs = ST.check_constants() + ST.check_final_ass(at, adur, T)
    ass_path.write_text(at, encoding="utf8")
    t0 = adur + 0.5
    make_logo_layers(adur, T, t0, WORK / "logo_frames")
    fc = ST.final_filter(adur, T, t0, ass_path)
    lock_errs += ST.check_filter(fc, ass_path, adur, T, t0) + ST.check_logo(WORK / "logo_frames", adur, T)
    report["logo_signature_head"] = ST.logo_signature(WORK / "logo_frames")["boxes"][:3]; report["style_lock_errors"] = lock_errs
    if lock_errs:
        print("VNC_MASTER_ABORT style_lock", json.dumps(lock_errs, ensure_ascii=False)); sys.exit(8)
    subprocess.run([FF, "-v", "error", "-y", "-i", str(WORK / "video.mp4"), "-i", str(WORK / "voice.mp3"), "-loop", "1", "-framerate", "30", "-i", str(WORK / "logo_frames" / "static.png"), "-i", str(WORK / "music.mp3"), "-framerate", "30", "-i", str(WORK / "logo_frames" / "f_%04d.png"),
        "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", "14M", "-bufsize", "28M", "-c:a", "aac", "-b:a", "192k", "-t", f"{T:.2f}", "-movflags", "+faststart", str(final)], check=True)
    fp = probe(final)
    if (fp["w"], fp["h"]) != (ST.W, ST.H) or abs(fp["dur"] - T) > 0.1:
        print("VNC_MASTER_ABORT style_lock formato_final", fp, T); sys.exit(8)
    report["final"] = {"w": fp["w"], "h": fp["h"], "seconds": round(fp["dur"], 2), "bytes": final.stat().st_size, "sha256": hashlib.sha256(final.read_bytes()).hexdigest()}
    tiles = []
    for sc, s in refit.items():
        t = (s["start_seconds"] + s["end_seconds"]) / 2
        png = subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-i", str(final), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
        tiles.append(Image.open(io.BytesIO(png)).convert("RGB").resize((240, 427)))
    for tt in (adur + 1.5, adur + 2.6, adur + 3.6, T - 2.0, T - 0.5):
        png = subprocess.run([FF, "-v", "error", "-ss", f"{tt:.2f}", "-i", str(final), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
        if png: tiles.append(Image.open(io.BytesIO(png)).convert("RGB").resize((240, 427)))
    sheet = Image.new("RGB", (6 * 240, 3 * 427))
    for k, im in enumerate(tiles): sheet.paste(im, ((k % 6) * 240, (k // 6) * 427))
    b = io.BytesIO(); sheet.save(b, "JPEG", quality=80); sb = base64.b64encode(b.getvalue()).decode()
    print("VNC_MASTER_SHEET", len(sb))
    for n in range(0, len(sb), 1800): print("VNC_MASTER_SHEETB64", n // 1800, sb[n:n + 1800])
    print("VNC_MASTER_REPORT", json.dumps(report, ensure_ascii=False))
    if srt.exists(): print("VNC_SRT", base64.b64encode(srt.read_bytes()).decode())
    vb = base64.b64encode(final.read_bytes()).decode(); print("VNC_MASTER_VIDEO", len(vb))
    for n in range(0, len(vb), 1800): print("VNC_MASTER_B64", n // 1800, vb[n:n + 1800])
    print("VNC_MASTER_END")


def build_whisper_timing(cfg, adur, caps, report):
    """Episodios novos: tempo das palavras = Whisper small (+ conferencia com base) alinhado ao roteiro das 12 cenas."""
    from agents.e01_v2_caption_pipeline import make_cues, export_ass, export_srt
    canon, first = vnc_align.words_from_scenes(cfg["scenes"])
    small = vnc_align.transcribe(WORK / "voice.mp3", "small"); base = vnc_align.transcribe(WORK / "voice.mp3", "base")
    ws, sm = vnc_align.align(canon, small, adur); wb, _ = vnc_align.align(canon, base, adur, strict=False)
    report["align"] = {**sm, "cross_check": vnc_align.cross_check(ws, wb)}
    scenes = vnc_align.scenes_from_words(ws, first, adur)
    cues = make_cues(ws, adur); bad = [c for c in cues if c.get("rule_violations")]
    report["align"]["cues"] = len(cues); report["align"]["typography_flags"] = len(bad)
    if len(bad) > 2:
        print("VNC_MASTER_ABORT caption_typography", len(bad)); sys.exit(7)
    caps.mkdir(exist_ok=True)
    (caps / "karaoke.ass").write_text(export_ass(cues, adur), encoding="utf8"); (caps / "captions.srt").write_text(export_srt(cues), encoding="utf8")
    print("VNC_TIMING", json.dumps({"words": [[w["text"], w["start"], w["end"]] for w in ws], "scenes": scenes}, ensure_ascii=False))
    # Whisper e a propria referencia de tempo: sem antecipacao (a de 70 ms corrigia o atraso do contrato Scribe do E01)
    return {s["id"]: s for s in scenes}, caps / "karaoke.ass", caps / "captions.srt", 0.0


if __name__ == "__main__":
    main()
