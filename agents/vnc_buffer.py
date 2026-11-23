"""VNC -> Buffer (agendador). Unico modulo autorizado a falar com api.buffer.com (autorizacao do dono em 2026-11-22: 'vamos integrar o que for necessario').
Modos (run/buffer.json {"mode": ..., "nonce": ...}):
  probe      leitura: lista organizacao e canais conectados (confirma chave e quais redes estao ligadas).
  introspect leitura: campos aceitos por createPost (titulo do YouTube, metadados por rede).
  dry        monta os pedidos de agendamento do calendario e IMPRIME; nao envia nada.
  schedule   BLOQUEADO ate haver hospedagem publica da midia + liberacao do dono (ver agendar()).
A chave vem de BUFFER_API_KEY (segredo do repo); nunca e impressa."""
import datetime as dt, json, os, sys, urllib.request, urllib.error
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://api.buffer.com"
BRT = ZoneInfo("America/Sao_Paulo")
# DECISAO DO DONO PENDENTE: a voz e sintetica (ElevenLabs). True = rotula como conteudo com IA nas 3 redes (padrao conservador). Imagens sao filmagens reais.
ROTULO_IA = True
YOUTUBE_CATEGORIA = "22"  # People & Blogs (Buffer exige categoria no YouTube)
SERVICOS = {"tiktok": "tiktok", "instagram": "instagram", "youtube": "youtube"}


class BufferError(RuntimeError):
    pass


def gql(query, key, variables=None, opener=urllib.request.urlopen):
    """Uma chamada GraphQL. Nunca inclui a chave em mensagens de erro."""
    if not key:
        raise BufferError("BUFFER_API_KEY ausente")
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with opener(req, timeout=60) as r:
            out = json.loads(r.read().decode("utf8"))
    except urllib.error.HTTPError as e:
        raise BufferError(f"HTTP {e.code} da Buffer") from None
    except Exception as e:
        raise BufferError(f"falha de rede/JSON: {type(e).__name__}") from None
    if out.get("errors"):
        raise BufferError("erro GraphQL: " + "; ".join(str(x.get("message", x)) for x in out["errors"])[:400])
    return out["data"]


def probe(key, opener=urllib.request.urlopen):
    orgs = gql("query { account { organizations { id name } } }", key, opener=opener)["account"]["organizations"]
    res = []
    for o in orgs:
        ch = gql("query($o:OrganizationId!){ channels(input:{organizationId:$o}){ id name service } }", key, {"o": o["id"]}, opener)["channels"]
        res.append({"organizacao": o["name"], "organizationId": o["id"], "canais": ch})
    return res


def introspect(key, opener=urllib.request.urlopen):
    q = 'query { __type(name:"CreatePostInput"){ inputFields { name type { name kind ofType { name kind } } } } }'
    return gql(q, key, opener=opener)


def _unwrap(t):
    while t and t.get("ofType"):
        t = t["ofType"]
    return t or {}


def introspect_deep(key, raiz=("PostInputMetaData", "ShareMode", "SchedulingType"), opener=urllib.request.urlopen, max_tipos=40):
    """Le (so leitura) os tipos de entrada a partir de 'raiz', seguindo INPUT_OBJECT aninhados; enums trazem os valores."""
    q = ("query($n:String!){ __type(name:$n){ kind name enumValues{name} "
         "inputFields{ name type{ name kind ofType{ name kind ofType{ name kind ofType{ name kind } } } } } } }")
    fila, vistos, out = list(raiz), set(), {}
    while fila and len(out) < max_tipos:
        n = fila.pop(0)
        if n in vistos:
            continue
        vistos.add(n)
        t = gql(q, key, {"n": n}, opener)["__type"]
        if not t:
            continue
        if t["kind"] == "ENUM":
            out[n] = [v["name"] for v in t["enumValues"]]
        elif t["kind"] == "INPUT_OBJECT":
            out[n] = {}
            for f in t["inputFields"]:
                u = _unwrap(f["type"]); out[n][f["name"]] = u.get("name")
                if u.get("kind") in ("INPUT_OBJECT", "ENUM"):
                    fila.append(u["name"])
    return out


