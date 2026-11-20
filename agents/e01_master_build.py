"""E01 master preview builder. Runs on a GitHub runner only.

Downloads the 12 selected free clips (Pexels, Mixkit, Coverr), crops each to 9:16 around the motion centroid,
cuts them to the scene timings, burns the approved karaoke captions and muxes the existing Johnes Bittar narration
(downloaded from the already generated take; no new voice, no spend). Output is printed as base64 chunks for the
owner's private copy; nothing is uploaded, committed or published."""
import base64, hashlib, io, json, os, re, subprocess, sys, urllib.request
from pathlib import Path
import imageio_ffmpeg, numpy as np
from PIL import Image

from agents.e01_v3_voice_captions import build as build_captions

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


MUSIC_PAGE = os.environ.get("VNC_MUSIC_PAGE", "https://mixkit.co/free-stock-music/a-new-life/")
TAIL_HOLD, TAIL_BLACK = 3.0, 4.0
CAP_LEAD = 0.07  # legenda 70 ms antes: checagem independente (Whisper) mostrou destaque ~100 ms atrasado em mediana


def fetch_music(dest):
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


def make_logo(dest):
    from PIL import ImageFilter
    lg = Image.open("assets/vnc_logo.png").convert("RGBA").resize((1000, 1000), Image.LANCZOS)
    a = lg.split()[3]
    glow = Image.new("RGBA", lg.size, (255, 255, 255, 0)); glow.putalpha(a.filter(ImageFilter.GaussianBlur(16)).point(lambda v: int(v * 0.55)))
    out = Image.new("RGBA", lg.size, (0, 0, 0, 0)); out = Image.alpha_composite(out, glow); out = Image.alpha_composite(out, lg); out.save(dest)
    import numpy as _np
    arr = _np.asarray(lg).copy(); dark = arr[..., :3].max(axis=2) < 110; arr[dark, :3] = (236, 232, 250)
    Image.fromarray(arr, "RGBA").save(str(dest).replace("logo.png", "logo_light.png"))


