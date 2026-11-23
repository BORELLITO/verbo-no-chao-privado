"""VNC -> hospedagem publica da midia (Cloudinary, plano gratis) para o Buffer buscar o mp4.
Unico modulo que fala com api.cloudinary.com / res.cloudinary.com. NAO publica nada em rede social.
Entrada: run/media.json {"mode": "check|upload", "episodes": ["E03", ...], "nonce": "..."}.
Fonte dos mp4: pasta indicada em VNC_MEDIA_SRC (padrao fonte/backfill; no workflow e a branch de recarga ou o artefato vnc-build).
Credenciais: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET (segredos do repo); o segredo nunca e impresso.
public_id = vnc/<quadro><numero>-<10 primeiros hex do sha256>: estavel, repetivel e nao adivinhavel."""
import hashlib, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMITE_BYTES = 95 * 1024 * 1024  # plano gratis: 100 MB por video (docs Cloudinary); folga de 5 MB


class MediaError(RuntimeError):
    pass


def episodio(ep_id):
    num = json.loads((ROOT / "contracts/vnc_numeracao_v1.json").read_text(encoding="utf8"))
    for e in num["episodios"]:
        if e["id"] == ep_id:
            return e, num["quadros"][e["quadro"]]["nome"]
    raise MediaError(f"episodio desconhecido: {ep_id}")


def localizar(ep_id, raiz):
    e, nome_quadro = episodio(ep_id)
    d = Path(raiz) / nome_quadro / f"EPISÓDIO {e['numero']} - {e['titulo']}"
    mp4 = d / f"EPISÓDIO {e['numero']} - {e['titulo']}.mp4"
    if not mp4.is_file():
        raise MediaError(f"mp4 nao encontrado para {ep_id}: {mp4}")
    return mp4


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def public_id(ep_id, sha):
    e, _ = episodio(ep_id)
    return f"vnc/{e['quadro'].lower()}{e['numero']}-{sha[:10]}"


def url_publica(cloud, pid):
    return f"https://res.cloudinary.com/{cloud}/video/upload/{pid}.mp4"


def assinar(params, secret):
    base = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] not in (None, ""))
    return hashlib.sha1((base + secret).encode()).hexdigest()


def enviar(mp4, pid, cloud, key, secret, agora=None):
    import requests  # instalado no workflow
    ts = int(agora or time.time())
    params = {"public_id": pid, "timestamp": ts}
    with open(mp4, "rb") as f:
        r = requests.post(f"https://api.cloudinary.com/v1_1/{cloud}/video/upload",
                          data={**params, "api_key": key, "signature": assinar(params, secret)},
                          files={"file": (Path(mp4).name, f, "video/mp4")}, timeout=600)
    if r.status_code != 200:
        raise MediaError(f"upload falhou HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def conferir_url(url, tamanho):
    """HEAD publico: tem que responder 200, video/mp4 e o mesmo tamanho do arquivo local."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            ct, cl = r.headers.get("Content-Type", ""), int(r.headers.get("Content-Length", "-1"))
            return {"http": r.status, "content_type": ct, "tamanho_ok": cl == tamanho, "tamanho_remoto": cl}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "content_type": "", "tamanho_ok": False, "tamanho_remoto": -1}


def main(argv):
    cfg = json.loads((ROOT / "run/media.json").read_text(encoding="utf8"))
    mode = argv[0] if argv else cfg.get("mode", "check")
    if mode not in ("check", "upload"):
        raise MediaError(f"modo invalido: {mode}")
    raiz = os.environ.get("VNC_MEDIA_SRC", "fonte/backfill")
    cloud = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    key, secret = os.environ.get("CLOUDINARY_API_KEY", ""), os.environ.get("CLOUDINARY_API_SECRET", "")
    if mode == "upload" and not (cloud and key and secret):
        raise MediaError("credenciais Cloudinary ausentes")
    out = []
    for ep in cfg["episodes"]:
        mp4 = localizar(ep, raiz)
        tam = mp4.stat().st_size
        if tam > LIMITE_BYTES:
            raise MediaError(f"{ep}: {tam} bytes acima do limite do plano gratis")
        sha = sha256(mp4)
        pid = public_id(ep, sha)
        item = {"id": ep, "bytes": tam, "sha256": sha, "public_id": pid}
        if mode == "upload":
            enviar(mp4, pid, cloud, key, secret)
            item["url"] = url_publica(cloud, pid)
            item["conferencia"] = conferir_url(item["url"], tam)
        out.append(item)
        print("VNC_MEDIA " + json.dumps(item, ensure_ascii=False), flush=True)
    return out


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except MediaError as e:
        print(f"VNC_MEDIA_ERRO {e}"); sys.exit(1)