def introspect_query(key, opener=urllib.request.urlopen, nomes=("PostsResults", "PostMetric", "PostsFiltersInput", "PostsInput")):
    """Somente leitura: campos da raiz Query (com argumentos) e dos tipos Post/PostsInput, para montar a leitura da fila."""
    q = ("query($n:String!){ __type(name:$n){ kind name fields{ name args{ name type{ name kind ofType{ name kind ofType{ name kind } } } } "
         "type{ name kind ofType{ name kind ofType{ name kind } } } } inputFields{ name type{ name kind ofType{ name kind } } } enumValues{name} possibleTypes{ name } } }")
    out = {}
    for n in nomes:
        t = gql(q, key, {"n": n}, opener)["__type"]
        if not t:
            continue
        if t.get("fields"):
            out[n] = {f["name"]: {"args": {a["name"]: _unwrap(a["type"]).get("name") for a in f["args"]}, "tipo": _unwrap(f["type"]).get("name")} for f in t["fields"]}
        elif t.get("inputFields"):
            out[n] = {f["name"]: _unwrap(f["type"]).get("name") for f in t["inputFields"]}
        elif t.get("enumValues"):
            out[n] = [v["name"] for v in t["enumValues"]]
        elif t.get("possibleTypes"):
            out[n] = {"uniao": [v["name"] for v in t["possibleTypes"]]}
    return out


def fila(key, agora=None, opener=urllib.request.urlopen):
    """Somente leitura: posts do Buffer por rede e estado, estoque agendado (dias a frente) e metricas dos enviados."""
    agora = agora or dt.datetime.now(dt.timezone.utc)
    q = ("query($o:OrganizationId!,$a:String){ posts(first:100, after:$a, input:{organizationId:$o, filter:{status:[scheduled,sent,error,needs_approval,draft]}}){ "
         "edges{ node{ id status channelService dueAt sentAt externalLink metrics{ name value } error{ message } } } pageInfo{ hasNextPage endCursor } } }")
    res = {}
    for org in probe(key, opener):
        after = None
        for _ in range(10):
            r = gql(q, key, {"o": org["organizationId"], "a": after}, opener)["posts"]
            for e in r["edges"]:
                n = e["node"]
                x = res.setdefault(n["channelService"], {"agendados": 0, "enviados": 0, "erros": 0, "rascunhos": 0, "ultimo_agendado": None, "enviados_detalhe": []})
                if n["status"] == "scheduled":
                    x["agendados"] += 1
                    if n["dueAt"] and (x["ultimo_agendado"] is None or n["dueAt"] > x["ultimo_agendado"]):
                        x["ultimo_agendado"] = n["dueAt"]
                elif n["status"] == "sent":
                    x["enviados"] += 1
                    x["enviados_detalhe"].append({"sentAt": n["sentAt"], "link": n["externalLink"], "metricas": {m["name"]: m["value"] for m in (n["metrics"] or [])}})
                elif n["status"] == "error":
                    x["erros"] += 1
                else:
                    x["rascunhos"] += 1
            if not r["pageInfo"]["hasNextPage"]:
                break
            after = r["pageInfo"]["endCursor"]
    for x in res.values():
        u = x["ultimo_agendado"]
        x["dias_de_estoque"] = round(max(0.0, (dt.datetime.fromisoformat(u.replace("Z", "+00:00")) - agora).total_seconds() / 86400), 1) if u else 0.0
    return res


def due_utc(brt_str):
    """'2026-11-23 12:00' (Brasilia) -> '2026-11-23T15:00:00.000Z'."""
    d = dt.datetime.strptime(brt_str, "%Y-%m-%d %H:%M").replace(tzinfo=BRT)
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def metadados(rede, titulo_youtube):
    if rede == "youtube":
        return {"youtube": {"title": titulo_youtube, "categoryId": YOUTUBE_CATEGORIA, "privacy": "public", "madeForKids": False, "notifySubscribers": False, "isAiGenerated": ROTULO_IA}}
    if rede == "instagram":
        return {"instagram": {"type": "reel", "shouldShareToFeed": True, "isAiGenerated": ROTULO_IA}}
    return {"tiktok": {"isAiGenerated": ROTULO_IA}}


def montar_pedidos(pacote, canais, media_url_de):
    """Um pedido por episodio x rede. canais: {'tiktok': channelId, ...}. media_url_de(ep_id)->URL publica do mp4."""
    out = []
    for e in pacote["episodios"]:
        for rede, cid in canais.items():
            if e["plataformas"][rede]["estado"] != "nao_agendado":
                continue
            leg = e["legendas"]
            texto = {"tiktok": leg["tiktok"], "instagram": leg["instagram"], "youtube": leg["youtube_descricao"]}[rede]
            out.append({"episodio": e["id"], "rede": rede, "input": {
                "text": texto, "channelId": cid, "schedulingType": "automatic", "mode": "customScheduled", "needsApproval": False,
                "dueAt": due_utc(e["sugestao_horario_brt"]),
                "metadata": metadados(rede, leg["youtube_titulo"]),
                "assets": [{"video": {"url": media_url_de(e["id"])}}]},
                })
    return out


