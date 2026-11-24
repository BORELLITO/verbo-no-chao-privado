"""VNC -> Facebook (Pagina VERBO NO CHAO, API oficial da Meta). Reusa o segredo IG_TOKEN (mesmo token de usuario/Pagina da Meta).
Modos (run/facebook.json {"mode": ..., "nonce": ...}):
  probe     leitura: permissoes do token, Pagina visivel, se existe token de Pagina (sem imprimir nenhum token).
  listar    leitura: Reels/videos agendados e publicados recentes da Pagina.
  capas     envia a capa (Cloudinary) como thumbnail preferida de reels ja criados. itens: [{episodio, video_id}].
  cancelar  apaga posts agendados ainda nao publicados (itens: [{post_id}]).
  agendar   agenda Reels na Pagina. Exige "liberado_pelo_dono": true e "itens": [{"episodio": "E01", "quando": "2026-11-24T05:00:00-03:00"}].
            Opcional por item: "video_public_id". Nada e publicado sem liberacao explicita; agendar != publicar.
Legenda do Facebook = legenda curta do Instagram sem hashtags extras alem das 5 do pacote (ver legenda())."""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPH = "https://graph.facebook.com/v21.0"
PAGE_ID = "1388285187712035"


class FBError(RuntimeError):
    pass


def _call(method, path, token, params=None, opener=urllib.request.urlopen, base=GRAPH, headers=None):
    params = dict(params or {})
    url = path if path.startswith("http") else f"{base}/{path.lstrip('/')}"
    data = None
    h = {"Authorization": f"Bearer {token}"}
    h.update(headers or {})
    if method == "GET":
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with opener(req, timeout=120) as r:
            return json.loads(r.read().decode("utf8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf8")).get("error", {})
            msg = f"{err.get('type','')} {err.get('code','')}/{err.get('error_subcode','')}: {err.get('message','')}"
        except Exception:
            msg = ""
        raise FBError(f"HTTP {e.code} {msg}"[:500]) from None
    except Exception as e:
        raise FBError(f"falha de rede/JSON: {type(e).__name__}") from None


def token_da_pagina(user_token, opener=urllib.request.urlopen):
    """Devolve (page_id, nome, token_da_pagina|None)."""
    r = _call("GET", "me/accounts", user_token, {"fields": "id,name,access_token,tasks"}, opener)
    for p in r.get("data", []):
        if p["id"] == PAGE_ID:
            return p["id"], p["name"], p.get("access_token"), p.get("tasks", [])
    raise FBError("Pagina " + PAGE_ID + " nao visivel para este token; visiveis: " + json.dumps([(p["id"], p["name"]) for p in r.get("data", [])])[:300])


def probe(token, opener=urllib.request.urlopen):
    perms = _call("GET", "me/permissions", token, {}, opener).get("data", [])
    ok = sorted(p["permission"] for p in perms if p.get("status") == "granted")
    out = {"permissoes": ok}
    try:
        pid, nome, ptok, tasks = token_da_pagina(token, opener)
        out.update({"pagina": nome, "page_id": pid, "tem_token_de_pagina": bool(ptok), "tarefas": tasks})
    except FBError as e:
        out["pagina_erro"] = str(e)
    return out


def montar_urls(ep, item):
    cloud = os.environ["CLOUDINARY_CLOUD_NAME"]
    midia = json.load(open(ROOT / "publicacao/midia_v1.json", encoding="utf8"))
    vid = item.get("video_public_id") or midia["public_ids"][ep]
    cap = midia["capas"].get(ep)
    video = f"https://res.cloudinary.com/{cloud}/video/upload/{vid}.mp4"
    capa = f"https://res.cloudinary.com/{cloud}/image/upload/{cap}.jpg" if cap else None
    return video, capa


def legenda(ep):
    fb = ROOT / "publicacao/facebook_legendas_v1.json"
    if fb.exists():
        d = json.load(open(fb, encoding="utf8"))
        if ep in d:
            return d[ep]["legenda"], "", d[ep]["titulo"]
    pac = json.load(open(ROOT / "publicacao/pacote_v1.json", encoding="utf8"))
    for e in pac["episodios"]:
        if e["id"] == ep:
            return e["legendas"]["instagram"], e["rotulo"], e["titulo"]
    raise FBError(f"episodio {ep} sem pacote")


def epoch(quando):
    d = datetime.fromisoformat(quando)
    if d.tzinfo is None:
        raise FBError("'quando' precisa de fuso (ex.: -03:00)")
    return int(d.astimezone(timezone.utc).timestamp())


def agendar_um(ptoken, item, opener=urllib.request.urlopen, agora=time.time):
    ep, quando = item["episodio"], item["quando"]
    ts = epoch(quando)
    if not (agora() + 600 <= ts <= agora() + 29 * 86400):
        raise FBError(f"{ep}: horario fora da janela da API (10 min a 29 dias a frente): {quando}")
    video, capa = montar_urls(ep, item)
    texto, rotulo, titulo = legenda(ep)
    ini = _call("POST", f"{PAGE_ID}/video_reels", ptoken, {"upload_phase": "start"}, opener)
    vid, up = ini["video_id"], ini["upload_url"]
    _call("POST", up, ptoken, {}, opener, headers={"file_url": video, "Content-Type": "application/octet-stream"})
    params = {"upload_phase": "finish", "video_id": vid, "video_state": "SCHEDULED", "scheduled_publish_time": str(ts),
              "description": texto, "title": titulo}
    fin = _call("POST", f"{PAGE_ID}/video_reels", ptoken, params, opener)
    return {"episodio": f"{rotulo}, {titulo}", "quando": quando, "video_id": vid, "resposta": fin, "video": video, "capa_disponivel": bool(capa)}


