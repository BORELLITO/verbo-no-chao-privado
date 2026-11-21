"""Persiste a voz aprovada no repo privado (assets/voice/<EP>.mp3) para o link assinado nunca mais bloquear a producao.
Roda so no runner (workflow vnc-ingest-voice). Confere o sha256 da config do episodio antes de gravar."""
import hashlib, json, sys, urllib.request
from pathlib import Path


def main(ep):
    cfg = json.loads(Path(f"episodes/{ep}.json").read_text(encoding="utf8"))
    link = Path(cfg["audio_link_file"]).read_text().strip()
    if not link.startswith("https://elevenlabsusercontent.com/"):
        print("VNC_INGEST_ABORT link_invalido"); return 4
    data = urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"}), timeout=120).read()
    sha = hashlib.sha256(data).hexdigest()
    ok = sha == cfg["audio_sha256"] if cfg.get("audio_sha256") else (sha.startswith(cfg["audio_sha256_prefix"]) and sha.endswith(cfg["audio_sha256_suffix"]))
    if not ok:
        print("VNC_INGEST_ABORT sha_diferente", sha); return 2
    out = Path(f"assets/voice/{ep}.mp3"); out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(data)
    print("VNC_INGEST_OK", ep, len(data), sha); return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
