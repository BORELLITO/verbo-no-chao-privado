"""VNC -> Google Drive (runner only). Envia os arquivos FINAIS de um episodio para a pasta certa do Drive do dono.
- Pastas: VERBO NO CHÃO / (QUADRO - DORES DA VIDA | QUADRO - FORA DO CONTEXTO) / EPISÓDIO N - TITULO. Cria o que faltar; reenvio sobrescreve pelo nome (sem duplicar).
- Acesso OAuth restrito (escopo drive.file): o app so enxerga o que ele mesmo criou. Nada e publicado; o link devolvido e privado (so o dono abre).
- Segredos (GitHub): GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN. Sem eles: DRIVE_NAO_CONFIGURADO e sai sem erro.
- DRIVE_DRY_RUN=1: so imprime o plano (nenhuma chamada ao Drive)."""
import json, os, re, subprocess, sys
from pathlib import Path

ROOT_NAME = "VERBO NO CHÃO"


def _cap(t):
    t = t.strip()
    return t[:1].upper() + t[1:]


def plan(cfg):
    """Nomes de pasta/arquivos vindos do registro unico (contracts/vnc_numeracao_v1.json via agents.vnc_naming). Funcao pura, testada.
    Padrao do dono: QUADRO - <NOME> / EPISÓDIO <N> - <TITULO EM MAIUSCULAS> / <mesmo nome>.mp4|.srt| - CAPA.jpg| - LEGENDAS DE POSTAGEM.txt"""
    from agents import vnc_naming as N
    ep = cfg["id"]; e = N.entry(ep); b = N.base(ep)
    return {"quadro": N.quadro_nome(ep), "folder": b, "base": b, "label": f"EPISÓDIO {e['numero']}", "title": e["titulo"], "ref": cfg["reference"], "files": N.files(ep)}


def posting_text(cfg, p):
    """Fonte unica: o mesmo arquivo que o agente-mestre imprime no chat (vnc_pipeline_gate.render_posting_file)."""
    from agents.vnc_pipeline_gate import render_posting_file
    return render_posting_file(cfg["id"], cfg)


def rclone_env(env=None):
    e = dict(os.environ if env is None else env)
    e.update({"RCLONE_CONFIG_GD_TYPE": "drive", "RCLONE_CONFIG_GD_CLIENT_ID": e["GDRIVE_CLIENT_ID"], "RCLONE_CONFIG_GD_CLIENT_SECRET": e["GDRIVE_CLIENT_SECRET"],
              "RCLONE_CONFIG_GD_SCOPE": "drive.file",
              "RCLONE_CONFIG_GD_TOKEN": json.dumps({"access_token": "", "token_type": "Bearer", "refresh_token": e["GDRIVE_REFRESH_TOKEN"], "expiry": "2000-01-01T00:00:00Z"})})
    return e


def rc(args, env):
    r = subprocess.run(["rclone"] + args, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"VNC_DRIVE_ERRO rclone {args[0]}: {r.stderr.strip()[:400]}")
    return r.stdout


def main(ep, build_dir, cover_dir):
    cfg = json.loads(Path(f"episodes/{ep}.json").read_text(encoding="utf8"))
    p = plan(cfg)
    src = {"video": Path(build_dir) / "master.mp4", "srt": Path(build_dir) / "captions.srt", "cover": Path(cover_dir) / "vertical.jpg"}
    path = f"{ROOT_NAME}/{p['quadro']}/{p['folder']}"
    print("VNC_DRIVE_PLANO", json.dumps({"pasta": path, "arquivos": p["files"], "presentes": {k: v.exists() for k, v in src.items()}}, ensure_ascii=False))
    if os.environ.get("DRIVE_DRY_RUN") == "1":
        print("VNC_DRIVE_DRY_RUN"); return 0
    if not all(os.environ.get(k) for k in ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN")):
        print("VNC_DRIVE_NAO_CONFIGURADO: faltam os segredos GDRIVE_*; nada enviado"); return 0
    env = rclone_env(); sent = []
    rc(["mkdir", f"gd:{path}"], env)
    if os.environ.get("VNC_DRIVE_SEGURO") == "1":
        # so a copia de PUBLICACAO (audio estereo, pico limitado), mesma regra do upload_seguro do Cloudinary; nao toca nos demais arquivos
        from agents import vnc_media
        dst = Path("/tmp/seguro.mp4")
        subprocess.run(vnc_media.ffmpeg_seguro(src["video"], dst), check=True)
        nome = p["files"]["video"].rsplit(".", 1)[0] + " - SEGURO.mp4"
        rc(["copyto", str(dst), f"gd:{path}/{nome}"], env)
        print("VNC_DRIVE_SEGURO_OK", json.dumps({"enviado": nome, "bytes": dst.stat().st_size}, ensure_ascii=False)); return 0
    for k, f in src.items():
        if f.exists() and f.stat().st_size > 0:
            rc(["copyto", str(f), f"gd:{path}/{p['files'][k]}"], env); sent.append(p["files"][k])
    tmp = Path("/tmp/posting.txt"); tmp.write_text(posting_text(cfg, p), encoding="utf8")
    rc(["copyto", str(tmp), f"gd:{path}/{p['files']['posting']}"], env); sent.append(p["files"]["posting"])
    parent = f"gd:{ROOT_NAME}/{p['quadro']}"
    ids = {d["Name"]: d["ID"] for d in json.loads(rc(["lsjson", "--dirs-only", parent], env) or "[]")}
    fid = ids.get(p["folder"])
    print("VNC_DRIVE_OK", json.dumps({"enviados": sent}, ensure_ascii=False))
    print("VNC_DRIVE_LINK", f"https://drive.google.com/drive/folders/{fid}" if fid else "(pasta criada; id nao encontrado)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "art/build", sys.argv[3] if len(sys.argv) > 3 else "art/cover"))