def main():
    audio_link = os.environ.get("VNC_E01_AUDIO_URL", "").strip()
    if not audio_link.startswith("https://elevenlabsusercontent.com/"):
        print("VNC_MASTER_ABORT no_audio_secret"); sys.exit(4)
    sel = json.loads(Path(os.environ.get("VNC_SELECTION","contracts/e01_v3_scene_clip_selection_v1.json")).read_text())["clips"]
    refit = {s["id"][-3:]: s for s in json.loads(Path("contracts/e01_v3_12_scene_refit_v1.json").read_text())["scenes"]}
    report = {"scenes": [], "errors": []}
    audio = get(audio_link); (WORK / "voice.mp3").write_bytes(audio)
    sha = hashlib.sha256(audio).hexdigest(); report["audio_sha256"] = sha
    if not (sha.startswith(AUDIO_SHA_PREFIX) and sha.endswith(AUDIO_SHA_SUFFIX)):
        print("VNC_MASTER_ABORT audio_sha_mismatch", sha); sys.exit(2)
    adur = probe(WORK / "voice.mp3")["dur"]; report["audio_seconds"] = round(adur, 2)
    caps = WORK / "caps"; build_captions(caps)
    segs = []
    for c in sel:
        sc = c["scene"]; sd = refit[sc]["duration_seconds"]; r = {"scene": sc, "source": c["source"], "id": c["id"], "need_s": sd}
        try:
            src = WORK / f"{sc}.src.mp4"; r.update(fetch_clip(c, src)); pr = probe(src); r.update({"src_w": pr["w"], "src_h": pr["h"], "src_s": round(pr["dur"], 2)})
            start = min(max(0.4, pr["dur"] * 0.08), max(0.0, pr["dur"] - sd - 0.2)); r["start"] = round(start, 2)
            if pr["w"] > pr["h"] * 0.6:
                cx = c.get("crop_cx") or motion_center(src, pr["dur"]); cw = int(pr["h"] * 9 / 16) // 2 * 2; x0 = int(min(max(cx * pr["w"] - cw / 2, 0), pr["w"] - cw)); r["crop_cx"] = round(cx, 2)
                vf = f"crop={cw}:{pr['h']}:{x0}:0,scale={W}:{H}:flags=lanczos,setsar=1,fps=30"
            else:
                vf = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1,fps=30"
            out = WORK / f"{sc}.seg.mp4"
            if sc == "S12":
                sd += TAIL_HOLD; start = min(start, max(0.0, pr["dur"] - sd - 0.2))
                vf += f",scale=2160:3840:flags=lanczos,zoompan=z='min(1+0.00028*on,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps=30"
            subprocess.run([FF, "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{sd:.3f}", "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out)], check=True)
            r["seg_s"] = round(probe(out)["dur"], 2); segs.append(out)
        except Exception as e:
            r["error"] = repr(e)[:160]; report["errors"].append(sc)
        report["scenes"].append(r)
    if report["errors"]:
        print("VNC_MASTER_ABORT scenes_failed", report["errors"]); print("VNC_MASTER_REPORT", json.dumps(report, ensure_ascii=False)); sys.exit(3)
    (WORK / "list.txt").write_text("".join(f"file '{p}'\n" for p in segs))
    subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(WORK / "list.txt"), "-c", "copy", str(WORK / "video.mp4")], check=True)
    final = WORK / "e01_master_preview_720.mp4"
    T = adur + TAIL_HOLD + TAIL_BLACK
    music = fetch_music(WORK / "music.mp3"); mp = probe(WORK / "music.mp3"); music["seconds"] = round(mp["dur"], 2); report["music"] = music
    if mp["dur"] < T + 0.5: print("VNC_MASTER_ABORT music_too_short", mp["dur"]); sys.exit(5)
    make_logo(WORK / "logo.png")
    ass_path = caps / "e01-v3-johnes-karaoke-qa.ass"; at = ass_path.read_text(encoding="utf8")
    fam = re.search(r"Style: Caption,([^,]+),", at)[1]
    at = at.replace(",8,90,90,118,1", ",2,90,90,40,1")
    at = re.sub(r"(Dialogue: 1,0:00:00\.00,)(\S+?)(,QA)", lambda m: m[1] + f"0:01:{T-60:05.2f}" + m[3], at, count=1)
    at = at.replace("[Events]", f"Style: Credit,{fam},46,&H00E6E6E6,&H00E6E6E6,&H00141210,&H00000000,0,0,0,0,100,100,2,0,1,2,0,8,90,90,1215,1\n\n[Events]", 1) if "[Events]" in at else at
    def ts(x): return f"0:{int(x // 60):02d}:{x % 60:05.2f}"
    at = at.rstrip("\n") + f"\nDialogue: 2,{ts(adur + 3.4)},{ts(T - 0.9)},Credit,,0,0,0,,{{\\fad(800,900)}}Habacuque 1:2–4\n"
    def _sec(x):
        h, mi, se = x.split(":"); return int(h) * 3600 + int(mi) * 60 + float(se)
    def _shift(m):
        a, b = max(0.0, _sec(m[2]) - CAP_LEAD), max(0.0, _sec(m[3]) - CAP_LEAD)
        return f"Dialogue: 0,{ts(a)},{ts(b)},Caption,"
    at = re.sub(r"Dialogue: 0,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),Caption,", lambda m: _shift([None, None, m[1], m[2]]), at)
    ass_path.write_text(at, encoding="utf8")
    t0, d = adur + 0.5, 2.4
    E = f"(pow(clip((t-{t0:.2f})/{d},0,1),2)*(3-2*clip((t-{t0:.2f})/{d},0,1)))"
    fc = (f"[0:v]fade=t=out:st={adur + 0.6:.2f}:d=2.4:color=black,tpad=stop_mode=add:stop_duration={TAIL_BLACK}:color=black[bv];"
          f"[2:v]format=rgba,colorchannelmixer=aa=0.8,fade=t=in:st=0.5:d=1.0:alpha=1,scale=w='trunc((210+510*{E})/2)*2':h=-1:eval=frame:flags=lanczos[lg];"
          f"[bv][lg]overlay=x='(W-w)/2':y='105+((H*0.42-h/2)-105)*{E}':eof_action=pass:format=auto[o1];"
          f"[4:v]format=rgba,fade=t=in:st={adur + 1.6:.2f}:d=1.0:alpha=1,scale=w='trunc((210+510*{E})/2)*2':h=-1:eval=frame:flags=lanczos[lg2];"
          f"[o1][lg2]overlay=x='(W-w)/2':y='105+((H*0.42-h/2)-105)*{E}':eof_action=pass:format=auto[ov];"
          f"[ov]ass={ass_path}:original_size={W}x{H}:fontsdir=assets/fonts,fade=t=out:st={T - 1.2:.2f}:d=1.2,scale=720:1280:flags=lanczos,format=yuv420p[v];"
          f"[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,apad,atrim=0:{T:.2f},asplit=2[vo][vk];"
          f"[3:a]aresample=48000,loudnorm=I=-26:TP=-3:LRA=7,aresample=48000,atrim=0:{T:.2f},afade=t=in:st=0:d=2.5,volume='1+1.2*clip((t-{adur:.2f})/2.5,0,1)':eval=frame[m];"
          f"[m][vk]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=500[md];"
          f"[md]afade=t=out:st={T - 3.5:.2f}:d=3.5[mf];"
          f"[vo][mf]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.95[a]")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(WORK / "video.mp4"), "-i", str(WORK / "voice.mp3"), "-loop", "1", "-framerate", "30", "-i", str(WORK / "logo.png"), "-i", str(WORK / "music.mp3"), "-loop", "1", "-framerate", "30", "-i", str(WORK / "logo_light.png"),
        "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-c:a", "aac", "-b:a", "160k", "-t", f"{T:.2f}", "-movflags", "+faststart", str(final)], check=True)
    fp = probe(final); report["final"] = {"w": fp["w"], "h": fp["h"], "seconds": round(fp["dur"], 2), "bytes": final.stat().st_size, "sha256": hashlib.sha256(final.read_bytes()).hexdigest()}
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
    vb = base64.b64encode(final.read_bytes()).decode(); print("VNC_MASTER_VIDEO", len(vb))
    for n in range(0, len(vb), 1800): print("VNC_MASTER_B64", n // 1800, vb[n:n + 1800])
    print("VNC_MASTER_END")


if __name__ == "__main__":
    main()
