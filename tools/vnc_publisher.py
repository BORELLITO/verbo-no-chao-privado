"""Publisher VNC camadas 1-2: pacote de publicacao + calendario. NAO publica nada.
Uso: python tools/vnc_publisher.py [--inicio AAAA-MM-DD] [--slots 12:00,19:00]
Gera publicacao/pacote_v1.json e publicacao/calendario_v1.csv.
Estados por plataforma: nao_agendado -> agendado -> publicado (preenchidos SO pelo dono)."""
import argparse, csv, json, datetime as dt, pathlib
R = pathlib.Path(__file__).resolve().parent.parent
PLAT = ("tiktok", "youtube", "instagram")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inicio", default="2026-11-23")
    ap.add_argument("--slots", default="12:00,19:00")
    a = ap.parse_args()
    slots = a.slots.split(","); dia = dt.date.fromisoformat(a.inicio)
    num = json.load(open(R / "contracts/vnc_numeracao_v1.json"))
    pend, pacote, k = [], [], 0
    for e in num["episodios"]:
        p = json.load(open(R / f"episodes/{e['id']}.json")).get("posting")
        nome = num["quadros"][e["quadro"]]["nome"]
        if not p:
            pend.append(f"{e['id']} {nome} {e['numero']}: sem bloco posting")
            continue
        d = dia + dt.timedelta(days=k // len(slots)); hh = slots[k % len(slots)]; k += 1
        pacote.append({
            "id": e["id"], "quadro": nome, "numero": e["numero"], "titulo": e["titulo"],
            "referencia": e["referencia"], "hook": p["hook"], "resumo": p["resumo"],
            "pergunta": p["pergunta"], "hashtags": p["hashtags"],
            "arquivos": "Drive: pasta do episodio (mp4, srt, capa vertical, legendas txt)",
            "sugestao_horario_brt": f"{d.isoformat()} {hh}",
            "plataformas": {x: {"estado": "nao_agendado", "link": None} for x in PLAT},
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
