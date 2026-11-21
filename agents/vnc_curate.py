"""Curadoria automatica de clipes (runner). Gratuita, sem chave de API, so fontes com licenca livre e listagem publica (Mixkit).

Fluxo por episodio (episodes/<ID>.json -> "curation" opcional; senao arco padrao contracts/vnc_arc_template_v1.json):
  listagens Mixkit por palavra-chave -> descarta ja usados/descartados (registro), pessoas/cidade/etc., duplicatas
  -> baixa previa 360p -> mede (duracao, orientacao, movimento, cortes, brilho, saturacao, nitidez, hash perceptual)
  -> rejeita automaticamente (estatico, cortes, escuro/claro demais para o clima da cena, curto demais, quase-duplicata)
  -> ranqueia e imprime JSON + planilha de contato (VNC_CURATE_JSON / VNC_CURATE_SHEETB64) para aprovacao.
Nada e escolhido sozinho: o Claude revisa a planilha, grava a selecao e registra no registro (travas em vnc_gates).
Funcoes puras (parse/score/filtros) testadas offline em tests/test_vnc_curate.py.
"""
import base64, io, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"}
PEOPLE = {"woman", "women", "man", "men", "girl", "boy", "people", "person", "child", "children", "kid", "kids", "couple", "family", "baby", "crowd",
          "selfie", "portrait", "face", "dancing", "dance", "walking", "running", "friends", "student", "worker", "businessman", "businesswoman", "tourist"}
URBAN = {"car", "cars", "traffic", "city", "building", "buildings", "street", "phone", "computer", "laptop", "office", "restaurant", "food", "drink", "beer", "party",
         "club", "shop", "mall", "airport", "train", "bus", "road", "highway", "skyscraper", "times", "square", "neon", "screen", "tv", "machine", "factory", "drone"}
GLOBAL_EXCLUDE = {"green", "chroma", "greenscreen", "cross", "rosary", "church", "bikini", "wine", "alcohol", "cocktail", "latte", "coffee", "cartoon", "animation", "logo"}
HAND_OK = {"hand", "hands"}
MOODS = {"dark": (35, 105), "mid": (70, 150), "bright": (115, 210)}  # faixa de brilho medio (0-255) aceita por clima


def get(url, binary=True, timeout=60, limit=25_000_000, retries=4):
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                data = r.read(limit + 1)
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or i == retries:
                raise
            time.sleep(4 * (2 ** i))  # backoff: 4, 8, 16, 32 s
    if len(data) > limit:
        raise RuntimeError("too_large")
    return data if binary else data.decode("utf8", "ignore")


# ---------- funcoes puras ----------
def parse_listing(html):
    """Entradas da listagem Mixkit: [{id, slug, title, page, preview}] (ids com URL padrao; os de URL opaca sao ignorados)."""
    out, seen = [], set()
    for m in re.finditer(r'/free-stock-video/([a-z0-9][a-z0-9\-]*?)-(\d{1,7})/', html):
        slug, vid = m.group(1), m.group(2)
        if vid in seen:
            continue
        seen.add(vid)
        if f"assets.mixkit.co/videos/{vid}/{vid}-" not in html:
            continue  # sem URL de previa padrao
        out.append({"id": vid, "slug": slug, "title": slug.replace("-", " "), "page": f"https://mixkit.co/free-stock-video/{slug}-{vid}/",
                    "preview": f"https://assets.mixkit.co/videos/{vid}/{vid}-360.mp4"})
    return out


def title_ok(title, allow=(), extra_exclude=()):
    """Titulo sem pessoas/cidade/maquinas (e sem maos, salvo cena que as permite via allow=['hands'])."""
    words = set(re.findall(r"[a-z]+", title.lower()))
    hit = words & ((PEOPLE | URBAN | HAND_OK | set(extra_exclude)) - set(allow)) | (words & GLOBAL_EXCLUDE)
    return (not hit), sorted(hit)


def used_ids(reg, episode):
    """ids Mixkit ja usados/descartados em QUALQUER episodio (inclusive o atual: nao reaproveitar dentro do mesmo)."""
    out = set()
    for ep, d in reg.get("episodes", {}).items():
        for c in d.get("used", []):
            if str(c.get("source")).lower() == "mixkit":
                out.add(str(c["id"]))
        for lst in d.get("discarded_versions", {}).values():
            out |= {str(c["id"]) for c in lst if str(c.get("source")).lower() == "mixkit"}
    return out