def agendar(token, cfg, opener=urllib.request.urlopen):
    if cfg.get("liberado_pelo_dono") is not True:
        raise FBError("BLOQUEADO: falta liberado_pelo_dono=true")
    itens = cfg.get("itens") or []
    if not itens:
        raise FBError("falta 'itens'")
    _, _, ptoken, _ = token_da_pagina(token, opener)
    if not ptoken:
        raise FBError("sem token de Pagina para esta Pagina")
    return [agendar_um(ptoken, it, opener) for it in itens]


def _multipart(campos, arquivo_nome, arquivo_bytes):
    b = "----vnc" + str(int(time.time() * 1000))
    corpo = b""
    for k, v in campos.items():
        corpo += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    corpo += (f"--{b}\r\nContent-Disposition: form-data; name=\"source\"; filename=\"{arquivo_nome}\"\r\n"
              "Content-Type: image/jpeg\r\n\r\n").encode() + arquivo_bytes + f"\r\n--{b}--\r\n".encode()
    return corpo, f"multipart/form-data; boundary={b}"


def capas(token, cfg, opener=urllib.request.urlopen):
    """itens: [{"episodio":"E01","video_id":"<id do reel>"}]. Envia a capa do Cloudinary como thumbnail preferida."""
    if cfg.get("liberado_pelo_dono") is not True:
        raise FBError("BLOQUEADO: falta liberado_pelo_dono=true")
    _, _, ptoken, _ = token_da_pagina(token, opener)
    if not ptoken:
        raise FBError("sem token de Pagina")
    out = []
    for it in cfg.get("itens") or []:
        _, capa = montar_urls(it["episodio"], {"video_public_id": "x"})
        if not capa:
            out.append({"episodio": it["episodio"], "erro": "sem capa no midia_v1"}); continue
        with opener(urllib.request.Request(capa), timeout=60) as r:
            img = r.read()
        corpo, ct = _multipart({"is_preferred": "true"}, "capa.jpg", img)
        req = urllib.request.Request(f"{GRAPH}/{it['video_id']}/thumbnails", data=corpo, method="POST",
                                     headers={"Authorization": f"Bearer {ptoken}", "Content-Type": ct})
        try:
            with opener(req, timeout=120) as r:
                out.append({"episodio": it["episodio"], "video_id": it["video_id"], "resposta": json.loads(r.read().decode() or "{}"), "bytes": len(img)})
        except urllib.error.HTTPError as e:
            out.append({"episodio": it["episodio"], "video_id": it["video_id"], "erro": f"HTTP {e.code} " + e.read().decode("utf8", "ignore")[:300]})
    return out


def cancelar(token, cfg, opener=urllib.request.urlopen):
    """Cancela (apaga) posts AGENDADOS e ainda nao publicados. itens: [{"post_id": "<id de scheduled_posts>"}]. Reversivel so re-agendando."""
    if cfg.get("liberado_pelo_dono") is not True:
        raise FBError("BLOQUEADO: falta liberado_pelo_dono=true")
    _, _, ptoken, _ = token_da_pagina(token, opener)
    if not ptoken:
        raise FBError("sem token de Pagina")
    ag = {p["id"]: p for p in _call("GET", f"{PAGE_ID}/scheduled_posts", ptoken, {"fields": "id,scheduled_publish_time,is_published", "limit": "50"}, opener).get("data", [])}
    out = []
    for it in cfg.get("itens") or []:
        pid = it["post_id"]
        if pid not in ag:
            out.append({"post_id": pid, "erro": "nao esta entre os agendados (ja publicado ou inexistente): nada feito"}); continue
        out.append({"post_id": pid, "resposta": _call("DELETE", pid, ptoken, {}, opener)})
    return out


def listar(token, opener=urllib.request.urlopen):
    _, _, ptoken, _ = token_da_pagina(token, opener)
    if not ptoken:
        raise FBError("sem token de Pagina")
    ag = _call("GET", f"{PAGE_ID}/scheduled_posts", ptoken, {"fields": "id,message,scheduled_publish_time,is_published", "limit": "25"}, opener)
    rd = _call("GET", f"{PAGE_ID}/video_reels", ptoken, {"fields": "id,description,status,permalink_url,created_time", "limit": "10"}, opener)
    return {"agendados": ag.get("data", []), "reels": rd.get("data", [])}


MODOS = ("probe", "listar", "agendar", "capas", "cancelar")  # fonte unica dos modos (o workflow le daqui)


def main(argv=None):
    argv = argv or sys.argv[1:]
    cfg = json.load(open(ROOT / "run/facebook.json", encoding="utf8"))
    mode = argv[0] if argv else cfg.get("mode", "probe")
    token = os.environ.get("IG_TOKEN", "")
    if not token:
        print("IG_TOKEN ausente"); return 2
    try:
        fn = {"probe": lambda: probe(token), "listar": lambda: listar(token), "agendar": lambda: agendar(token, cfg), "capas": lambda: capas(token, cfg), "cancelar": lambda: cancelar(token, cfg)}.get(mode)
        if fn is None:
            print("modo desconhecido"); return 2
        print(json.dumps(fn(), ensure_ascii=False, indent=1))
        return 0
    except FBError as e:
        print("ERRO:", str(e).replace(token, "***")); return 1


if __name__ == "__main__":
    sys.exit(main())
