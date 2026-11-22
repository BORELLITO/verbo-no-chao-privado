"""VNC -> Google Drive (runner only). Envia os arquivos FINAIS de um episodio para a pasta certa do Drive do dono.
- Pastas: VERBO NO CHÃO / (QUADRO - DORES DA VIDA | QUADRO - FORA DO CONTEXTO) / EPISÓDIO N - TITULO. Cria o que faltar; reenvio sobrescreve pelo nome (sem duplicar).
- Acesso OAuth restrito (escopo drive.file): o app so enxerga o que ele mesmo criou. Nada e publicado; o link devolvido e privado (so o dono abre).
- Segredos (GitHub): GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN. Sem eles: DRIVE_NAO_CONFIGURADO e sai sem erro.
- DRIVE_DRY_RUN=1: so imprime o plano (nenhuma chamada ao Drive)."""
import json, os, re, subprocess, sys
from pathlib import Path

ROOT_NAME = "VERBO NO CHÃO"
QUADRO_DORES, QUADRO_FORA = "QUADRO - DORES DA VIDA", "QUADRO - FORA DO CONTEXTO"


def _cap(t):
    t = t.strip()
    return t[:1].upper() + t[1:]


def plan(cfg):
    """Nomes de pasta/arquivos a partir do episodes/<EP>.json (funcao pura, testada).
    Padrao do dono: QUADRO - <NOME> / EPISÓDIO <N> - <TITULO EM MAIUSCULAS> / <mesmo nome>.mp4|.srt| - CAPA.jpg| - LEGENDAS DE POSTAGEM.txt"""
    ref = cfg["reference"]
    title = cfg.get("drive_titulo") or " ".join(cfg["title_lines"]).upper()
    if cfg.get("cover_style") == "quadro":
        n = int(re.search(r"(?:#|EPIS[ÓO]DIO)\s*(\d+)", cfg["cover_quadro"]["kicker"]).group(1))
        quadro, label = QUADRO_FORA, f"EPISÓDIO {n}"
    else:
        n = int(cfg.get("cover_number", cfg["number"]))
        quadro, label = QUADRO_DORES, f"EPISÓDIO {n}"
    base = f"EPISÓDIO {n} - {title}"
    return {"quadro": quadro, "folder": base, "base": base, "label": label, "title": title, "ref": ref,
            "files": {"video": f"{base}.mp4", "srt": f"{base}.srt", "cover": f"{base} - CAPA.jpg", "posting": f"{base} - LEGENDAS DE POSTAGEM.txt"}}


def posting_text(cfg, p):
    from agents.vnc_pipeline_gate import render_posting
    t = render_posting(cfg)
    return (f'VERBO NO CHÃO — {p["quadro"]} — {p["label"]} "{p["title"]}" — {p["ref"]}\nLEGENDAS DE POSTAGEM POR PLATAFORMA (publicar é decisão do dono)\n\n'
            f'=== TIKTOK ({len(t["tiktok"])} caracteres) ===\n{t["tiktok"]}\n\n=== INSTAGRAM REELS ===\n{t["instagram"]}\n\n'
            f'=== YOUTUBE SHORTS ===\nTítulo ({len(t["youtube_titulo"])} caracteres):\n{t["youtube_titulo"]}\n\nDescrição:\n{t["youtube_descricao"]}\n')


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
