"""VNC -> hospedagem publica da midia (Cloudinary, plano gratis) para o Buffer buscar o mp4.
Unico modulo que fala com api.cloudinary.com / res.cloudinary.com. NAO publica nada em rede social.
Entrada: run/media.json {"mode": "check|upload|check_capa|upload_capa", "episodes": ["E03", ...], "nonce": "..."}.
Fonte dos mp4: artefato vnc-build do run indicado em "runs" ({"E08": <run_id>}; vale 3 dias) ou, sem run, pasta indicada em VNC_MEDIA_SRC (padrao fonte/backfill; no workflow e a branch de recarga ou o artefato vnc-build).
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


def localizar(ep_id, raiz, art=None):
    """Artefato do Runflow (art/<id>/**/*.mp4, quando o episodio tem run indicado) tem prioridade; senao pasta de recarga."""
    if art and (Path(art) / ep_id).is_dir():
        achados = sorted((Path(art) / ep_id).rglob("*.mp4"))
        if len(achados) != 1:
            raise MediaError(f"{ep_id}: esperado 1 mp4 no artefato, achei {len(achados)}")
        return achados[0]
    e, nome_quadro = episodio(ep_id)
    d = Path(raiz) / nome_quadro / f"EPISÓDIO {e['numero']} - {e['titulo']}"
    mp4 = d / f"EPISÓDIO {e['numero']} - {e['titulo']}.mp4"
    if not mp4.is_file():
        raise MediaError(f"mp4 nao encontrado para {ep_id}: {mp4}")
    return mp4


def localizar_capa(ep_id, raiz, art=None):
    """Capa vertical (jpg). Artefato vnc-cover do run (art/<id>-capa/**/*.jpg) tem prioridade; senao CAPA.jpg da pasta de recarga."""
    if art and (Path(art) / f"{ep_id}-capa").is_dir():
        achados = sorted((Path(art) / f"{ep_id}-capa").rglob("*.jpg"))
        if len(achados) != 1:
            raise MediaError(f"{ep_id}: esperado 1 jpg de capa no artefato, achei {len(achados)}")
        return achados[0]
    e, nome_quadro = episodio(ep_id)
    d = Path(raiz) / nome_quadro / f"EPISÓDIO {e['numero']} - {e['titulo']}"
    jpg = d / f"EPISÓDIO {e['numero']} - {e['titulo']} - CAPA.jpg"
    if not jpg.is_file():
        raise MediaError(f"capa nao encontrada para {ep_id}: {jpg}")
    return jpg


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def public_id(ep_id, sha):
    e, _ = episodio(ep_id)
    return f"vnc/{e['quadro'].lower()}{e['numero']}-{sha[:10]}"


def public_id_capa(ep_id, sha):
    e, _ = episodio(ep_id)
    return f"vnc/{e['quadro'].lower()}{e['numero']}-capa-{sha[:10]}"


def url_capa(cloud, pid):
    return f"https://res.cloudinary.com/{cloud}/image/upload/{pid}.jpg"


def public_id_seguro(ep_id, sha):
    e, _ = episodio(ep_id)
    return f"vnc/{e['quadro'].lower()}{e['numero']}-seguro-{sha[:10]}"


def ffmpeg_seguro(src, dst):
    """Copia de PUBLICACAO (o master nao muda): video copiado sem recodificar; audio estereo (mono duplicado), pico limitado a ~-3 dBFS, AAC 192k.
    Motivo: audio estourado/robotico nos 3 canais quando o Buffer processa o mp4 (23/11); os posts nativos anteriores ficaram bons."""
    return ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
            "-af", "pan=stereo|c0=c0|c1=c0,alimiter=limit=0.708:level=disabled,aresample=48000",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dst)]


def medir_audio(arq):
    import subprocess, re
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(arq), "-vn", "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"], capture_output=True, text=True).stderr
    r = r[r.rfind("Summary"):]
    return {"lufs": re.search(r"I:\s+(-?[\d.]+) LUFS", r).group(1), "pico_dbfs": re.search(r"Peak:\s+(-?[\d.]+) dBFS", r).group(1)}


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


def enviar_capa(jpg, pid, cloud, key, secret, agora=None):
    import requests  # instalado no workflow
    ts = int(agora or time.time())
    params = {"public_id": pid, "timestamp": ts}
    with open(jpg, "rb") as f:
        r = requests.post(f"https://api.cloudinary.com/v1_1/{cloud}/image/upload",
                          data={**params, "api_key": key, "signature": assinar(params, secret)},
                          files={"file": (Path(jpg).name, f, "image/jpeg")}, timeout=120)
    if r.status_code != 200:
        raise MediaError(f"upload da capa falhou HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def verificar_remoto(url, sha_local):
    """GET publico do que o Buffer realmente baixa: sha256 do corpo entregue x sha256 do arquivo local (prova byte a byte)."""
    import requests  # instalado no workflow
    h, n = hashlib.sha256(), 0
    with requests.get(url, stream=True, timeout=600) as r:
        for b in r.iter_content(1 << 20):
            h.update(b); n += len(b)
        return {"http": r.status_code, "content_type": r.headers.get("Content-Type", ""), "bytes": n, "sha256_remoto": h.hexdigest(), "identico": h.hexdigest() == sha_local}


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
    if mode not in ("check", "upload", "check_capa", "upload_capa", "verify_remoto", "upload_seguro"):
        raise MediaError(f"modo invalido: {mode}")
    raiz = os.environ.get("VNC_MEDIA_SRC", "fonte/backfill")
    cloud = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    key, secret = os.environ.get("CLOUDINARY_API_KEY", ""), os.environ.get("CLOUDINARY_API_SECRET", "")
    if mode in ("upload", "upload_capa", "upload_seguro") and not (cloud and key and secret):
        raise MediaError("credenciais Cloudinary ausentes")
    out = []
    for ep in cfg["episodes"]:
        if mode.endswith("_capa"):
            jpg = localizar_capa(ep, raiz, os.environ.get("VNC_MEDIA_ART", "art"))
            sha = sha256(jpg)
            pid = public_id_capa(ep, sha)
            item = {"id": ep, "capa_bytes": jpg.stat().st_size, "sha256": sha, "public_id_capa": pid}
            if mode == "upload_capa":
                enviar_capa(jpg, pid, cloud, key, secret)
                item["url"] = url_capa(cloud, pid)
                item["conferencia"] = conferir_url(item["url"], jpg.stat().st_size)
            out.append(item)
            print("VNC_MEDIA_CAPA " + json.dumps(item, ensure_ascii=False), flush=True)
            continue
        mp4 = localizar(ep, raiz, os.environ.get("VNC_MEDIA_ART", "art"))
        tam = mp4.stat().st_size
        if tam > LIMITE_BYTES:
            raise MediaError(f"{ep}: {tam} bytes acima do limite do plano gratis")
        sha = sha256(mp4)
        pid = public_id(ep, sha)
        item = {"id": ep, "bytes": tam, "sha256": sha, "public_id": pid}
        if mode == "upload_seguro":
            import subprocess, tempfile
            with tempfile.TemporaryDirectory() as t:
                dst = Path(t) / "seguro.mp4"
                subprocess.run(ffmpeg_seguro(mp4, dst), check=True)
                sha_s, tam_s = sha256(dst), dst.stat().st_size
                if tam_s > LIMITE_BYTES:
                    raise MediaError(f"{ep}: copia segura {tam_s} bytes acima do limite")
                pid_s = public_id_seguro(ep, sha_s)
                item = {"id": ep, "original_sha256": sha, "original_audio": medir_audio(mp4), "seguro_bytes": tam_s, "seguro_sha256": sha_s, "seguro_audio": medir_audio(dst), "public_id_seguro": pid_s}
                enviar(dst, pid_s, cloud, key, secret)
                item["url_ok"] = verificar_remoto(url_publica(cloud, pid_s), sha_s)
            out.append(item)
            print("VNC_MEDIA_SEGURO " + json.dumps(item, ensure_ascii=False), flush=True)
            continue
        if mode == "verify_remoto":
            item["url_ok"] = verificar_remoto(url_publica(cloud, pid), sha)
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