CRIAR = ("mutation($i: CreatePostInput!){ createPost(input:$i){ __typename "
         "... on PostActionSuccess { post { id status dueAt channelService } } ... on MutationError { message } } }")


def canais_por_rede(key, opener=urllib.request.urlopen):
    res = {}
    for org in probe(key, opener):
        for c in org["canais"]:
            res[str(c["service"]).lower()] = c["id"]
    return {r: res[r] for r in SERVICOS if r in res}


def existentes(key, opener=urllib.request.urlopen, com_rascunho=True):
    """(rede, dueAt) de posts ja criados (agendados, rascunhos, enviados): evita duplicar ao repetir um run."""
    q = ("query($o:OrganizationId!,$a:String){ posts(first:100, after:$a, input:{organizationId:$o, filter:{status:[%s]}}){ "
         "edges{ node{ channelService dueAt } } pageInfo{ hasNextPage endCursor } } }") % ("scheduled,draft,needs_approval,sending,sent" if com_rascunho else "scheduled,needs_approval,sending,sent")
    vistos = set()
    for org in probe(key, opener):
        after = None
        for _ in range(10):
            r = gql(q, key, {"o": org["organizationId"], "a": after}, opener)["posts"]
            vistos |= {(str(e["node"]["channelService"]).lower(), e["node"]["dueAt"]) for e in r["edges"]}
            if not r["pageInfo"]["hasNextPage"]:
                break
            after = r["pageInfo"]["endCursor"]
    return vistos


def _apagar_por_status(key, status, opener=urllib.request.urlopen):
    """Apaga SOMENTE posts com o status pedido (draft ou scheduled). Enviados e em envio nunca sao tocados."""
    assert status in ("draft", "scheduled")
    q = ("query($o:OrganizationId!){ posts(first:100, input:{organizationId:$o, filter:{status:[%s]}}){ edges{ node{ id status channelService dueAt } } } }") % status
    apagados = []
    for org in probe(key, opener):
        for e in gql(q, key, {"o": org["organizationId"]}, opener)["posts"]["edges"]:
            n = e["node"]
            if n["status"] != status:
                continue
            r = gql("mutation($i: DeletePostInput!){ deletePost(input:$i){ __typename ... on VoidMutationError { message } } }", key, {"i": {"id": n["id"]}}, opener)["deletePost"]
            if r.get("__typename") != "DeletePostSuccess":
                raise BufferError(f"deletePost recusado: {r.get('message') or r}")
            apagados.append(f"{n['id']}|{str(n.get('channelService')).lower()}|{n.get('dueAt')}" if status == "scheduled" else n["id"])
    return apagados


def limpar_rascunhos(key, opener=urllib.request.urlopen):
    """Apaga SOMENTE rascunhos (draft)."""
    return _apagar_por_status(key, "draft", opener)


def conferir_posts(key, opener=urllib.request.urlopen):
    """Somente leitura: texto e configuracoes (metadata) dos posts enviados e agendados, para conferir o que foi realmente enviado."""
    q = ("query($o:OrganizationId!){ posts(first:30, input:{organizationId:$o, filter:{status:[sent, scheduled]}}){ edges{ node{ id status channelService dueAt sentAt text "
         "metadata{ __typename ... on YoutubePostMetadata{ title privacy madeForKids notifySubscribers isAiGenerated type } "
         "... on InstagramPostMetadata{ type shouldShareToFeed isAiGenerated firstComment } } } } } }")
    saida = []
    for org in probe(key, opener):
        for e in gql(q, key, {"o": org["organizationId"]}, opener)["posts"]["edges"]:
            n = e["node"]
            saida.append({"rede": str(n.get("channelService")).lower(), "status": n.get("status"), "dueAt": n.get("dueAt"), "sentAt": n.get("sentAt"), "texto": n.get("text"), "meta": n.get("metadata")})
    return saida


def cancelar_agendados(key, opener=urllib.request.urlopen):
    """Apaga SOMENTE posts agendados (scheduled). Exige liberacao do dono no modo principal."""
    return _apagar_por_status(key, "scheduled", opener)


