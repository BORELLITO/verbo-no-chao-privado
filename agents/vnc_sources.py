"""Adaptadores de bancos de clipes da curadoria VNC. Cada fonte: descobrir(kw) -> entradas; direitos(entry) -> (ok, evidencia, url_hd).
Fontes SEM chave (sempre ativas): mixkit, coverr (via sitemap publico + paginas de clipe; robots.txt so veta '?q='), wikimedia (SOMENTE CC0/dominio publico).
Fontes COM chave gratuita (ativas apenas se o segredo existir no GitHub): pexels (PEXELS_API_KEY), pixabay (PIXABAY_API_KEY).
Entrada: {source, id, title, page, preview, hd?, license, origin_id?, size?}. `id` e o mesmo que vai ao registro/memoria (Coverr: 'coverr-<slug>-<n>').
Regras editoriais: nada de IA/premium/animacao; Coverr so aceita id legado 'coverr-<slug>-<numero>' (catalogo de filmagem real); Wikimedia so CC0/PD com >=1280 px.
"""
import json, os, re, time, urllib.parse, urllib.request
from pathlib import Path

LICENSES = {"mixkit": "Mixkit Stock Video Free License", "coverr": "Coverr License (royalty-free, uso comercial)", "pexels": "Pexels License", "pixabay": "Pixabay Content License", "wikimedia": "CC0/Dominio publico (Wikimedia Commons)"}
COVERR_SITEMAP = "https://coverr.co/sitemap/sitemap_videos.xml"
COVERR_ID = re.compile(r"cdn\.coverr\.co/videos/(coverr-[a-z0-9-]+-\d+)/")
COVERR_DENY = ("user-ai", "ai-generation", "-temp-", "coverr-temp", "premium", "sponsored", "mp4-")   # sonda: paginas de IA tem player 'user-ai-generation-*' ou 'coverr-temp-*mp4-N'; 'premium' = Coverr+ (preview com marca d'agua)
COVERR_LICENSE_URL = "https://coverr.co/license"
STOP = {"a", "an", "the", "of", "on", "in", "at", "with", "and", "to", "from", "for"}
CC0_OK = {"cc0", "cc0 1.0", "public domain", "pd", "pdm"}


def enabled(env=None):
    env = os.environ if env is None else env
    out = ["mixkit", "wikimedia"]   # Coverr DESATIVADO (decisao do dono 2026-11-21: canal monetizado; termos da API gratuita vetam uso comercial). Codigo mantido so p/ protecao antirrepeticao dos clipes legados do E01
    if env.get("PEXELS_API_KEY"): out.append("pexels")
    if env.get("PIXABAY_API_KEY"): out.append("pixabay")
    return out


# ---------- funcoes puras (testaveis com fixtures) ----------
def slug_words(slug, drop_hash=False):
    ws = [w for w in slug.split("-") if w and w not in STOP]
    if drop_hash and ws and re.fullmatch(r"[a-z0-9]{10}", ws[-1]):
        ws = ws[:-1]   # sufixo-hash de 10 caracteres do sitemap (tentado so na comparacao com o id do CDN)
    return ws


def coverr_match(slugs, kw, k=25):
    """Busca por titulo no catalogo (slugs do sitemap): consulta 'dark-clouds' casa slugs com dark e/ou clouds (prefixo p/ plural). Retorna [(slug, score)]."""
    toks = [t for t in re.split(r"[-\s]+", kw.lower()) if t and t not in STOP]
    out = []
    for sl in slugs:
        ws = slug_words(sl)
        sc = sum(any(w == t or w.startswith(t) or t.startswith(w) and len(w) > 3 for w in ws) for t in toks)
        if sc:
            out.append((sl, sc))
    return sorted(out, key=lambda x: (-x[1], len(x[0])))[:k]


def coverr_resolve(page_html, slug):
    """Id do CDN do PROPRIO clipe (a pagina lista tambem relacionados): exige coincidencia de titulo e sufixo numerico (catalogo legado = filmagem real)."""
    wants = {"-".join(slug_words(slug)), "-".join(slug_words(slug, True))}
    for cid in dict.fromkeys(COVERR_ID.findall(page_html)):
        if any(d in cid for d in COVERR_DENY):
            continue
        have = "-".join(w for w in cid[len("coverr-"):].rsplit("-", 1)[0].split("-") if w and w not in STOP)
        if have in wants:
            return cid
    return None


