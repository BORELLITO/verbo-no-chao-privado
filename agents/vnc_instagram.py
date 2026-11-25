"""VNC -> Instagram (API oficial da Meta, Content Publishing). Unico modulo que fala com graph.facebook.com.
Modos (run/instagram.json {"mode": ..., "nonce": ...}):
  probe    leitura: confirma o token (sem imprimi-lo), a Pagina e o ID da conta do Instagram ligada.
  publish  publica 1 Reel COM CAPA. Exige "liberado_pelo_dono": true e "episodio" (ex.: "E06").
           Opcional: "video_public_id" (ex.: copia de audio seguro "vnc/fora1-seguro-...").
           Opcional: "publicar_em" (ISO UTC, ex.: "2026-11-25T15:00:00Z"): o workflow ESPERA ate esse horario e publica sozinho
           (a API do Instagram nao agenda). Comeca ANTECEDENCIA_S antes para o video terminar de processar. Maximo MAX_ESPERA_S.
           Opcional: "dry_run": true = espera e valida mas NAO publica (ensaio).
O token vem de IG_TOKEN (segredo do repo); nunca e impresso. Nada e publicado sem liberacao explicita."""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPH = "https://graph.facebook.com/v21.0"
ROTULO_IA = True  # voz sintetica: rotular como conteudo com IA
ANTECEDENCIA_S = 150  # cria o container e processa o video antes do horario alvo
MAX_ESPERA_S = 5 * 3600 + 30 * 60  # o job do Actions tem teto de 6 h
TOLERANCIA_ATRASO_S = 600  # horario alvo ja passado ha mais que isso = erro (evita publicar velho por engano)


class IGError(RuntimeError):
    pass


def _call(method, path, token, params=None, opener=urllib.request.urlopen):
    params = dict(params or {})
    url = f"{GRAPH}/{path.lstrip('/')}"
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if method == "GET":
        if params:
            url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with opener(req, timeout=120) as r:
            return json.loads(r.read().decode("utf8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf8")).get("error", {})
            msg = f"{err.get('type','')} {err.get('code','')}/{err.get('error_subcode','')}: {err.get('message','')}"
        except Exception:
            msg = ""
        raise IGError(f"HTTP {e.code} {msg}"[:500]) from None
    except Exception as e:
        raise IGError(f"falha de rede/JSON: {type(e).__name__}") from None


def achar_conta(token, opener=urllib.request.urlopen):
    """Devolve (page_id, page_name, ig_id, ig_username)."""
    r = _call("GET", "me/accounts", token, {"fields": "id,name,instagram_business_account{id,username}"}, opener)
    for p in r.get("data", []):
        ig = p.get("instagram_business_account")
        if ig:
            return p["id"], p["name"], ig["id"], ig.get("username")
    raise IGError("nenhuma Pagina com Instagram ligado visivel para este token: " + json.dumps(r.get("data", []))[:300])


def probe(token, opener=urllib.request.urlopen):
    page_id, page_name, ig_id, user = achar_conta(token, opener)
    info = _call("GET", ig_id, token, {"fields": "username,media_count,followers_count"}, opener)
    return {"pagina": page_name, "page_id": page_id, "ig_id": ig_id, "usuario": info.get("username", user),
            "midias": info.get("media_count")}


def montar_urls(ep, cfg):
    cloud = os.environ["CLOUDINARY_CLOUD_NAME"]
    midia = json.load(open(ROOT / "publicacao/midia_v1.json", encoding="utf8"))
    vid = cfg.get("video_public_id") or midia["public_ids"][ep]
    cap = midia["capas"][ep]
    return (f"https://res.cloudinary.com/{cloud}/video/upload/{vid}.mp4",
            f"https://res.cloudinary.com/{cloud}/image/upload/{cap}.jpg")


def legenda(ep):
    pac = json.load(open(ROOT / "publicacao/pacote_v1.json", encoding="utf8"))
    for e in pac["episodios"]:
        if e["id"] == ep:
            return e["legendas"]["instagram"], e["rotulo"], e["titulo"]
    raise IGError(f"episodio {ep} sem pacote")


