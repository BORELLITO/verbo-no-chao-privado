"""VNC -> Google Drive (runner only). Organiza as pastas dos episodios em ESTOQUE (disponiveis) e POSTADOS (ja publicados), sempre separando os quadros.
Entrada: run/drive.json  {"mode": "listar|organizar", "nonce": "...", "estoque": ["E03", ...], "postados": ["E01", ...], "liberado_pelo_dono": true}
- listar    (leitura) mostra o que o app enxerga hoje em VERBO NO CHAO, ESTOQUE e POSTADOS.
- organizar MOVE a pasta inteira do episodio (mv de pasta no mesmo Drive, sem copiar nem apagar arquivo) de VERBO NO CHAO/<QUADRO>/<EPISODIO> para
            VERBO NO CHAO/<ESTOQUE|POSTADOS>/<QUADRO>/<EPISODIO>. Exige liberado_pelo_dono=true. Idempotente: o que ja foi movido e so reportado.
Acesso OAuth restrito (escopo drive.file): o app so enxerga o que ele mesmo criou (as pastas dos episodios foram criadas por ele). Nada e publicado nem apagado.
Segredos: GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN. DRIVE_DRY_RUN=1 so imprime o plano."""
import json, os, sys
from pathlib import Path

from agents import vnc_drive as D
from agents import vnc_naming as N

ROOT = Path(__file__).resolve().parents[1]
DESTINOS = {"estoque": "ESTOQUE", "postados": "POSTADOS"}
MODOS = ("listar", "organizar")


class DriveOrgError(RuntimeError):
    pass


def plano(cfg, root=ROOT):
    """Funcao pura: lista de movimentos [{ep, quadro, pasta, de, para, destino}]. Valida ids, duplicidade e o campo de liberacao fica no chamador."""
    movs, vistos = [], set()
    for chave, nome in DESTINOS.items():
        for ep in cfg.get(chave) or []:
            if ep in vistos:
                raise DriveOrgError(f"{ep} aparece em mais de um destino (ou repetido)")
            vistos.add(ep)
            try:
                quadro, pasta = N.quadro_nome(ep, root), N.base(ep, root)
            except KeyError as e:
                raise DriveOrgError(str(e)) from None
            movs.append({"ep": ep, "quadro": quadro, "pasta": pasta, "destino": nome,
                         "de": f"{D.ROOT_NAME}/{quadro}/{pasta}", "para": f"{D.ROOT_NAME}/{nome}/{quadro}/{pasta}"})
    if not movs:
        raise DriveOrgError("nada a mover: informe 'estoque' e/ou 'postados'")
    return movs


def _existe(path, env):
    pai, _, nome = path.rpartition("/")
    try:
        saida = D.rc(["lsjson", "--dirs-only", f"gd:{pai}"], env)
    except SystemExit:
        return False
    return any(d["Name"] == nome for d in json.loads(saida or "[]"))


def listar(env):
    out = {}
    for caminho in (D.ROOT_NAME, f"{D.ROOT_NAME}/ESTOQUE", f"{D.ROOT_NAME}/POSTADOS"):
        for q in (["", "/QUADRO - DORES DA VIDA", "/QUADRO - FORA DO CONTEXTO"] if caminho != D.ROOT_NAME else [""]):
            p = caminho + q
            try:
                out[p] = sorted(d["Name"] for d in json.loads(D.rc(["lsjson", "--dirs-only", f"gd:{p}"], env) or "[]"))
            except SystemExit as e:
                out[p] = f"(nao visivel/erro: {str(e)[:120]})"
    return out


def organizar(cfg, env, movs):
    if cfg.get("liberado_pelo_dono") is not True:
        raise DriveOrgError("BLOQUEADO: falta liberado_pelo_dono=true")
    res = []
    for m in movs:
        if _existe(m["para"], env):
            res.append({**m, "resultado": "ja_estava_no_destino"}); continue
        if not _existe(m["de"], env):
            res.append({**m, "resultado": "origem_nao_encontrada_pelo_app"}); continue
        D.rc(["mkdir", f"gd:{D.ROOT_NAME}/{m['destino']}/{m['quadro']}"], env)
        D.rc(["moveto", f"gd:{m['de']}", f"gd:{m['para']}"], env)
        res.append({**m, "resultado": "movido"})
    return res


def main(argv=None):
    cfg = json.load(open(ROOT / "run/drive.json", encoding="utf8"))
    mode = (argv or sys.argv[1:] or [cfg.get("mode", "listar")])[0]
    if mode not in MODOS:
        print("modo desconhecido"); return 2
    try:
        movs = plano(cfg) if mode == "organizar" else []
        print("VNC_DRIVE_ORG_PLANO", json.dumps(movs, ensure_ascii=False))
        if os.environ.get("DRIVE_DRY_RUN") == "1":
            print("VNC_DRIVE_ORG_DRY_RUN"); return 0
        if not all(os.environ.get(k) for k in ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN")):
            print("VNC_DRIVE_NAO_CONFIGURADO: faltam os segredos GDRIVE_*; nada feito"); return 0
        env = D.rclone_env()
        out = listar(env) if mode == "listar" else organizar(cfg, env, movs)
        print("VNC_DRIVE_ORG_RESULTADO", json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    except DriveOrgError as e:
        print("ERRO:", e); return 1


if __name__ == "__main__":
    sys.exit(main())