def dhash(gray, n=8):
    """Hash perceptual (dHash) de um quadro em tons de cinza (numpy 2D)."""
    import numpy as np
    from PIL import Image
    im = Image.fromarray(gray.astype("uint8")).resize((n + 1, n))
    a = np.asarray(im, dtype=float)
    return int("".join("1" if x else "0" for x in (a[:, 1:] > a[:, :-1]).flatten()), 2)


def hamming(a, b):
    return bin(a ^ b).count("1")


def metrics_from_frames(frames):
    """frames: lista de arrays RGB (h,w,3) uint8 amostrados a cada 0,5 s."""
    import numpy as np
    g = [f.mean(axis=2) for f in frames]
    diffs = [float(np.abs(g[i + 1] - g[i]).mean()) for i in range(len(g) - 1)] or [0.0]
    med = float(np.median(diffs)); mx = max(diffs)
    mx_rgb = np.stack(frames).astype(float)
    sat = float(((mx_rgb.max(axis=3) - mx_rgb.min(axis=3)) / (mx_rgb.max(axis=3) + 1)).mean() * 255)
    lap = [float(np.abs(np.diff(x, axis=0)).mean() + np.abs(np.diff(x, axis=1)).mean()) for x in g]
    return {"brightness": round(float(np.mean([x.mean() for x in g])), 1), "saturation": round(sat, 1), "motion": round(med, 2),
            "cut_ratio": round(mx / (med + 0.5), 2), "sharp": round(float(np.mean(lap)), 2)}


def reject_reason(m, mood, need_s, dur, w, h):
    lo, hi = MOODS[mood]
    if w < h: return "vertical (padrao e paisagem)"
    if dur < need_s: return f"curto ({dur:.1f}s < {need_s:.1f}s)"
    if m["motion"] < 0.35: return "estatico (parece foto)"
    if m["motion"] > 22: return "movimento frenetico"
    if m["cut_ratio"] > 9 and m["motion"] > 1.5: return "tem cortes/saltos"
    if not (lo - 12 <= m["brightness"] <= hi + 12): return f"brilho {m['brightness']} fora do clima {mood}"
    return None


def score(m, mood, kw_hit):
    lo, hi = MOODS[mood]; mid = (lo + hi) / 2
    s = 1.0 - abs(m["brightness"] - mid) / (hi - lo + 40)
    s += 0.5 * (1.0 - min(abs(m["motion"] - 5.0) / 8.0, 1.0))      # movimento suave e perceptivel
    s += min(m["sharp"], 12) / 40.0
    s += 0.25 * kw_hit
    s -= 0.25 * max(0, m["cut_ratio"] - 4) / 5
    s -= 0.4 * max(0.0, m["saturation"] - 110) / 80          # tom sobrio: penaliza cor saturada demais
    return round(s, 3)


def pick_top(cands, k=4, min_hamming=7):
    """Ranqueia e remove quase-duplicatas (hash perceptual) entre os candidatos da mesma cena."""
    out = []
    for c in sorted(cands, key=lambda x: -x["score"]):
        if all(hamming(c["phash"], o["phash"]) >= min_hamming for o in out):
            out.append(c)
        if len(out) == k:
            break
    return out


# ---------- runner ----------
def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe(path):
    e = subprocess.run([_ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    d = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", e); v = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", e)
    return (int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]) if d else 0.0), (int(v[1]) if v else 0), (int(v[2]) if v else 0)


def sample_frames(path, w=160, h=90, max_frames=24):
    import numpy as np
    raw = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-vf", f"fps=2,scale={w}:{h}", "-frames:v", str(max_frames), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    return [np.frombuffer(raw[i * w * h * 3:(i + 1) * w * h * 3], dtype="uint8").reshape(h, w, 3) for i in range(n)]


