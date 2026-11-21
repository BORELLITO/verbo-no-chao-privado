"""Curadoria automatica de clipes (runner). Gratuita, sem chave de API, so fontes com licenca livre e listagem publica (Mixkit).

Fluxo por episodio (episodes/<ID>.json -> "curation" opcional; senao arco padrao contracts/vnc_arc_template_v1.json):
  listagens Mixkit por palavra-chave -> descarta ja usados/descartados (registro), pessoas/cidade/etc., duplicatas
  -> baixa previa 360p -> mede (duracao, orientacao, movimento, cortes, brilho, saturacao, nitidez, hash perceptual)
  -> rejeita automaticamente (estatico, cortes, escuro/claro demais para o clima da cena, curto demais, quase-duplicata)
  -> ranqueia e imprime JSON + planilha de contato (VNC_CURATE_JSON / VNC_CURATE_SHEETB64) para aprovacao.
Nada e escolhido sozinho: o Claude revisa a planilha, grava a selecao e registra no registro (travas em vnc_gates).
Funcoes puras (parse/score/filtros) testadas offline em tests/test_vnc_curate.py.
"""
import base64, hashlib, io, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from agents import vnc_memory as MEM, vnc_plan as PLAN, vnc_select as SEL

ROOT = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"}
PEOPLE = {"woman", "women", "man", "men", "girl", "boy", "people", "person", "child", "children", "kid", "kids", "couple", "family", "baby", "crowd",
          "selfie", "portrait", "face", "dancing", "dance", "walking", "running", "friends", "student", "worker", "businessman", "businesswoman", "tourist"}
URBAN = {"car", "cars", "traffic", "city", "building", "buildings", "street", "phone", "computer", "laptop", "office", "restaurant", "food", "drink", "beer", "party",
         "club", "shop", "mall", "airport", "train", "bus", "road", "highway", "skyscraper", "times", "square", "neon", "screen", "tv", "machine", "factory", "drone", "smartphone", "texting", "mobile", "cellphone", "tablet", "keyboard", "typing", "money", "cash"}
GLOBAL_EXCLUDE = {"green", "chroma", "greenscreen", "cross", "rosary", "church", "bikini", "wine", "alcohol", "cocktail", "latte", "coffee", "cartoon", "animation", "logo", "pumpkin", "halloween", "birthday", "cake", "wedding", "romantic", "petals", "resort", "hotel", "statue", "contract", "document", "signing", "paper", "celebration", "christmas", "festive"}
HAND_OK = {"hand", "hands"}
MOODS = {"dark": (35, 105), "mid": (70, 150), "bright": (115, 210)}  # faixa de brilho medio (0-255) aceita por clima


def get(url, binary=True, timeout=60, limit=25_000_000, retries=2):
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                data = r.read(limit + 1)
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or i == retries:
                raise
            time.sleep(6 * (2 ** i))  # backoff: 6, 12 s
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


