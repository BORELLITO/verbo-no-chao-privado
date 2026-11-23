"""Numeracao e nomes OFICIAIS dos episodios (fonte unica: contracts/vnc_numeracao_v1.json).
O id interno (E01..E0N) e so chave estavel de arquivos/hashes. Tudo que o dono ve usa QUADRO + numero do quadro + TITULO.
  python -m agents.vnc_naming list            tabela oficial
  python -m agents.vnc_naming check           valida registro x episodes/*.json (sai 1 se divergir)
  python -m agents.vnc_naming label E07       rotulo de um episodio
  python -m agents.vnc_naming next FORA       proximo numero do quadro (DORES|FORA)
  python -m agents.vnc_naming doc [--write]   gera EPISODIOS.md"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "contracts" / "vnc_numeracao_v1.json"


def load(root=ROOT):
    return json.loads((root / "contracts" / "vnc_numeracao_v1.json").read_text(encoding="utf8"))


def entry(ep, root=ROOT):
    for e in load(root)["episodios"]:
        if e["id"] == ep:
            return e
    raise KeyError(f"{ep} nao esta em contracts/vnc_numeracao_v1.json (registre quadro, numero e titulo antes de produzir)")


def quadro_nome(ep, root=ROOT):
    return load(root)["quadros"][entry(ep, root)["quadro"]]["nome"]


def rotulo(ep, root=ROOT):
    """Nome curto que o dono ve: 'DORES DA VIDA 4'. Quadro + numero do quadro, nunca o id interno."""
    e = entry(ep, root); return f"{load(root)['quadros'][e['quadro']]['curto'].upper()} {e['numero']}"


def kicker(ep, root=ROOT):
    """Linha pequena da capa: 'DORES DA VIDA · EPISÓDIO 4' (sem zero a esquerda; mesmo padrao nos dois quadros)."""
    e = entry(ep, root); return f"{load(root)['quadros'][e['quadro']]['curto'].upper()} · EPISÓDIO {e['numero']}"


def horario(quadro, root=ROOT):
    return load(root)["quadros"][quadro]["horario"]


def base(ep, root=ROOT):
    e = entry(ep, root); return f"{rotulo(ep, root)} - {e['titulo']}"


def files(ep, root=ROOT):
    b = base(ep, root)
    return {"video": f"{b}.mp4", "srt": f"{b}.srt", "cover": f"{b} - CAPA.jpg", "posting": f"{b} - LEGENDAS DE POSTAGEM.txt"}


def label(ep, root=ROOT):
    e = entry(ep, root); return f"{rotulo(ep, root)} — {e['titulo']}"


def next_number(quadro, root=ROOT):
    ns = [e["numero"] for e in load(root)["episodios"] if e["quadro"] == quadro]
    return (max(ns) if ns else 0) + 1


KARAOKE_LARANJA = "&H0066B3FF"   # quadro FORA DO CONTEXTO (decisao do dono 2026-11-22); DORES DA VIDA = lilas travado do vnc_style


def check(root=ROOT):
    errs, reg = [], load(root)
    ids = [e["id"] for e in reg["episodios"]]
    if len(ids) != len(set(ids)): errs.append("id repetido no registro")
    for q in reg["quadros"]:
        ns = sorted(e["numero"] for e in reg["episodios"] if e["quadro"] == q)
        if ns != list(range(1, len(ns) + 1)): errs.append(f"{q}: numeracao {ns} nao e 1..{len(ns)} sem buracos nem repeticao")
    for e in reg["episodios"]:
        if e["quadro"] not in reg["quadros"]: errs.append(f"{e['id']}: quadro {e['quadro']} desconhecido")
    on_disk = sorted(p.stem for p in (root / "episodes").glob("E[0-9]*.json") if re.fullmatch(r"E\d+", p.stem))
    for ep in on_disk:
        if ep not in ids: errs.append(f"{ep}: tem episodes/{ep}.json mas nao esta no registro de numeracao")
    for ep in ids:
        if ep not in on_disk: errs.append(f"{ep}: esta no registro mas falta episodes/{ep}.json"); continue
        errs += check_episode(ep, root)
    return errs


def check_episode(ep, root=ROOT):
    """Confere o episodes/<EP>.json contra o registro (numero na capa, kicker do quadro, titulo, referencia)."""
    try: e = entry(ep, root)
    except KeyError as ex: return [f"NUMERACAO: {ex.args[0]}"]
    p = root / "episodes" / f"{ep}.json"
    if not p.exists(): return [f"NUMERACAO: falta episodes/{ep}.json"]
    cfg, errs = json.loads(p.read_text(encoding="utf8")), []
    if cfg.get("reference") != e["referencia"]: errs.append(f"NUMERACAO {ep}: referencia '{cfg.get('reference')}' != registro '{e['referencia']}'")
    kar = load(root)["quadros"][e["quadro"]].get("karaoke")
    if kar == "laranja" and cfg.get("karaoke_color") != KARAOKE_LARANJA: errs.append(f"NUMERACAO {ep}: quadro {e['quadro']} exige karaoke laranja {KARAOKE_LARANJA}, episodio tem {cfg.get('karaoke_color')}")
    if kar == "lilas" and cfg.get("karaoke_color"): errs.append(f"NUMERACAO {ep}: quadro {e['quadro']} usa o lilas travado; remova karaoke_color ({cfg.get('karaoke_color')})")
    if cfg.get("cover_style") == "quadro":
        if e["quadro"] != "FORA": errs.append(f"NUMERACAO {ep}: capa de quadro mas registro diz {e['quadro']}")
        k = (cfg.get("cover_quadro") or {}).get("kicker", "")
        want = kicker(ep, root)
        if k != want: errs.append(f"NUMERACAO {ep}: kicker da capa '{k}' != '{want}'")
        big = " ".join((cfg.get("cover_quadro") or {}).get("big", []))
        ok_big = (load(root).get("excecoes", {}).get(ep) or {}).get("capa_big", e["titulo"])
        if big != ok_big: errs.append(f"NUMERACAO {ep}: titulo grande da capa '{big}' != titulo oficial '{e['titulo']}'")
    else:
        shown = cfg.get("cover_number", cfg.get("number"))
        if shown != e["numero"]: errs.append(f"NUMERACAO {ep}: numero na capa {shown} != numero do quadro {e['numero']}")
        if e["quadro"] != "DORES": errs.append(f"NUMERACAO {ep}: capa padrao e so do quadro DORES (registro diz {e['quadro']})")
    if "titulo_curto" in (cfg.get("posting") or {}): errs.append(f"NUMERACAO {ep}: posting.titulo_curto e proibido (nome so pelo registro: {rotulo(ep, root)} - {e['titulo']})")
    return errs


def check_publicacao(root=ROOT):
    """Pacote/calendario: horario fixo por quadro (12:00 DORES, 19:00 FORA), um episodio por dia por quadro, em ordem, sem buracos."""
    reg, errs = load(root), []
    pk = json.loads((root / "publicacao" / "pacote_v1.json").read_text(encoding="utf8"))
    por_quadro = {}
    for x in pk["episodios"]:
        q = next(k for k, v in reg["quadros"].items() if v["nome"] == x["quadro"])
        dia, hora = x["sugestao_horario_brt"].split(" ")
        if hora != reg["quadros"][q]["horario"]: errs.append(f"PUBLICACAO {rotulo(x['id'], root)}: horario {hora} != {reg['quadros'][q]['horario']} do quadro")
        por_quadro.setdefault(q, []).append((x["numero"], dia))
    import datetime as dt
    for q, itens in por_quadro.items():
        itens.sort()
        for (n1, d1), (n2, d2) in zip(itens, itens[1:]):
            if n2 != n1 + 1 or dt.date.fromisoformat(d2) - dt.date.fromisoformat(d1) != dt.timedelta(days=1):
                errs.append(f"PUBLICACAO {q}: {n1}({d1}) -> {n2}({d2}) fora de ordem ou com buraco")
    with open(root / "publicacao" / "calendario_v1.csv", encoding="utf8") as f:
        for linha in f.read().splitlines()[1:]:
            if "QUADRO -" in linha: errs.append(f"PUBLICACAO calendario: prefixo 'QUADRO -' no rotulo: {linha}")
    return errs


def doc(root=ROOT):
    reg = load(root); out = ["# Episódios do VERBO NO CHÃO — numeração oficial", "",
        "Gerado por `python -m agents.vnc_naming doc --write` a partir de `contracts/vnc_numeracao_v1.json` (fonte única). Não editar à mão.", "",
        "O **id interno** (`E01`…) é só a chave estável de arquivos, hashes e registros. Pastas, arquivos, capas, legendas e Drive usam **quadro + número + título**.", ""]
    for q, qi in reg["quadros"].items():
        out += [f"## {qi['nome']}", "", "| Nº | Título | Referência | id interno |", "|---|---|---|---|"]
        for e in sorted((x for x in reg["episodios"] if x["quadro"] == q), key=lambda x: x["numero"]):
            out.append(f"| {rotulo(e['id'], root)} | {e['titulo']} | {e['referencia']} | {e['id']} |")
        out += ["", f"Próximo: {qi['curto'].upper()} {next_number(q, root)} (horário fixo {qi['horario']} BRT)", ""]
    out += ["## Padrão de nomes no Drive", "", "`VERBO NO CHÃO / QUADRO - <NOME> / <QUADRO> <N> - <TÍTULO> /` (ex.: `DORES DA VIDA 4 - ESPERANÇA ENTRE RUÍNAS`) com `<mesmo nome>.mp4`, `.srt`, ` - CAPA.jpg` e ` - LEGENDAS DE POSTAGEM.txt`. Capa: kicker `<QUADRO> · EPISÓDIO <N>` sem zero à esquerda. Horário fixo: 12:00 DORES DA VIDA, 19:00 FORA DO CONTEXTO.", ""]
    return "\n".join(out)


def main(argv):
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        for e in load()["episodios"]: print(label(e["id"]), f"(id interno {e['id']})")
    elif cmd == "check":
        errs = check() + check_publicacao()
        for e in errs: print("VNC_NUMERACAO_FAIL", e)
        print("VNC_NUMERACAO_OK" if not errs else f"VNC_NUMERACAO_BLOCKED {len(errs)}"); return 1 if errs else 0
    elif cmd == "label": print(label(argv[1]))
    elif cmd == "next": print(next_number(argv[1].upper()))
    elif cmd == "doc":
        t = doc()
        if "--write" in argv: (ROOT / "EPISODIOS.md").write_text(t, encoding="utf8")
        else: print(t)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