def thumb(path, dur):
    from PIL import Image
    png = subprocess.run([_ffmpeg(), "-v", "error", "-ss", f"{dur / 2:.2f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=240:135", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    return Image.open(io.BytesIO(png)).convert("RGB")


def analyse(entry, mood, need_s, work):
    f = work / f"{entry['id']}.mp4"
    try:
        if not f.exists():
            f.write_bytes(get(entry["preview"]))
        dur, w, h = probe(f); fr = sample_frames(f)
        if len(fr) < 3:
            return None
        m = metrics_from_frames(fr)
        import numpy as np
        return {"dur": dur, "w": w, "h": h, "m": m, "phash": dhash(fr[len(fr) // 2].mean(axis=2)), "file": str(f)}
    except Exception as e:  # noqa
        return {"error": repr(e)[:80]}


def run(ep):
    cfg = json.loads((ROOT / "episodes" / f"{ep}.json").read_text(encoding="utf8"))
    tpl = json.loads((ROOT / "contracts" / "vnc_arc_template_v1.json").read_text(encoding="utf8"))["scenes"]
    reg = json.loads((ROOT / "contracts" / "vnc_clip_registry_v1.json").read_text(encoding="utf8"))
    plan = {s["id"]: dict(s) for s in tpl}
    for s, c in (cfg.get("curation") or {}).items():
        plan[s].update(c)
    taken = used_ids(reg, ep) - {str(c["id"]) for c in reg.get("episodes", {}).get(ep, {}).get("used", [])}
    work = Path("/tmp/curate"); work.mkdir(exist_ok=True)
    listing = {}
    def list_kw(kw):
        slug = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-")
        out = []
        for page in (1, 2, 3):
            try:
                out += parse_listing(get(f"https://mixkit.co/free-stock-video/{slug}/" + (f"?page={page}" if page > 1 else ""), False))
            except Exception as e:  # noqa
                print("VNC_CURATE_WARN listagem", slug, page, repr(e)[:60])
        return out
    kws = sorted({k for s in plan.values() for k in s["queries"]})
    for k in kws:  # serial e espacado: o Mixkit devolve 429 sob paralelismo
        listing[k] = list_kw(k)
        time.sleep(1.5)
    result, cache, rejected, allc, stats = {}, {}, {}, {}, {}
    for sid in sorted(plan):
        s = plan[sid]; pool = {}
        for k in s["queries"]:
            for e in listing.get(k, []):
                ok, hit = title_ok(e["title"], s.get("allow", ()), s.get("exclude", ()))
                if e["id"] in taken or not ok or e["id"] in pool:
                    continue
                kw_hit = sum(w in e["title"] for w in s.get("prefer", []))
                pool[e["id"]] = dict(e, kw_hit=kw_hit)
        top = sorted(pool.values(), key=lambda e: -e["kw_hit"])[: s.get("max_downloads", 30)]
        with ThreadPoolExecutor(8) as ex:
            res = list(ex.map(lambda e: cache.get(e["id"]) or analyse(e, s["mood"], s["min_seconds"], work), top))
        cands, rej = [], []
        for e, a in zip(top, res):
            if not a or "error" in a:
                rej.append([e["id"], "erro/curto"]); continue
            cache[e["id"]] = a
            why = reject_reason(a["m"], s["mood"], s["min_seconds"], a["dur"], a["w"], a["h"])
            if why:
                rej.append([e["id"], why]); continue
            cands.append({"id": e["id"], "title": e["title"], "page": e["page"], "dur": round(a["dur"], 1), "score": score(a["m"], s["mood"], e["kw_hit"]), "m": a["m"], "phash": a["phash"], "file": a["file"]})
        allc[sid] = cands; rejected[sid] = rej; stats[sid] = (len(pool), len(top))
    # atribuicao global: um clipe so aparece em UMA cena (cenas com menos opcoes escolhem primeiro)
    claimed = set()
    for sid in sorted(allc, key=lambda x: (len(allc[x]), x)):
        avail = [c for c in allc[sid] if c["id"] not in claimed]
        result[sid] = pick_top(avail, plan[sid].get("keep", 6))
        claimed |= {c["id"] for c in result[sid]}
        print("VNC_CURATE_SCENE", sid, plan[sid]["mood"], "pool", stats[sid][0], "analisados", stats[sid][1], "aprovados", len(allc[sid]), "top", [c["id"] for c in result[sid]], "rejeicoes", rejected[sid][:6])
    # planilha de contato
    from PIL import Image, ImageDraw
    cols, tw, th = 6, 240, 135
    sheet = Image.new("RGB", (cols * tw + 70, 12 * th), (12, 12, 14)); d = ImageDraw.Draw(sheet)
    for r, sid in enumerate(sorted(result)):
        d.text((6, r * th + 6), sid, fill=(240, 240, 240))
        for c_i, c in enumerate(result[sid]):
            try:
                sheet.paste(thumb(Path(c["file"]), c["dur"]), (70 + c_i * tw, r * th)); d.text((74 + c_i * tw, r * th + 4), f"{c['id']} {c['score']}", fill=(255, 220, 90))
            except Exception:  # noqa
                pass
    b = io.BytesIO(); sheet.convert("RGB").save(b, "JPEG", quality=80); sb = base64.b64encode(b.getvalue()).decode()
    for n in range(0, len(sb), 1800):
        print("VNC_CURATE_SHEETB64", n // 1800, sb[n:n + 1800])
    out = {sid: [{k: v for k, v in c.items() if k not in ("file",)} for c in cs] for sid, cs in result.items()}
    print("VNC_CURATE_JSON", json.dumps({"episode": ep, "candidates": out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
