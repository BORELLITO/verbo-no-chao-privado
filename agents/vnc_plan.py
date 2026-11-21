"""Planejamento visual a partir do roteiro aprovado (episodes/<EP>.json -> scenes[].text).

Interpretacao semantica: o ROTEIRO e interpretado pelo Claude (unico componente com compreensao de linguagem) e gravado em episodes/<EP>.json -> scenes[].visual
({meaning, emotion, mood, queries[], prefer[], avoid[], shot, min_seconds}). O motor NAO simula compreensao: sem `visual`, usa um lexico pt-BR deterministico
(palavras-gatilho -> consultas/clima) + o arco padrao, e marca o segmento `interpretation: "lexico"` (menos confiavel) no manifesto.
Travas: >= 12 unidades; cada unidade >= MIN_UNIT_S; roteiro com texto placeholder = bloqueio.
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_CLIPS = 12
MIN_UNIT_S = 2.0   # frase isolada curta e valida (E01 S02 tem 2 s); abaixo disso o corte nao se sustenta
MIN_AVG_S = 4.0    # media por unidade: abaixo, o episodio fica fragmentado demais para 12 clipes
WPS = 2.6  # palavras/s da locucao (estimativa quando nao ha timing real)
PAUSE_S = 1.0

# gatilho pt-BR -> (consultas Mixkit, preferencias, clima, emocao)
LEX = [
    (("chuva", "chover", "molhad", "lagrim", "chorar", "choro"), ["rain", "raindrops", "rainy-day", "water-drops"], ["rain", "drops", "window"], "dark", "tristeza"),
    (("noite", "escur", "trevas", "sozinh", "solid"), ["night", "dark-clouds", "stormy-sky"], ["night", "dark", "clouds"], "dark", "solidao"),
    (("tempestade", "injusti", "violenc", "ferid", "gritar", "clamor"), ["storm", "thunderstorm", "dark-clouds"], ["storm", "dark", "clouds"], "dark", "angustia"),
    (("mar ", "onda", "naufrag", "afog"), ["waves", "sea", "ocean"], ["waves", "stormy", "sea"], "dark", "agitacao"),
    (("esperar", "esperand", "demora", "ate quando", "até quando"), ["fog", "mist", "foggy-forest", "clouds"], ["fog", "mist", "clouds"], "mid", "espera"),
    (("vela", "chama", "luz acesa"), ["candle", "candles", "flame", "campfire"], ["candle", "flame", "fire"], "mid", "intimidade"),
    (("maos", "mãos", "toque", "segur"), ["hands", "hand", "holding"], ["hands", "holding"], "mid", "toque_humano"),
    (("montanha", "caminho", "firme", "rocha", "forca", "força"), ["mountains", "mountain", "hills", "trail"], ["mountain", "trail", "peak"], "mid", "firmeza"),
    (("amanhec", "nascer", "aurora", "novo dia"), ["sunrise", "dawn", "sunbeams", "sunlight"], ["sunrise", "dawn", "sunlight"], "mid", "esperanca"),
    (("descans", "lago", "repous", "libert"), ["lake", "valley", "river", "reflection"], ["lake", "valley", "mountain", "calm"], "bright", "libertacao"),
]
ARC_MOOD = ["dark", "dark", "dark", "mid", "mid", "mid", "mid", "mid", "mid", "mid", "bright", "bright"]  # padrao E01: tristeza -> abertura -> libertacao


def words(text):
    return len(re.findall(r"\w+", text or ""))


def est_seconds(text):
    return round(words(text) / WPS + PAUSE_S, 2)


def lexicon(text, idx, n):
    t = " " + (text or "").lower() + " "
    hits = [(q, p, m, e) for trig, q, p, m, e in LEX if any(x in t for x in trig)]
    mood = ARC_MOOD[min(idx, 11)] if n == 12 else ("dark" if idx < n * .3 else "mid" if idx < n * .75 else "bright")
    if not hits:
        return {"queries": [], "prefer": [], "mood": mood, "emotion": "arco_padrao", "interpretation": "arco_padrao"}
    q, p = [], []
    for h in hits[:3]:
        q += [x for x in h[0] if x not in q]; p += [x for x in h[1] if x not in p]
    return {"queries": q, "prefer": p, "mood": mood, "emotion": hits[0][3], "interpretation": "lexico"}


def build_plan(cfg, arc_template, scene_seconds=None):
    """Retorna (plan, diagnostico). plan = lista de unidades narrativas; diagnostico = [] se apto."""
    scenes = cfg.get("scenes") or []
    diag = []
    if len(scenes) < MIN_CLIPS:
        diag.append(f"INCOMPATIVEL: {len(scenes)} unidades narrativas < minimo {MIN_CLIPS}")
    arc = {s["id"]: s for s in arc_template}
    plan, t = [], 0.0
    for i, sc in enumerate(scenes):
        text = (sc.get("text") or "").strip()
        if len(text) < 8 or text in ("...", "PREENCHER"):
            diag.append(f"{sc.get('id')}: roteiro ausente/placeholder"); continue
        dur = (scene_seconds or {}).get(sc["id"]) or est_seconds(text)
        src = "timing_real" if (scene_seconds or {}).get(sc["id"]) else "estimativa_palavras"
        if dur < MIN_UNIT_S:
            diag.append(f"{sc['id']}: unidade com {dur:.1f}s < {MIN_UNIT_S}s (ritmo inviavel p/ clipe cinematografico)")
        v = sc.get("visual") or {}
        lex = lexicon(text, i, len(scenes))
        base = arc.get(sc["id"], {})
        unit = {"scene": sc["id"], "block": sc.get("block"), "text": text, "start": round(t, 2), "end": round(t + dur, 2), "duration": round(dur, 2), "duration_source": src,
                "meaning": v.get("meaning"), "emotion": v.get("emotion") or lex["emotion"], "mood": v.get("mood") or lex["mood"],
                "queries": list(dict.fromkeys((v.get("queries") or []) + base.get("queries", []) + lex["queries"]))[:14],   # Claude > arco padrao vetado > lexico
                "prefer": list(dict.fromkeys((v.get("prefer") or []) + base.get("prefer", []) + lex["prefer"])),
                "avoid": v.get("avoid", []), "allow": base.get("allow", []) + v.get("allow", []), "shot": v.get("shot"),
                "min_seconds": float(v.get("min_seconds") or max(base.get("min_seconds", 8), round(dur + 0.6, 1))),
                "interpretation": "claude" if v else lex["interpretation"]}
        plan.append(unit); t += dur
    if plan and len(plan) >= MIN_CLIPS and (t / len(plan)) < MIN_AVG_S:
        diag.append(f"INCOMPATIVEL: media {t / len(plan):.1f}s/unidade < {MIN_AVG_S}s (12 clipes fragmentariam o ritmo)")
    return plan, diag


def load_episode(ep):
    cfg = json.loads((ROOT / "episodes" / f"{ep}.json").read_text(encoding="utf8"))
    tpl = json.loads((ROOT / "contracts" / "vnc_arc_template_v1.json").read_text(encoding="utf8"))["scenes"]
    return cfg, tpl
