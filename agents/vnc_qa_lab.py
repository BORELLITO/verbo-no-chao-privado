"""Laboratorio de QA (so roda no GitHub; gratuito; sem publicar nem gastar). Tarefas via run/qa.json:
  vision_calibrate : mede o CLIP nos clipes RUINS conhecidos (vetados por revisao) x BONS (selecionados e aprovados) com os prompts atuais e propostos
                     e imprime, por classe, o melhor limiar de veto (maior folga entre ruins e bons). Nao altera nada.
  audio_audit      : mede loudness/pico/clipping/silencio/balanco dos mp4 finais do branch de backfill (E01..E08 no Drive) e imprime a tabela."""
import glob, json, os, re, subprocess, sys, tempfile, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUINS = {  # id Mixkit -> motivo (revisao do agente no E08, 2026-11-22)
    "12025": "cidade a noite com predios iluminados", "20440": "arame farpado em close", "41877": "ciclista em rua de parque/cidade",
    "34945": "vila com telhados sob nuvens", "4107": "ruinas de pedra (templo)"}
POS = ["a cinematic nature video frame", "a cinematic landscape video frame of sky, mountains, forest or water", "pure wild nature with no buildings, roads, people or man-made objects"]
NEG_ATUAL = None  # vem de vnc_vision.NEG
NEG_NOVO_EXTRA = {
    "city": ["houses and rooftops of a small town seen from above", "a person riding a bicycle on a road", "an urban skyline at night with lit buildings", "a paved street or highway with markings"],
    "ruins": ["ancient stone ruins or a temple", "an old stone wall of a building"],
    "fence": ["barbed wire or a metal fence in close-up"],
    "manmade": ["buildings, rooftops or a town", "a road, street or path with markings", "a fence, wire, ruins or other man-made structure", "a person, a bicycle or a vehicle"],
}


def selected_good():
    good = {}
    for f in sorted(glob.glob(str(ROOT / "contracts" / "e0*_scene_clip_selection.json"))):
        d = json.load(open(f, encoding="utf8"))
        for c in d.get("clips", []):
            if str(c["id"]) not in RUINS: good[str(c["id"])] = f"{d.get('episode_id')}{c.get('scene')}"
    return good


def vision_calibrate():
    from agents import vnc_vision as V
    b = V.backend()
    if b is None: print("VNC_QALAB_VISION_INDISPONIVEL", V.unavailable_reason()); return 3
    cache = json.load(open(ROOT / "data" / "curadoria_cache.json", encoding="utf8")).get("clipemb", {})
    ff = _ffmpeg(); emb = {}
    for cid in list(RUINS) + list(selected_good()):
        if cid in cache: emb[cid] = cache[cid]; continue
        try:
            p = Path(tempfile.mkdtemp()) / f"{cid}.mp4"; urllib.request.urlretrieve(f"https://assets.mixkit.co/videos/{cid}/{cid}-360.mp4", p)
            dur = 10.0
            fr = V.clip_frames(p, ff, dur)
            if fr: emb[cid] = V.mean_vec(b.embed_images(fr))
        except Exception as e: print("VNC_QALAB_SEM_EMB", cid, repr(e)[:80])
    pos = b.embed_texts(POS)
    def neg_embs(extra):
        n = {c: list(v) for c, v in V.NEG.items()}
        for c, v in (extra or {}).items(): n.setdefault(c, []).extend(v)
        return {c: b.embed_texts(v) for c, v in n.items()}
    sets = {"atual": neg_embs(None), "novo": neg_embs(NEG_NOVO_EXTRA)}
    good = selected_good(); report = {}
    for nome, ne in sets.items():
        rows = {cid: V.classify(emb[cid], pos, ne)["neg"] for cid in emb}
        report[nome] = rows
        print(f"VNC_QALAB_TABELA {nome} (classe: ruins | bons max)")
        for cl in ne:
            r = {cid: rows[cid].get(cl, 0) for cid in RUINS if cid in rows}; g = {cid: rows[cid].get(cl, 0) for cid in good if cid in rows}
            print(f"  {cl:6s} ruins {json.dumps({k: round(v, 2) for k, v in r.items()})} | bons max {max(g.values(), default=0):.2f} (p95 {sorted(g.values())[int(len(g) * .95) - 1] if g else 0:.2f}, n={len(g)})")
        # melhor limiar por classe vetavel: separa o maximo de ruins mantendo 0 bons vetados
        for cl in ne:
            gmax = max((rows[c].get(cl, 0) for c in good if c in rows), default=0)
            vet = [c for c in RUINS if c in rows and rows[c].get(cl, 0) > gmax]
            print(f"  VNC_QALAB_LIMIAR {nome} {cl}: veto > {gmax:.3f} pega {len(vet)}/{len([c for c in RUINS if c in rows])} ruins {vet}")
    print("VNC_QALAB_JSON", json.dumps(report)[:6000]); return 0


def _ffmpeg():
    import shutil
    return shutil.which("ffmpeg") or __import__("imageio_ffmpeg").get_ffmpeg_exe()


def audio_audit(bf_dir):
    from agents import vnc_audio_qa as A, vnc_naming as N
    reg = N.load(); por = {}
    for e in reg["episodios"]:
        por[(e["quadro"], e["numero"])] = e["id"]
    rows = []
    for mp4 in sorted(Path(bf_dir).glob("backfill/*/*/*.mp4")):
        quadro = "DORES" if "DORES" in mp4.parts[-3] else "FORA"; num = int(re.search(r"EPIS.DIO (\d+)", mp4.parts[-2]).group(1)); ep = por[(quadro, num)]
        voz = ROOT / "assets" / "voice" / f"{ep}.mp3"
        m = A.medir(str(mp4)); v = A.medir(str(voz)) if voz.exists() else None
        erros = A.avaliar(m, v); rows.append((ep, quadro, num, m, erros))
        print("VNC_QALAB_AUDIO", ep, quadro, num, json.dumps(m, ensure_ascii=False), "APROVADO" if not erros else "REPROVADO " + "; ".join(erros))
    return 0


def main(a):
    t = a[1]
    if t == "vision_calibrate": return vision_calibrate()
    if t == "audio_audit": return audio_audit(a[2])
    print("tarefa desconhecida"); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