def analyse(entry, work):
    """Baixa a previa 360p (so se nao ha cache) e extrai metricas + sha256 + dHash de 3 quadros. Sem opiniao estetica: so medidas."""
    f = work / f"{entry['id']}.mp4"
    try:
        if not f.exists():
            f.write_bytes(get(entry["preview"]))
        dur, w, h = probe(f); fr = sample_frames(f)
        if len(fr) < 3:
            return {"error": "poucos_quadros"}
        n = len(fr)
        return {"dur": dur, "w": w, "h": h, "m": metrics_from_frames(fr), "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                "phashes": [dhash(fr[int(n * q)].mean(axis=2)) for q in (0.25, 0.5, 0.75)], "phash": dhash(fr[n // 2].mean(axis=2))}
    except Exception as e:  # noqa
        return {"error": repr(e)[:80]}


# ---------- cache persistente (so medidas; sem midia) ----------
CACHE = ROOT / "data" / "curadoria_cache.json"
LIST_TTL = 14 * 86400


def cache_load():
    return json.loads(CACHE.read_text(encoding="utf8")) if CACHE.exists() else {"listing": {}, "metrics": {}}


def cache_save(c):
    CACHE.parent.mkdir(exist_ok=True); CACHE.write_text(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf8")


def license_check(page_html):
    """Trava de direitos (Mixkit): pagina do clipe precisa citar a licenca gratuita de video. Retorna (ok, evidencia)."""
    h = page_html.lower()
    ok = ("mixkit stock video free license" in h) or ("/license/#videofree" in h) or ("videofree" in h and "license" in h)
    return ok, ("pagina cita 'Stock Video Free License'" if ok else "licenca gratuita NAO localizada na pagina")


def hd_url(vid):
    for q in ("1080", "720"):
        u = f"https://assets.mixkit.co/videos/{vid}/{vid}-{q}.mp4"
        try:
            req = urllib.request.Request(u, headers=dict(UA, Range="bytes=0-1")); urllib.request.urlopen(req, timeout=30).close(); return u
        except Exception:  # noqa
            continue
    return None


def validate_manifest(m):
    """Contrato explicito do manifesto de curadoria (para o pipeline). Retorna lista de erros."""
    e = []
    for k in ("episode", "run_id", "engine_version", "status", "segments", "clips", "reservation_state", "qa"):
        if k not in m:
            e.append(f"falta {k}")
    if m.get("status") == "OK":
        cl = m.get("clips", [])
        if len(cl) < PLAN.MIN_CLIPS: e.append("menos de 12 clipes")
        if len({(c["source"], c["id"]) for c in cl}) != len(cl): e.append("clipe repetido")
        for c in cl:
            for k in ("scene", "source", "id", "page", "license", "license_evidence", "interval", "sha256", "phashes", "justification", "scores", "segment"):
                if k not in c: e.append(f"{c.get('scene')}: falta {k}")
            if not c.get("license_ok"): e.append(f"{c.get('scene')}: licenca nao comprovada")
    return e


ENGINE_VERSION = "vnc-curadoria-2.0"


def run(ep, mode=None):
    mode = mode or os.environ.get("VNC_CURATE_MODE", "select")
    dry = os.environ.get("VNC_CURATE_DRY") == "1"
    as_ep = os.environ.get("VNC_CURATE_AS") or ep   # simulacao: roteiro de `ep` tratado como outro episodio (prova antirrepeticao real)
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    if mode == "confirm":
        print("VNC_MEMORY_CONFIRMED", MEM.confirm(ep)); return 0
    if mode == "release":
        print("VNC_MEMORY_RELEASED", MEM.release(ep, os.environ.get("VNC_RELEASE_RUN", ""))); return 0
    cfg, tpl = PLAN.load_episode(ep)
    led, reg = MEM.load(), json.loads((ROOT / "contracts" / "vnc_clip_registry_v1.json").read_text(encoding="utf8"))
    mf_path = ROOT / "episodes" / f"{as_ep}_curadoria_manifest.json"
    # idempotencia: mesma selecao ja reservada/confirmada para este episodio -> reutiliza
    own = [e for e in led["entries"].values() if e["episode"] == as_ep and e["state"] in MEM.ACTIVE]
    if not dry and mf_path.exists() and len(own) >= PLAN.MIN_CLIPS and os.environ.get("VNC_FORCE_RESELECT") != "1":
        m = json.loads(mf_path.read_text(encoding="utf8"))
        if m.get("status") == "OK" and {(c["source"], str(c["id"])) for c in m["clips"]} <= {(e["source"], e["id"]) for e in own}:
            print("VNC_CURATE_IDEMPOTENT reutilizando selecao reservada", as_ep); return 0
    scene_seconds = None
    plan, diag = PLAN.build_plan(cfg, tpl, scene_seconds)
    manifest = {"episode": as_ep, "run_id": run_id, "engine_version": ENGINE_VERSION, "dry_run": dry, "status": "BLOQUEADO", "segments": plan, "clips": [],
                "reservation_state": "none", "qa": {"diagnostico": diag, "limitacoes_pt": [
                    "sem analise visual multimodal: so metricas objetivas (movimento, brilho, saturacao, nitidez, cortes) + titulo/tags; compreensao do roteiro = plano `visual` escrito pelo Claude",
                    "fonte automatica unica: Mixkit (Coverr bloqueia busca por robots; Pexels exige chave)",
                    "ids legados Coverr/Pexels do E01 sem impressao digital: protegidos so por ID e titulo"]}}
    if diag:
        return _finish(manifest, mf_path, None, dry, 3)
    work = Path("/tmp/curate"); work.mkdir(exist_ok=True)
    cache = cache_load(); t0 = time.time()
    def list_kw(kw):
        slug = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-")
        hit = cache["listing"].get(slug)
        if hit and time.time() - hit["ts"] < LIST_TTL:
            return hit["entries"]
        out = []
        for page in (1, 2):
            try:
                out += parse_listing(get(f"https://mixkit.co/free-stock-video/{slug}/" + (f"?page={page}" if page > 1 else ""), False))
            except Exception as e:  # noqa
                print("VNC_CURATE_WARN listagem", slug, page, repr(e)[:60])
        if out:
            cache["listing"][slug] = {"ts": time.time(), "entries": out}
        time.sleep(2.0)
        return out
    def pool_for(unit, extra_q=()):
        pool = {}
        for k in list(unit["queries"]) + list(extra_q):
            if time.time() - t0 > 600:
                break
            for e in list_kw(k):
                ok, hit = title_ok(e["title"], unit.get("allow", ()), unit.get("avoid", ()))
                if ok and e["id"] not in pool:
                    pool[e["id"]] = dict(e, kw_hit=sum(w in e["title"] for w in unit["prefer"]))
        return pool
    def evaluate(unit, pool, n):
        top = sorted(pool.values(), key=lambda e: -e["kw_hit"])[:n]; need = unit["min_seconds"]; mood = unit["mood"]
        rejected, cands = [], []
        unit_themes = SEL.themes_of(list(unit['queries']) + list(unit['prefer']))
        with ThreadPoolExecutor(8) as ex:
            res = list(ex.map(lambda e: (cache["metrics"].get(e["id"]) if e["id"] in cache["metrics"] and "phashes" in cache["metrics"][e["id"]] else None) or analyse(e, work), top))
        for e, a in zip(top, res):
            if not a or "error" in a:
                rejected.append([e["id"], "erro/inacessivel"]); continue
            cache["metrics"][e["id"]] = a
            why = reject_reason(a["m"], mood, need, a["dur"], a["w"], a["h"])
            th = SEL.theme(e["title"])
            if not why and th and unit_themes and th not in unit_themes and not (unit_themes & {"sky", "cloud"} and th in {"cloud", "sky"}):
                why = f"sem correspondencia narrativa minima (tema '{th}' fora de {sorted(unit_themes)})"
            if not why:
                why = "; ".join(MEM.conflicts({"source": "mixkit", "id": e["id"], "title": e["title"], "sha256": a["sha256"], "phashes": a["phashes"]}, as_ep, led, reg)) or None
                if why: why = "antirrepeticao: " + why
            if why:
                rejected.append([e["id"], why]); continue
            cands.append({"id": e["id"], "source": "mixkit", "title": e["title"], "page": e["page"], "dur": round(a["dur"], 1), "m": a["m"], "phash": a["phash"], "phashes": a["phashes"],
                          "sha256": a["sha256"], "kw_hit": e["kw_hit"], "mood_range": MOODS[mood], "mood_ok": True, "preview": e["preview"]})
        return pick_top([dict(c, score=SEL.unary(c, unit, SEL.weights())) for c in cands], 8), rejected
    by_scene, rej_all, extra = {}, {}, {}
    for unit in plan:
        sid = unit["scene"]
        pool = pool_for(unit)
        cands, rej = evaluate(unit, pool, 30)
        if len(cands) < 3:  # reformulacao automatica: consultas do arco padrao + clima, mais candidatos (1 rodada)
            fb = [q for s in tpl if s["id"] == sid for q in s["queries"]] + [q for t in PLAN.LEX if True for q in t[1] if t[3] == unit["mood"]]
            pool2 = pool_for(unit, fb[:10]); c2, r2 = evaluate(unit, pool2, 45); cands = c2; rej += r2
            print("VNC_CURATE_REFORMULA", sid, "candidatos agora", len(cands))
        by_scene[sid] = cands; rej_all[sid] = rej
        print("VNC_CURATE_SCENE", sid, unit["mood"], unit["interpretation"], "pool", len(pool), "candidatos", len(cands), [c["id"] for c in cands[:6]], "rej", rej[:3], flush=True)
    if not dry:
        cache_save(cache)
    # selecao global + direitos + reserva (com recuperacao: remove so o invalido e reseleciona)
    chosen, util, trace, license_info = None, 0, {}, {}
    for attempt in range(1, 7):
        chosen, util, trace = SEL.select_sequence(plan, by_scene)
        if not chosen:
            manifest["qa"]["bloqueio"] = trace.get("bloqueio"); manifest["qa"]["rejeicoes"] = rej_all
            return _finish(manifest, mf_path, None, dry, 4)
        bad = {}
        for c in chosen:
            if c["id"] in license_info and license_info[c["id"]][0]:
                continue
            try:
                ok, ev = license_check(get(c["page"], False)); hd = hd_url(c["id"]) if ok else None
                license_info[c["id"]] = (ok and bool(hd), ev + ("" if hd else "; arquivo HD inacessivel"), hd)
            except Exception as e:  # noqa
                license_info[c["id"]] = (False, "pagina inacessivel " + repr(e)[:40], None)
            if not license_info[c["id"]][0]:
                bad[c["id"]] = license_info[c["id"]][1]
        if not bad and not dry:
            ok, blocked = MEM.try_reserve(as_ep, run_id, [{"source": "mixkit", "id": c["id"], "scene": u["scene"], "interval": [0, round(min(c["dur"], u["min_seconds"]), 2)], "title": c["title"],
                                                           "page": c["page"], "license": "Mixkit Stock Video Free License", "sha256": c["sha256"], "phashes": c["phashes"], "dur": c["dur"]}
                                                          for c, u in zip(chosen, plan)], reg=reg)
            bad = {k.split(":", 1)[1]: "reserva recusada: " + "; ".join(v) for k, v in blocked.items()}
            manifest["reservation_state"] = "reserved" if ok else "recusada"
        if not bad:
            break
        print("VNC_CURATE_RECUPERA", attempt, "removendo", bad)
        for sid in by_scene:
            by_scene[sid] = [c for c in by_scene[sid] if c["id"] not in bad]
    else:
        manifest["qa"]["bloqueio"] = "limite de tentativas de recuperacao"; return _finish(manifest, mf_path, None, dry, 4)
    clips = []
    for c, u in zip(chosen, plan):
        ok, ev, hd = license_info[c["id"]]
        clips.append({"scene": u["scene"], "source": "mixkit", "id": c["id"], "title": c["title"], "page": c["page"], "preview_url": c["preview"], "hd_url": hd,
                      "license": "Mixkit Stock Video Free License", "license_ok": ok, "license_evidence": ev, "interval": [0, round(min(c["dur"], u["min_seconds"]), 2)], "clip_seconds": c["dur"],
                      "sha256": c["sha256"], "phashes": c["phashes"], "segment": {"start": u["start"], "end": u["end"], "emotion": u["emotion"], "interpretation": u["interpretation"]},
                      "justification": f"clima {u['mood']} (brilho {c['m']['brightness']}), movimento {c['m']['motion']}, palavras-chave {c['kw_hit']}, interpretacao={u['interpretation']}",
                      "scores": {"unary": round(c["score"], 3)}, "metrics": c["m"], "alternatives": [a["id"] for a in by_scene[u["scene"]] if a["id"] != c["id"]][:4]})
    manifest.update({"status": "OK", "clips": clips, "sequence_utility": util, "trace": trace})
    manifest["qa"].update({"clips": len(clips), "distinct": len({c["id"] for c in clips}), "license_all_ok": all(c["license_ok"] for c in clips),
                           "duracao_total_estimada": plan[-1]["end"], "aprovacao_estetica_humana": "NAO_VERIFICADA"})
    errs = validate_manifest(manifest); manifest["qa"]["manifest_errors"] = errs
    if errs:
        manifest["status"] = "BLOQUEADO"
    return _finish(manifest, mf_path, chosen, dry, 0 if not errs else 5)


def _finish(manifest, mf_path, chosen, dry, code):
    out = Path("/tmp/curate_out"); out.mkdir(exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf8")
    if not dry:
        mf_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
        if manifest["status"] == "OK":  # selecao no formato do gate/pipeline + registro (reservado conta como usado)
            sel = {"schema_version": "1.0.0", "project": "verbo-no-chao", "episode_id": manifest["episode"], "kind": "SCENE_CLIP_SELECTION_CURADORIA_AUTOMATICA", "engine_version": ENGINE_VERSION,
                   "run_id": manifest["run_id"], "publication_authorized": False, "master_approved": False, "scope": "DIRECAO_VISUAL_NAO_MASTER_NAO_PUBLICACAO",
                   "clips": [{k: c[k] for k in ("scene", "source", "id", "license", "page", "interval")} | {"preview_seconds": c["clip_seconds"], "note_pt": c["justification"]} for c in manifest["clips"]]}
            (ROOT / "contracts" / f"{manifest['episode'].lower()}_scene_clip_selection.json").write_text(json.dumps(sel, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
            from agents import vnc_gates as G
            reg = G.load_registry(); G.REGISTRY.write_text(json.dumps(G.register(manifest["episode"], sel, reg), ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    print("VNC_CURATE_STATUS", manifest["status"], "clips", len(manifest["clips"]), "dry" if dry else "persistido", "bloqueio:", manifest["qa"].get("bloqueio") or manifest["qa"]["diagnostico"])
    if chosen:
        from PIL import Image, ImageDraw
        tw, th = 240, 135; cols = 6
        sheet = Image.new("RGB", (cols * tw, 2 * th), (12, 12, 14)); d = ImageDraw.Draw(sheet)
        for i, c in enumerate(chosen):
            try:
                f = Path("/tmp/curate") / f"{c['id']}.mp4"
                if not f.exists(): f.write_bytes(get(c["preview"]))
                sheet.paste(thumb(f, c["dur"]), ((i % cols) * tw, (i // cols) * th)); d.text(((i % cols) * tw + 4, (i // cols) * th + 4), f"S{i + 1:02d} {c['id']}", fill=(255, 220, 90))
            except Exception:  # noqa
                pass
        b = io.BytesIO(); sheet.save(b, "JPEG", quality=82); (out / "selecao.jpg").write_bytes(b.getvalue()); sb = base64.b64encode(b.getvalue()).decode()
        for n in range(0, len(sb), 1800):
            print("VNC_CURATE_SHEETB64", n // 1800, sb[n:n + 1800])
    print("VNC_CURATE_JSON", json.dumps({k: manifest[k] for k in ("episode", "status", "reservation_state")} | {"clips": [(c["scene"], c["id"], c["title"]) for c in manifest["clips"]]}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