def publicar(token, cfg, opener=urllib.request.urlopen, sleep=time.sleep):
    if cfg.get("liberado_pelo_dono") is not True:
        raise IGError("BLOQUEADO: falta liberado_pelo_dono=true")
    ep = cfg.get("episodio")
    if not ep:
        raise IGError("falta 'episodio'")
    _, _, ig_id, user = achar_conta(token, opener)
    video, capa = montar_urls(ep, cfg)
    texto, rotulo, titulo = legenda(ep)
    params = {"media_type": "REELS", "video_url": video, "cover_url": capa, "caption": texto, "share_to_feed": "true"}
    if ROTULO_IA:
        params["is_ai_generated"] = "true"
    try:
        c = _call("POST", f"{ig_id}/media", token, params, opener)
    except IGError as e:
        if ROTULO_IA and "is_ai_generated" in str(e):
            raise IGError("rotulo de IA recusado pela API; nao publicado (a regra exige o rotulo): " + str(e)) from None
        raise
    cid = c["id"]
    estado = None
    for _ in range(60):
        st = _call("GET", cid, token, {"fields": "status_code,status"}, opener)
        estado = st.get("status_code")
        print(f"container {cid}: {estado}")
        if estado in ("FINISHED", "ERROR", "EXPIRED"):
            break
        sleep(10)
    if estado != "FINISHED":
        raise IGError(f"container nao ficou pronto: {estado}")
    pub = _call("POST", f"{ig_id}/media_publish", token, {"creation_id": cid}, opener)
    mid = pub["id"]
    info = _call("GET", mid, token, {"fields": "permalink,media_type,media_product_type,thumbnail_url"}, opener)
    return {"episodio": f"{rotulo}, {titulo}", "ig_media_id": mid, "permalink": info.get("permalink"),
            "tipo": info.get("media_product_type"), "capa_enviada": capa}


def espera_s(cfg, agora=None):
    """Funcao pura: segundos a esperar antes de publicar (0 = agora). Valida o horario alvo de "publicar_em"."""
    alvo = cfg.get("publicar_em")
    if not alvo:
        return 0
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(str(alvo).replace("Z", "+00:00"))
    except ValueError:
        raise IGError(f"publicar_em invalido: {alvo!r}") from None
    if t.tzinfo is None:
        raise IGError("publicar_em precisa de fuso (use ...Z)")
    agora = agora or datetime.now(timezone.utc)
    falta = (t - agora).total_seconds() - ANTECEDENCIA_S
    if falta < -TOLERANCIA_ATRASO_S:
        raise IGError(f"publicar_em ja passou ({alvo}); nada publicado")
    if falta > MAX_ESPERA_S:
        raise IGError(f"publicar_em muito distante ({alvo}); empurre o arquivo mais perto do horario")
    return max(0, int(falta))


def main(argv=None):
    argv = argv or sys.argv[1:]
    cfg = json.load(open(ROOT / "run/instagram.json", encoding="utf8"))
    mode = argv[0] if argv else cfg.get("mode", "probe")
    token = os.environ.get("IG_TOKEN", "")
    if not token:
        print("IG_TOKEN ausente"); return 2
    try:
        if mode == "publish":
            if cfg.get("liberado_pelo_dono") is not True:
                raise IGError("BLOQUEADO: falta liberado_pelo_dono=true")
            esp = espera_s(cfg)  # valida ANTES de dormir
            if esp:
                print(f"VNC_IG_AGUARDANDO {esp}s ate publicar_em={cfg['publicar_em']} (antecedencia {ANTECEDENCIA_S}s)", flush=True)
                time.sleep(esp)
            if cfg.get("dry_run") is True:  # ensaio: espera e valida, mas NAO publica
                print("VNC_IG_DRY_RUN_OK espera concluida; nada publicado"); return 0
        out = probe(token) if mode == "probe" else publicar(token, cfg) if mode == "publish" else None
        if out is None:
            print("modo desconhecido"); return 2
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    except IGError as e:
        print("ERRO:", str(e).replace(token, "***")); return 1


if __name__ == "__main__":
    sys.exit(main())
