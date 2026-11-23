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


def introspect_query(key, opener=urllib.request.urlopen):
    """Somente leitura: campos da raiz Query (com argumentos) e dos tipos Post/PostsInput, para montar a leitura da fila."""
    q = ("query($n:String!){ __type(name:$n){ kind name fields{ name args{ name type{ name kind ofType{ name kind ofType{ name kind } } } } "
         "type{ name kind ofType{ name kind ofType{ name kind } } } } inputFields{ name type{ name kind ofType{ name kind } } } enumValues{name} } }")
    out = {}
    for n in ("Query", "Post", "PostsInput", "PostsFiltersInput", "PostStatus"):
        t = gql(q, key, {"n": n}, opener)["__type"]
        if not t:
            continue
        if t.get("fields"):
            out[n] = {f["name"]: {"args": {a["name"]: _unwrap(a["type"]).get("name") for a in f["args"]}, "tipo": _unwrap(f["type"]).get("name")} for f in t["fields"]}
        elif t.get("inputFields"):
            out[n] = {f["name"]: _unwrap(f["type"]).get("name") for f in t["inputFields"]}
        elif t.get("enumValues"):
            out[n] = [v["name"] for v in t["enumValues"]]
    return out


def due_utc(brt_str):
    """'2026-11-23 12:00' (Brasilia) -> '2026-11-23T15:00:00.000Z'."""
    d = dt.datetime.strptime(brt_str, "%Y-%m-%d %H:%M").replace(tzinfo=BRT)
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def metadados(rede, titulo_youtube):
    if rede == "youtube":
        return {"youtube": {"title": titulo_youtube, "privacy": "public", "madeForKids": False, "notifySubscribers": True, "isAiGenerated": ROTULO_IA}}
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


def agendar(*a, **k):
    raise BufferError("schedule BLOQUEADO: falta hospedagem publica da midia e liberacao explicita do dono")


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
        print("VNC_BUFFER_SCHEMA_QUERY " + json.dumps(introspect_query(key), ensure_ascii=False))
    elif mode == "dry":
        pk = json.loads((ROOT / "publicacao/pacote_v1.json").read_text(encoding="utf8"))
        canais = {r: f"<channelId {r}>" for r in SERVICOS}
        for p in montar_pedidos(pk, canais, lambda ep: f"<URL publica do mp4 {ep}>"):
            print("VNC_BUFFER_DRY " + json.dumps(p, ensure_ascii=False))
    elif mode == "schedule":
        agendar()
    else:
        raise BufferError(f"modo invalido: {mode}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except BufferError as e:
        print(f"VNC_BUFFER_ERRO {e}"); sys.exit(1)