def agendar(key, pedidos, rascunho, opener=urllib.request.urlopen):
    """Cria os posts no Buffer. rascunho=True -> saveToDraft (nada sera publicado). Para no primeiro erro; devolve o que foi criado."""
    if not key:
        raise BufferError("BUFFER_API_KEY ausente")
    feitos = []
    for p in pedidos:
        entrada = dict(p["input"])
        if rascunho:
            entrada["saveToDraft"] = True
        r = gql(CRIAR, key, {"i": entrada}, opener)["createPost"]
        if r.get("__typename") != "PostActionSuccess":
            raise BufferError(f"createPost recusado ({p['episodio']}/{p['rede']}): {r.get('message') or r}")
        feitos.append({"episodio": p["episodio"], "rede": p["rede"], "post": r["post"]})
    return feitos


def main(argv):
    mode = argv[0] if argv else json.loads((ROOT / "run/buffer.json").read_text(encoding="utf8")).get("mode", "probe")
    key = os.environ.get("BUFFER_API_KEY", "")
    if mode == "probe":
        print("VNC_BUFFER_PROBE " + json.dumps(probe(key), ensure_ascii=False))
    elif mode == "introspect":
        print("VNC_BUFFER_SCHEMA " + json.dumps(introspect(key), ensure_ascii=False))
    elif mode == "introspect_deep":
        print("VNC_BUFFER_SCHEMA_DEEP " + json.dumps(introspect_deep(key), ensure_ascii=False))
    elif mode == "introspect_query":
        nomes = json.loads((ROOT / "run/buffer.json").read_text(encoding="utf8")).get("tipos") or ["PostsResults"]
        print("VNC_BUFFER_SCHEMA_QUERY " + json.dumps(introspect_query(key, nomes=tuple(nomes)), ensure_ascii=False))
    elif mode == "limpar_rascunhos":
        print("VNC_BUFFER_APAGADOS " + json.dumps(limpar_rascunhos(key)))
    elif mode == "conferir_posts":
        print("VNC_BUFFER_CONFERIR " + json.dumps(conferir_posts(key), ensure_ascii=False))
    elif mode == "cancelar_agendados":
        cfg = json.loads((ROOT / "run/buffer.json").read_text(encoding="utf8"))
        if cfg.get("liberado_pelo_dono") is not True:
            raise BufferError("cancelar_agendados exige liberado_pelo_dono=true no run/buffer.json")
        print("VNC_BUFFER_CANCELADOS " + json.dumps(cancelar_agendados(key)))
    elif mode == "fila":
        print("VNC_BUFFER_FILA " + json.dumps(fila(key), ensure_ascii=False))
    elif mode == "dry":
        pk = json.loads((ROOT / "publicacao/pacote_v1.json").read_text(encoding="utf8"))
        canais = {r: f"<channelId {r}>" for r in SERVICOS}
        for p in montar_pedidos(pk, canais, lambda ep: f"<URL publica do mp4 {ep}>"):
            print("VNC_BUFFER_DRY " + json.dumps(p, ensure_ascii=False))
    elif mode in ("draft", "schedule"):
        cfg = json.loads((ROOT / "run/buffer.json").read_text(encoding="utf8"))
        eps = set(cfg.get("episodes") or [])
        if not eps:
            raise BufferError(f"{mode}: lista 'episodes' obrigatoria")
        if mode == "schedule" and cfg.get("liberado_pelo_dono") is not True:
            raise BufferError("schedule exige liberado_pelo_dono=true no run/buffer.json")
        cloud = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
        pids = json.loads((ROOT / "publicacao/midia_v1.json").read_text(encoding="utf8"))["public_ids"]
        if not cloud or not eps <= set(pids):
            raise BufferError("midia publica ausente para algum episodio (rode vnc-media upload)")
        pk = json.loads((ROOT / "publicacao/pacote_v1.json").read_text(encoding="utf8"))
        pk["episodios"] = [e for e in pk["episodios"] if e["id"] in eps]
        redes = set(cfg.get("redes") or SERVICOS)
        canais = {r: c for r, c in canais_por_rede(key).items() if r in redes}
        ja = existentes(key, com_rascunho=(mode == "draft"))
        pedidos = [p for p in montar_pedidos(pk, canais, lambda ep: f"https://res.cloudinary.com/{cloud}/video/upload/{pids[ep]}.mp4")
                   if (p["rede"], p["input"]["dueAt"]) not in ja]
        print(f"VNC_BUFFER_PLANO modo={mode} pedidos={len(pedidos)} ja_existentes={len(ja)}")
        print("VNC_BUFFER_CRIADOS " + json.dumps(agendar(key, pedidos, rascunho=(mode == "draft")), ensure_ascii=False))
    else:
        raise BufferError(f"modo invalido: {mode}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except BufferError as e:
        print(f"VNC_BUFFER_ERRO {e}"); sys.exit(1)
