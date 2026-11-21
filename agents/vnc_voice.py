"""Voz do episodio dentro do GitHub (ElevenLabs, voz Johnes Bittar). Chave: segredo ELEVENLABS_API_KEY do repositorio.
Travas: so gera se o roteiro estiver APROVADO, se assets/voice/<EP>.mp3 ainda nao existir (nunca regenera/gasta duas vezes),
e se houver credito suficiente. Modo check = valida chave/voz/credito SEM gastar. Uso: python -m agents.vnc_voice <EP> [check|generate]"""
import hashlib, json, os, subprocess, sys, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "contracts" / "vnc_voice_v1.json").read_text(encoding="utf8"))
TAIL_S = 9.5


def narration(ep, root=ROOT):
    j = json.loads((root / "episodes" / f"{ep}.json").read_text(encoding="utf8"))
    return " ".join(s["text"].strip() for s in j["scenes"]), j


def _api(path, key, body=None, binary=False):
    req = urllib.request.Request(CFG["api_base"] + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = r.read()
    return d if binary else json.loads(d)


def credits_left(key):
    s = _api("/v1/user/subscription", key)
    return int(s["character_limit"]) - int(s["character_count"])


def mp3_seconds(p):
    import imageio_ffmpeg
    out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(p)], capture_output=True, text=True).stderr
    h, m, s = out.split("Duration:")[1].split(",")[0].strip().split(":"); return int(h) * 3600 + int(m) * 60 + float(s)


def run(ep, mode="check", root=ROOT, api=_api, left=credits_left, seconds=mp3_seconds):
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        print("VNC_VOICE_ABORT sem_segredo ELEVENLABS_API_KEY (Settings > Secrets and variables > Actions)"); return 4
    text, cfg = narration(ep, root)
    out = root / "assets" / "voice" / f"{ep}.mp3"
    if out.exists() and mode == "generate":
        print("VNC_VOICE_ABORT voz_ja_existe (nunca regenerar: economia de creditos)", out); return 5
    need = int(len(text) * CFG["credit_margin"]) + 1
    try:
        have = left(key)
    except urllib.error.HTTPError as e:
        print("VNC_VOICE_ABORT api_http subscription (permissao User)", e.code, e.read()[:200]); return 6
    try:
        api(f"/v1/voices/{CFG['voice_id']}", key)
    except urllib.error.HTTPError as e:
        print("VNC_VOICE_ABORT api_http voz (permissao Voices ou voz fora do workspace)", e.code, e.read()[:200]); return 6
    print("VNC_VOICE_CHECK", json.dumps({"episodio": ep, "caracteres": len(text), "creditos_necessarios": need, "creditos_disponiveis": have, "voz_ok": True, "voz_ja_existe": out.exists()}))
    if have < need:
        print("VNC_VOICE_ABORT creditos_insuficientes"); return 7
    if mode != "generate":
        print("VNC_VOICE_CHECK_OK (nada gerado, nada gasto)"); return 0
    try:
        data = api(f"/v1/text-to-speech/{CFG['voice_id']}?output_format={CFG['output_format']}", key,
                   {"text": text, "model_id": CFG["model_id"], "language_code": CFG["language_code"]}, binary=True)
    except urllib.error.HTTPError as e:
        print("VNC_VOICE_ABORT geracao_http", e.code); return 6
    out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(data)   # grava antes de qualquer conferencia: credito ja gasto nao se perde
    sha = hashlib.sha256(data).hexdigest(); cfg["audio_sha256"] = sha
    (root / "episodes" / f"{ep}.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf8")
    d = seconds(out)
    print("VNC_VOICE_OK", ep, len(data), sha, round(d, 2), "s")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "check"))
