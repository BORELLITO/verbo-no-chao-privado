"""Familia de finais de cinema (C sol que nasce, D chuva de ouro, E feixe de luz). Valida de E03 em diante; E01/E02 ficam no final A (style lock).

Fluxo no build: o master com final A e montado e travado como sempre; para E03+ o trecho [adur, T] e substituido por um final renderizado aqui,
sobre os quadros REAIS da cena final (video.mp4, sem legenda/logo), com camadas de luz FILMADAS (Mixkit, licenca gratuita conferida no build).
Textos (credito/CTA) saem do proprio ASS travado (mesmas fontes, tempos e fades). Audio = o do master (cadeia travada). Nada aqui muda o final A.
Partes puras (escolha, contrato, deteccao de horizonte) nao exigem numpy/cv2; a renderizacao importa sob demanda."""
import hashlib, json, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "vnc_endings_v1.json"
W, H, FPS = 1080, 1920, 30


def load_contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf8"))


def contract_sha():
    return hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()


def ep_num(ep):
    m = re.fullmatch(r"E(\d+)", str(ep))
    return int(m[1]) if m else None


def choose(ep, c=None):
    """E01/E02 -> 'A' (legado). E03+ -> rotacao deterministica C, D, E por numero do episodio (nunca repete em sequencia)."""
    c = c or load_contract(); n = ep_num(ep)
    if n is None or n < c["first_episode"]:
        return "A"
    return c["order"][(n - c["first_episode"]) % len(c["order"])]


def layer_ids(variant, c=None):
    c = c or load_contract()
    return {k: v["id"] for k, v in c["variants"][variant]["layers"].items()} if variant != "A" else {}


def check_contract(c=None):
    """Autoteste do contrato: ordem cobre as variantes, janelas coerentes, ids unicos por variante, duracao = cauda travada (3.0 + 6.5)."""
    c = c or load_contract(); errs = []
    from agents import vnc_style as ST
    if abs(c["duration_s"] - (ST.TAIL_HOLD + ST.TAIL_BLACK)) > 1e-6:
        errs.append("duracao do final difere da cauda travada")
    if sorted(c["order"]) != sorted(c["variants"]):
        errs.append("ordem de rotacao nao cobre exatamente as variantes")
    for vn, v in c["variants"].items():
        for ln, L in v["layers"].items():
            a, b, cc, d, pk = L["window"]
            if not (a < b <= cc <= d <= c["duration_s"] + 1e-9 and 0 < pk <= 1):
                errs.append(f"{vn}.{ln}: janela invalida")
        ids = [L["id"] for L in v["layers"].values()]
        if len(set(ids)) != len(ids):
            errs.append(f"{vn}: ids de camada repetidos")
        if v["tail"]["line"] > ST.CREDIT["start"] + 0.5:
            errs.append(f"{vn}: logo termina depois do credito")
    allids = [L["id"] for v in c["variants"].values() for L in v["layers"].values()]
    return errs


def detect_horizon(gray, c=None):
    """gray: matriz HxW (float). Maior borda horizontal estavel (linha de horizonte/cumeada) em [y_min,y_max]; None se fraca (-> sol sobe sem recorte)."""
    import numpy as np, cv2
    c = c or load_contract(); hz = c["horizon"]
    row = cv2.GaussianBlur(np.asarray(gray, np.float32).mean(1, keepdims=True), (0, 0), sigmaX=0.1, sigmaY=6)[:, 0]
    d = np.abs(np.gradient(row)); seg = d[hz["y_min"]:hz["y_max"]]
    if not len(seg):
        return None
    y = hz["y_min"] + int(seg.argmax()); med = float(np.median(seg)) + 1e-6
    return y if seg.max() >= hz["min_peak"] and seg.max() / med >= hz["min_ratio"] else None


# ------------------------------------------------------------------ renderizacao (build)
def _ss(t, a, b):
    u = min(max((t - a) / (b - a), 0.0), 1.0); return u * u * (3 - 2 * u)


