"""Publisher VNC camadas 1-2: pacote de publicacao + calendario. NAO publica nada.
Uso: python tools/vnc_publisher.py [--inicio AAAA-MM-DD] [--slots 12:00,19:00]
Gera publicacao/pacote_v1.json e publicacao/calendario_v1.csv.
Estados por plataforma: nao_agendado -> agendado -> publicado (preenchidos SO pelo dono)."""
import argparse, csv, json, sys, datetime as dt, pathlib
R = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
from agents.vnc_pipeline_gate import render_posting  # gerador unico das legendas por plataforma
PLAT = ("tiktok", "youtube", "instagram")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inicio", default="2026-11-23")
    ap.add_argument("--slots", default="12:00,19:00")
    a = ap.parse_args()
    slots = a.slots.split(","); dia = dt.date.fromisoformat(a.inicio)
    num = json.load(open(R / "contracts/vnc_numeracao_v1.json"))
    pend, pacote, k = [], [], 0
    # Estrutura 2 quadros: cada quadro tem uma fila na ordem definida pelo dono;
    # o calendario intercala (slot 1 = DORES, slot 2 = FORA); se uma fila acaba, a outra segue.
    pub = json.load(open(R / "contracts/vnc_publicados_v1.json"))["publicados"]
    ja = lambda e: all(pub.get(e["id"], {}).get(x) == "publicado" for x in PLAT)
    tem = lambda e: json.load(open(R / f"episodes/{e['id']}.json")).get("posting")
    tem_ou_pub = lambda e: tem(e) or ja(e)
    filas = {q: [e for e in num["episodios"] if e["quadro"] == q and tem_ou_pub(e) and not ja(e)] for q in num["quadros"]}
    ordem = []
    while any(filas.values()):
        for q in ("DORES", "FORA"):
            if filas[q]: ordem.append(filas[q].pop(0))
    for e in num["episodios"]:
        if not tem(e) and not ja(e): pend.append(f"{e['id']} {num['quadros'][e['quadro']]['nome']} {e['numero']}: sem bloco posting")
    for e in ordem:
        cfg = json.load(open(R / f"episodes/{e['id']}.json")); p = cfg.get("posting"); leg = render_posting(cfg)
        nome = num["quadros"][e["quadro"]]["nome"]
        d = dia + dt.timedelta(days=k // len(slots)); hh = slots[k % len(slots)]; k += 1
        pacote.append({
            "id": e["id"], "quadro": nome, "numero": e["numero"], "titulo": e["titulo"],
            "referencia": e["referencia"], "hook": p["hook"], "resumo": p["resumo"],
            "pergunta": p["pergunta"], "hashtags": p["hashtags"],
            "legendas": {"tiktok": leg["tiktok"], "instagram": leg["instagram"], "youtube_titulo": leg["youtube_titulo"], "youtube_descricao": leg["youtube_descricao"]},
            "arquivos": "NAO VERIFICADO: link da pasta no Drive nao registrado aqui (esta no indice do Drive)",
            "sugestao_horario_brt": f"{d.isoformat()} {hh}",
            "plataformas": {x: {"estado": pub.get(e["id"], {}).get(x, "nao_agendado"), "link": None} for x in PLAT},
            "aprovacao_publicacao": "PENDENTE_DO_DONO"})
    out = R / "publicacao"; out.mkdir(exist_ok=True)
    json.dump({"versao": 1, "aviso": "Horarios sao sugestao. Nada publicado/agendado por esta ferramenta.",
               "sem_pacote": pend, "episodios": pacote},
              open(out / "pacote_v1.json", "w"), ensure_ascii=False, indent=1)
    with open(out / "calendario_v1.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["data_hora_brt", "episodio", "quadro", "titulo", "TikTok", "YouTube", "Instagram"])
        for x in pacote:
            w.writerow([x["sugestao_horario_brt"], x["id"], f"{x['quadro']} {x['numero']}", x["titulo"], "", "", ""])
    print(len(pacote), "episodios;", "pendentes:", pend)

if __name__ == "__main__":
    main()
