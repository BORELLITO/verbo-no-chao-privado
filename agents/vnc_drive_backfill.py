"""VNC -> Drive: recarga unica dos episodios JA PRONTOS (runner only). Le backfill/<QUADRO>/<EPISODIO>/* de um branch isolado e envia para
VERBO NO CHÃO/<QUADRO>/<EPISODIO>/ com os mesmos nomes (reenvio sobrescreve, sem duplicar). Nao publica nada. Segredos: GDRIVE_*."""
import json, os, sys
from pathlib import Path
from agents.vnc_drive import ROOT_NAME, rclone_env, rc


def main(src="backfill"):
    if not all(os.environ.get(k) for k in ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN")):
        print("VNC_DRIVE_NAO_CONFIGURADO"); return 0
    env = rclone_env(); n = 0
    for quadro in sorted(p for p in Path(src).iterdir() if p.is_dir()):
        for ep in sorted(p for p in quadro.iterdir() if p.is_dir()):
            path = f"{ROOT_NAME}/{quadro.name}/{ep.name}"
            rc(["mkdir", f"gd:{path}"], env)
            for f in sorted(ep.iterdir()):
                if f.is_file() and f.stat().st_size > 0:
                    rc(["copyto", str(f), f"gd:{path}/{f.name}"], env); n += 1
            ids = {d["Name"]: d["ID"] for d in json.loads(rc(["lsjson", "--dirs-only", f"gd:{ROOT_NAME}/{quadro.name}"], env) or "[]")}
            print("VNC_DRIVE_BACKFILL", json.dumps({"pasta": path, "link": f"https://drive.google.com/drive/folders/{ids.get(ep.name, '?')}"}, ensure_ascii=False))
    print("VNC_DRIVE_BACKFILL_OK", n, "arquivos"); return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