def commons_entries(api_json, min_w=1280):
    """Resposta da API do Commons -> so videos com licenca sem atribuicao (CC0/PD) e largura >= min_w."""
    out = []
    for p in (api_json.get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]; lic = (ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value") or "").strip().lower()
        if lic not in CC0_OK or (ii.get("width") or 0) < min_w or not ii.get("url"):
            continue
        t = re.sub(r"^File:|\.(webm|ogv|ogg|mp4)$", "", p["title"], flags=re.I)
        out.append({"source": "wikimedia", "id": f"commons-{p['pageid']}", "title": t.replace("_", " ").lower(), "page": ii.get("descriptionurl") or "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(p["title"]),
                    "preview": ii["url"], "hd": ii["url"], "license": LICENSES["wikimedia"], "size": ii.get("size"), "license_raw": lic})
    return out


def pexels_entries(api_json):
    out = []
    for v in api_json.get("videos", []):
        if v.get("width", 0) < v.get("height", 1):
            continue
        files = sorted([f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")], key=lambda f: f["width"])
        if not files:
            continue
        prev = next((f for f in files if f["width"] >= 640), files[0]); hd = next((f for f in reversed(files) if f["width"] <= 1920), files[-1])
        slug = (v.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
        out.append({"source": "pexels", "id": str(v["id"]), "title": re.sub(r"-\d+$", "", slug).replace("-", " "), "page": v.get("url"), "preview": prev["link"], "hd": hd["link"], "license": LICENSES["pexels"], "duration": v.get("duration")})
    return out


def pixabay_entries(api_json):
    out = []
    for h in api_json.get("hits", []):
        if h.get("type") not in (None, "film"):
            continue  # exclui animacao
        vs = h.get("videos", {}); prev = next((vs[k]["url"] for k in ("tiny", "small") if (vs.get(k) or {}).get("url")), None); hd = next((vs[k]["url"] for k in ("large", "medium") if (vs.get(k) or {}).get("url")), None)  # doc: large pode vir vazio
        if not prev or not hd:
            continue
        out.append({"source": "pixabay", "id": str(h["id"]), "title": (h.get("tags") or "").replace(",", " ").lower(), "page": h.get("pageURL"), "preview": prev, "hd": hd, "license": LICENSES["pixabay"], "duration": h.get("duration")})
    return out


def coverr_license(get, ctx=None):
    """Baixa e confere os termos da licenca Coverr na execucao (1x). Exige: gratuito/comercial para o acervo de estoque e secao de conteudo patrocinado/premium (as excecoes que o motor veta por clipe)."""
    import hashlib
    try:
        raw = get(COVERR_LICENSE_URL, False, limit=6_000_000)
    except Exception as e:  # noqa
        return {"ok": False, "why": repr(e)[:60], "sha": ""}
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", "", raw, flags=re.S))).lower()
    ok = "free for commercial" in t and "sponsored content" in t and "premium content" in t
    return {"ok": ok, "why": "" if ok else "frases-chave ausentes", "sha": hashlib.sha256(t.encode()).hexdigest()}


PEXELS_KEYS = {"videos", "page", "per_page"}
PIXABAY_KEYS = {"hits", "total"}


def schema_check(source, j):
    """Autoteste de contrato contra a DOCUMENTACAO oficial (Pexels /v1/videos/search; Pixabay /api/videos/). Divergencia = erro explicito (nada de adivinhar formato)."""
    need = PEXELS_KEYS if source == "pexels" else PIXABAY_KEYS
    miss = need - set(j)
    if miss:
        raise ValueError(f"{source}: resposta fora do contrato documentado (faltam {sorted(miss)})")
    items = j.get("videos" if source == "pexels" else "hits", [])
    if items:
        need_i = {"id", "video_files", "width", "height", "url"} if source == "pexels" else {"id", "pageURL", "tags", "videos"}
        m2 = need_i - set(items[0])
        if m2:
            raise ValueError(f"{source}: item fora do contrato documentado (faltam {sorted(m2)})")


# ---------- descoberta (rede) ----------
def discover(source, kw, ctx):
    """Falha de uma fonte nunca derruba a curadoria: registra aviso e segue com as demais."""
    try:
        return _discover(source, kw, ctx)
    except Exception as e:  # noqa
        print("VNC_CURATE_WARN fonte", source, kw, repr(e)[:80]); return []


def _discover(source, kw, ctx):
    """ctx: {get(url,binary,..), cache(dict), env, sleep}. Retorna lista de entradas."""
    get, cache = ctx["get"], ctx["cache"]; env = ctx.get("env", os.environ); slug = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-")
    if source == "mixkit":
        from agents.vnc_curate import parse_listing
        out = []
        for page in (1, 2):
            try:
                out += [dict(e, source="mixkit", license=LICENSES["mixkit"]) for e in parse_listing(get(f"https://mixkit.co/free-stock-video/{slug}/" + (f"?page={page}" if page > 1 else ""), False))]
            except Exception as e:  # noqa
                print("VNC_CURATE_WARN mixkit", slug, page, repr(e)[:50])
        return out
    if source == "coverr":
        idx = cache.setdefault("coverr_index", {})
        if not idx.get("slugs") or time.time() - idx.get("ts", 0) > 7 * 86400:
            xml = get(COVERR_SITEMAP, False, limit=60_000_000, timeout=120)
            idx["slugs"] = [u.rsplit("/", 1)[-1] for u in re.findall(r"<loc>([^<]+/videos/[^<]+)</loc>", xml)]; idx["ts"] = time.time()
        ids = cache.setdefault("coverr_ids", {}); out = []; fetched = 0
        for sl, sc in coverr_match(idx["slugs"], kw, 14):
            cid = ids.get(sl)
            if cid is None and fetched < 14 and ctx["budget"]["coverr"] > 0:
                ctx["budget"]["coverr"] -= 1; fetched += 1
                try:
                    cid = coverr_resolve(get(f"https://coverr.co/videos/{sl}", False, limit=6_000_000), sl) or ""
                except Exception as e:  # noqa
                    cid = None; print("VNC_CURATE_WARN coverr", sl, repr(e)[:50])
                if cid is not None:
                    ids[sl] = cid
                ctx["sleep"](0.7)
            if cid:
                out.append({"source": "coverr", "id": cid, "title": " ".join(slug_words(sl, True)), "page": f"https://coverr.co/videos/{sl}", "preview": f"https://cdn.coverr.co/videos/{cid}/360p.mp4",
                            "hd": f"https://cdn.coverr.co/videos/{cid}/1080p.mp4", "license": LICENSES["coverr"]})
        return out
    if source == "wikimedia":
        q = urllib.parse.quote(f"{kw.replace('-', ' ')} filetype:video")
        try:
            j = json.loads(get("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6&gsrlimit=30&prop=imageinfo&iiprop=url|size|extmetadata&iiextmetadatafilter=LicenseShortName&gsrsearch=" + q, False))
            return [e for e in commons_entries(j) if (e.get("size") or 0) <= 24_000_000]
        except Exception as e:  # noqa
            print("VNC_CURATE_WARN wikimedia", kw, repr(e)[:50]); return []
    if source == "pexels":
        req = urllib.request.Request(f"https://api.pexels.com/v1/videos/search?orientation=landscape&size=medium&per_page=40&query={urllib.parse.quote(kw.replace('-', ' '))}", headers={"Authorization": env["PEXELS_API_KEY"], "User-Agent": "vnc-curadoria"})
        if ctx["budget"].get("pexels", 0) <= 0:
            return []
        ctx["budget"]["pexels"] -= 1   # API: 200 req/h
        try:
            j = json.loads(urllib.request.urlopen(req, timeout=40).read()); schema_check("pexels", j)
            return pexels_entries(j)
        except Exception as e:  # noqa
            print("VNC_CURATE_WARN pexels", kw, repr(e)[:50]); return []
    if source == "pixabay":
        if ctx["budget"].get("pixabay", 0) <= 0:
            return []
        ctx["budget"]["pixabay"] -= 1  # API: 100 req/60 s; respostas ficam em cache (listing) por >=24 h
        try:
            j = json.loads(get(f"https://pixabay.com/api/videos/?key={env['PIXABAY_API_KEY']}&video_type=film&per_page=40&safesearch=true&q={urllib.parse.quote(kw.replace('-', ' '))}", False)); schema_check("pixabay", j)
            return pixabay_entries(j)
        except Exception as e:  # noqa
            print("VNC_CURATE_WARN pixabay", kw, repr(e)[:50]); return []
    return []


def rights(entry, ctx):
    """Trava de direitos por clipe. Retorna (ok, evidencia, url_hd)."""
    get, s = ctx["get"], entry["source"]
    try:
        if s == "mixkit":
            from agents.vnc_curate import license_check, hd_url
            ok, ev = license_check(get(entry["page"], False)); hd = hd_url(entry["id"]) if ok else None
            return ok and bool(hd), ev + ("" if hd else "; HD inacessivel"), hd
        if s == "coverr":
            html = get(entry["page"], False, limit=6_000_000)
            own = coverr_resolve(html, entry["page"].rsplit("/", 1)[-1]) == entry["id"]
            text = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", "", html, flags=re.S))
            if re.search(r"sponsored by", text, re.I):
                return False, "pagina marca 'Sponsored by' (parceiro pago, fora da licenca Coverr)", None
            lic = ctx.setdefault("coverr_license", coverr_license(get, ctx))
            if not lic["ok"]:
                return False, "termos da licenca Coverr nao conferem: " + lic["why"], None
            if not own:
                return False, "id do CDN nao confere com a pagina ou e IA/premium/temporario", None
            req = urllib.request.Request(entry["hd"], headers=dict(ctx.get("ua", {}), Range="bytes=0-1")); urllib.request.urlopen(req, timeout=30).close()
            return True, (f"por clipe: id legado '{entry['id']}' (nao premium/IA/temporario), pagina sem 'Sponsored by', HD sem marca d'agua acessivel; termos {COVERR_LICENSE_URL} "
                          f"conferidos hoje (sha256 {lic['sha'][:12]}): estoque gratuito, uso comercial, sem atribuicao"), entry["hd"]
        if s == "wikimedia":
            return entry.get("license_raw") in CC0_OK, f"extmetadata do Commons: {entry.get('license_raw')}", entry["hd"]
        if s in ("pexels", "pixabay"):
            req = urllib.request.Request(entry["hd"], headers=dict(ctx.get("ua", {}), Range="bytes=0-1")); urllib.request.urlopen(req, timeout=30).close()
            return True, f"origem: API oficial autenticada ({s}); licenca {LICENSES[s]}", entry["hd"]
    except Exception as e:  # noqa
        return False, "falha na verificacao: " + repr(e)[:60], None
    return False, "fonte desconhecida", None