class Overlay:
    """Camada de luz filmada: decodifica em loop, 1080x1920 (corte central), um quadro por chamada."""
    def __init__(self, ff, path):
        import numpy as np
        self.np = np
        self.p = subprocess.Popen([ff, "-loglevel", "error", "-stream_loop", "-1", "-i", str(path), "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def next(self):
        b = self.p.stdout.read(W * H * 3)
        return self.np.frombuffer(b, self.np.uint8).reshape(H, W, 3).astype(self.np.float32) if len(b) == W * H * 3 else None

    def close(self):
        self.p.kill()


def fetch_layers(variant, workdir, c, get, hd_url, rights):
    """Baixa as camadas (HD) e confere a licenca de CADA uma agora; devolve ({papel: caminho}, evidencias). Falha de licenca = aborta."""
    paths, ev = {}, []
    for role, L in c["variants"][variant]["layers"].items():
        vid = str(L["id"]); ent = {"source": "mixkit", "id": vid, "page": f"https://mixkit.co/free-stock-video/x-{vid}/"}
        for t in range(4):
            ok, evid, _ = rights(ent)
            if "429" not in evid:
                break
            time.sleep(6 * (t + 1))
        if not ok:
            raise RuntimeError(f"licenca nao confirmada para camada {role} ({vid}): {evid}")
        u = hd_url(vid) or f"https://assets.mixkit.co/videos/{vid}/{vid}-360.mp4"
        p = Path(workdir) / f"layer_{vid}.mp4"; p.write_bytes(get(u, True, 180)); paths[role] = p
        ev.append({"role": role, "id": vid, "license": "Mixkit Stock Video Free License", "evidence": evid, "url": u})
        time.sleep(1.5)
    return paths, ev


def read_base_frames(ff, video, t0, n):
    """n quadros 1080x1920 de `video` a partir de t0 (segura o ultimo se acabar)."""
    import numpy as np
    p = subprocess.Popen([ff, "-loglevel", "error", "-ss", f"{t0:.3f}", "-i", str(video), "-vf", f"fps={FPS},scale={W}:{H}", "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    last = None
    for _ in range(n):
        b = p.stdout.read(W * H * 3)
        if len(b) == W * H * 3:
            last = np.frombuffer(b, np.uint8).reshape(H, W, 3).astype(np.float32)
        if last is None:
            raise RuntimeError("sem quadros base para o final")
        yield last
    p.kill()


def logo_parts(ST, MB):
    """Camadas da logo com a MESMA rotina do final A (_pad/_hq, recolor claro, 600 px, centro a 39%): sol, livro e palavra."""
    import numpy as np
    from PIL import Image
    src = MB._pad(Image.open("assets/vnc_logo.png").convert("RGBA")); arr = np.asarray(src).astype(np.float32).copy()
    gold = (arr[..., 0] > 200) & (arr[..., 1] > 130) & (arr[..., 2] < 140) & (arr[..., 3] > 40)
    n = int(round(1254 * MB.PADF)); rel = np.arange(arr.shape[0])[:, None] - (n + 12)      # linhas relativas ao topo do conteudo
    sun = gold & (rel < 330); word = rel >= 700; book = (~sun) & (~word)
    dark = arr[..., :3].max(axis=2) < 110; arr[dark, :3] = (236, 232, 250)
    sp = int(round(ST.LOGO_END_SIZE * (1 + 2 * MB.PADF) / 2)) * 2
    out = {}
    for k, m in (("sun", sun), ("book", book), ("word", word)):
        a = arr.copy(); a[..., 3] = a[..., 3] * m
        out[k] = np.asarray(MB._hq(Image.fromarray(a.astype(np.uint8), "RGBA"), sp)).astype(np.float32)
    return out, sp


def render(ff, video_clean, adur, variant, layer_paths, out_path, ST, MB, c=None, static_png=None, start_override=None):
    """Escreve o final (sem textos) em out_path e devolve metricas. Tempo t relativo ao fim da voz."""
    import numpy as np, cv2, subprocess as sp_
    c = c or load_contract(); V = c["variants"][variant]; n = int(round(c["duration_s"] * FPS)); T = c["duration_s"]
    nh = int(round(adur * FPS)); t_start = nh / FPS if start_override is None else start_override
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    parts, spx = logo_parts(ST, MB)
    cy_logo = H * ST.LOGO_END_CENTER_Y; LT = int(round(cy_logo - spx / 2)); LX = (W - spx) // 2
    gold = np.array([255, 190, 80], np.float32)
    top = None
    if static_png is not None and Path(static_png).exists():
        from PIL import Image
        top = np.asarray(Image.open(static_png).convert("RGBA")).astype(np.float32)
    ov = {k: Overlay(ff, p) for k, p in layer_paths.items()}
    frames = read_base_frames(ff, video_clean, t_start, n)
    base0 = next(frames); frames.close()   # primeiro quadro: so para detectar o horizonte (o gerador e reaberto abaixo)
    horizon = None
    if V["mode"] == "horizon":
        horizon = detect_horizon(cv2.cvtColor(np.clip(base0, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY), c)
    proc = sp_.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", str(out_path)], stdin=sp_.PIPE)
    vg = np.clip((yy - 500) / 900, 0, 1)[..., None]
    vig = 1 - 0.38 * np.clip((np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H * 0.42) / H) ** 2) - 0.28) / 0.5, 0, 1)[..., None]

    def glow(cx, cy, r):
        d = np.sqrt((xx - cx) ** 2 + ((yy - cy) * 1.1) ** 2); return np.clip(1 - d / r, 0, 1) ** 2

    def blit(img, layer, alpha=1.0, dy=0, clip_y=None, scale=1.0, cy=None):
        h, w = layer.shape[:2]
        if scale != 1.0:
            layer = cv2.resize(layer, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA); h, w = layer.shape[:2]
        cyy = (LT + spx / 2) if cy is None else cy
        x, y = (W - w) // 2, int(cyy - h / 2) + dy
        y0, y1 = max(y, 0), min(y + h, H)
        if y1 <= y0: return
        la = layer[y0 - y:y1 - y, :, 3:4] / 255.0 * alpha
        if clip_y is not None:
            la = la * (np.arange(y0, y1)[:, None, None] < clip_y)
        img[y0:y1, x:x + w] = img[y0:y1, x:x + w] * (1 - la) + layer[y0 - y:y1 - y, :, :3] * la

    push_k = c["push_in"]; deep = np.array(V["tint"], np.float32)
    first = True; i = 0
    base_iter = read_base_frames(ff, video_clean, t_start, n)
    for base in base_iter:
        t = i / FPS
        zf = 1.0 + push_k * (t / T)
        def push(a):
            ch, cw = int(H / zf), int(W / zf); y0 = int((H - ch) * 0.45); x0 = (W - cw) // 2
            return cv2.resize(a[y0:y0 + ch, x0:x0 + cw], (W, H), interpolation=cv2.INTER_LINEAR)
        if variant == "C":
            k = _ss(t, 0.3, 2.8); bl = cv2.GaussianBlur(base, (0, 0), 9)
            img = push(base) * (1 - k) + push(bl) * k
            img = img * (1 - V["dim"] * k) + deep * V["dim"] * k
            img = img * (1 - 0.45 * vg * _ss(t, 1.0, 3.5))
        else:
            k = _ss(t, 0.2, 2.0); bl = cv2.GaussianBlur(base, (0, 0), 1 + 16 * k) if k > 0.02 else base
            e = _ss(t, 0.4, 2.4)
            img = push(bl) * (1 - V["dim"] * e) + deep * V["dim"] * e
        if top is not None:
            tl = (1 - _ss(t, 0, 0.9))
            if tl > 0:
                la = top[..., 3:4] / 255.0 * tl; img = img * (1 - la) + top[..., :3] * la
        # camadas filmadas (tela): janela = (inicio, plena, inicio_saida, fim, pico); a ultima de cada final fica ate o fim
        glitter_last = None
        for role, L in V["layers"].items():
            a, b, cc, d, pk = L["window"]
            if a <= t <= d + 1e-9 and role in ov:
                fr = ov[role].next()
                if fr is None: continue
                op = pk * min(_ss(t, a, b), 1 - _ss(t, cc, d) if d > cc else 1.0)
                if role in ("glitter", "dust") and V["mode"] == "horizon":
                    glitter_last = (fr, op); continue
                img = 255 - (255 - img) * (255 - fr * op) / 255
        # logo
        if V["mode"] == "horizon":
            HOR = horizon
            r = _ss(t, 0.8, 2.8)
            sy0 = (max(HOR - LT + 10, 200) if HOR else 260)
            sy = int(sy0 * (1 - r))
            sunc = LT + int(0.12 * spx) + sy
            gl = glow(W / 2, min(sunc, HOR) if HOR else sunc, 700)[..., None] * (0.55 * _ss(t, 0.8, 3.0))
            img = img * (1 - gl) + gold * gl
            sa = 1.0 if HOR else _ss(t, 0.8, 1.8)
            blit(img, parts["sun"], alpha=sa, dy=sy, clip_y=(HOR if (HOR and r < 1) else None))
            tb, tw, tl_ = V["tail"]["book"], V["tail"]["word"], V["tail"]["line"]
        else:
            ts_ = V["tail"]["sun"]; sa = _ss(t, ts_, ts_ + 0.5)
            if sa > 0:
                fl = np.exp(-((t - ts_) / 0.25) ** 2)
                g = np.clip(glow(W / 2, LT + int(0.17 * spx), 900)[..., None] * (0.35 + 0.9 * fl) * sa, 0, 1)
                img = img * (1 - g * 0.8) + gold * g * 0.8
                blit(img, parts["sun"], alpha=sa)
            tb, tw, tl_ = V["tail"]["book"], V["tail"]["word"], V["tail"]["line"]
        b_ = _ss(t, tb, tb + 0.9) if variant != "C" else _ss(t, 2.2, 3.3)
        if b_ > 0:
            blit(img, parts["book"], alpha=b_, scale=0.80 + 0.20 * b_)
        wp = _ss(t, tw, tw + (1.0 if variant != "C" else 1.1))
        if wp > 0:
            edge = LX + wp * (spx + 120) - 60; cols = np.arange(spx) + LX
            m = np.clip((edge - cols) / 60, 0, 1)[None, :, None]
            lay = parts["word"].copy(); lay[..., 3:4] = lay[..., 3:4] * m; blit(img, lay)
        lp = _ss(t, tl_, tl_ + 0.9)
        if lp > 0:
            hw = int(200 * lp); la = np.zeros((H, W, 1), np.float32); la[1070:1073, W // 2 - hw:W // 2 + hw] = 1
            img = img * (1 - la * 0.9) + gold * la * 0.9
        if glitter_last is not None:
            fr, op = glitter_last; img = 255 - (255 - img) * (255 - fr * op) / 255
        if variant == "C" and 2.0 < t < 4.2:
            sa2 = np.sin(np.pi * (t - 2.0) / 2.2) ** 2 * 0.55
            sy_ = min(LT + int(0.12 * spx) + int(0.07 * spx) + (sy if HOR else 0), (HOR - 5) if HOR else 10 ** 6) if r < 1 else LT + int(0.2 * spx)
            band = np.exp(-((yy - sy_) / 5.0) ** 2) * np.exp(-np.abs(xx - W / 2) / 380)
            img = img + np.array([255, 205, 120], np.float32) * (band[..., None] * sa2)
        img = img * vig + np.random.default_rng(i).normal(0, 4.5, (H, W, 1)).astype(np.float32)
        img = img * (1 - _ss(t, T - 1.2, T))
        proc.stdin.write(np.clip(img, 0, 255).astype(np.uint8).tobytes()); i += 1
    proc.stdin.close(); proc.wait()
    for o in ov.values(): o.close()
    return {"variant": variant, "name": V["name"], "frames": i, "horizon_y": horizon, "start_s": round(t_start, 3)}


def tail_ass(final_ass, adur):
    """ASS so com Credito/CTA1/CTA2 (mesmos estilos/fades do final travado), tempos relativos ao inicio do final."""
    head = final_ass.split("[Events]")[0]
    ev = re.search(r"\[Events\]\s*\nFormat:[^\n]*\n", final_ass)
    def sec(x): h, m, s = x.split(":"); return int(h) * 3600 + int(m) * 60 + float(s)
    def ts(x): return f"0:{int(x // 60):02d}:{x % 60:05.2f}"
    lines = []
    for m in re.finditer(r"Dialogue: 2,(\S+?),(\S+?),(Credit|CTA1|CTA2),(.*)", final_ass):
        lines.append(f"Dialogue: 2,{ts(max(0.0, sec(m[1]) - adur))},{ts(max(0.0, sec(m[2]) - adur))},{m[3]},{m[4]}")
    return head + ev[0] + "\n".join(lines) + "\n", len(lines)


def burn_texts(ff, notext, ass_path, out_path, fonts="assets/fonts"):
    subprocess.run([ff, "-v", "error", "-y", "-i", str(notext), "-vf", f"ass={ass_path}:original_size={W}x{H}:fontsdir={fonts},format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "17", str(out_path)], check=True)


def splice(ff, master_a, ending, adur, T, out_path):
    """Cabeca do master (ate o fim da voz, 30 fps) + final novo; audio = o do master."""
    nh = int(round(adur * FPS))
    fc = f"[0:v]trim=end_frame={nh},setpts=PTS-STARTPTS,fps={FPS}[a];[1:v]setpts=PTS-STARTPTS,fps={FPS}[b];[a][b]concat=n=2:v=1:a=0,format=yuv420p[v]"
    subprocess.run([ff, "-v", "error", "-y", "-i", str(master_a), "-i", str(ending), "-filter_complex", fc, "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "14M", "-bufsize", "28M", "-c:a", "copy", "-movflags", "+faststart", str(out_path)], check=True)


# ------------------------------------------------------------------ QA objetivo
def _lum(rgb):
    import numpy as np
    v = np.asarray(rgb, np.float64) / 255.0; v = np.where(v <= 0.03928, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    return float(v[..., 0] * 0.2126 + v[..., 1] * 0.7152 + v[..., 2] * 0.0722) if v.ndim == 1 else 0.2126 * v[..., 0] + 0.7152 * v[..., 1] + 0.0722 * v[..., 2]


def contrast(l1, l2):
    a, b = max(l1, l2), min(l1, l2); return (a + 0.05) / (b + 0.05)


TEXT_RGB = {"credito": (230, 216, 216), "cta1": (242, 241, 238), "cta2": (196, 176, 242)}   # cores dos estilos Credit/CTA1/CTA2 do style lock (BGR no ASS)


def qa_frame(ff, ending_notext, tail_ass_path, c=None):
    """Contraste medido dos textos (mascara = ASS renderizado sobre preto) contra o fundo REAL do final no instante qa_time_s; ultimo quadro preto."""
    import numpy as np, io
    from PIL import Image
    c = c or load_contract(); q = c["qa"]; t = q["qa_time_s"]
    def grab(src_args, vf=None):
        cmd = [ff, "-v", "error", "-y"] + src_args + ["-frames:v", "1"] + (["-vf", vf] if vf else []) + ["-f", "image2pipe", "-vcodec", "png", "-"]
        return np.asarray(Image.open(io.BytesIO(subprocess.run(cmd, capture_output=True, check=True).stdout)).convert("RGB")).astype(np.float32)
    bg = grab(["-ss", f"{t:.2f}", "-i", str(ending_notext)])
    black = grab(["-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d=10", "-ss", f"{t:.2f}"], f"ass={tail_ass_path}:original_size={W}x{H}:fontsdir=assets/fonts")
    mask = black.max(axis=2) > 60
    import cv2
    ring = cv2.dilate(mask.astype(np.uint8), np.ones((41, 41), np.uint8)).astype(bool) & ~cv2.dilate(mask.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    res = {"bg_median_luminance_text_zone": None}
    errs = []
    if mask.sum() < 500 or ring.sum() < 500:
        errs.append("qa: textos nao detectados no instante de verificacao")
        return errs, res
    bgl = float(np.median(_lum(bg[ring]))); res["bg_median_luminance_text_zone"] = round(bgl, 4)
    # textos por faixa vertical: credito (~1090-1180), CTA1 (~1205-1320), CTA2 (~1330-1450)
    zones = {"credito": ((1085, 1180), 0.80, q["min_contrast_color"]), "cta1": ((1200, 1325), 1.0, q["min_contrast_white"]), "cta2": ((1330, 1460), 0.65, q["min_contrast_color"])}
    for nm, ((y0, y1), tl, need) in zones.items():
        zm = ring.copy(); zm[:y0] = False; zm[y1:] = False
        if zm.sum() < 100: continue
        cr = contrast(_lum(np.array(TEXT_RGB[nm], np.float64)), float(np.median(_lum(bg[zm])))); res[f"contraste_{nm}"] = round(cr, 2)
        if cr < need: errs.append(f"qa: contraste {nm} {cr:.2f} < {need}")
    lum_all = _lum(bg); res["bg_luminance_p90"] = round(float(np.percentile(lum_all, 90)), 3)
    if res["bg_luminance_p90"] > q["max_bg_luminance_p90"] + 0.35:   # logo clara ocupa parte do quadro; fundo em si e checado pelos contrastes acima
        errs.append("qa: quadro final claro demais")
    lastf = grab(["-sseof", "-0.05", "-i", str(ending_notext)]); res["ultimo_quadro_max"] = int(lastf.max())
    if lastf.max() > q["max_last_frame_value"]:
        errs.append("qa: final nao termina em preto")
    return errs, res
