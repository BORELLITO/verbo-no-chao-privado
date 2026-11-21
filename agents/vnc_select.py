"""Selecao global da sequencia: beam search sobre as 12+ cenas (nao 'melhor por cena').
Utilidade = soma(pesos * criterios por clipe) + continuidade entre vizinhos. Travas eliminatorias ficam FORA (filtradas antes); nenhuma nota as compensa.
Pesos configuraveis em contracts/vnc_curation_weights_v1.json (justificados em `why_pt`)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTS = {
    "semantic": 1.0,     # fidelidade ao roteiro (palavras-chave do plano + clima + titulo) - criterio dominante
    "technical": 0.6,    # nitidez/resolucao
    "motion": 0.5,       # movimento suave e perceptivel
    "mood_fit": 0.8,     # brilho dentro do clima da unidade
    "duration_fit": 0.5, # clipe cobre a unidade sem sobrar demais
    "continuity": 0.7,   # transicao suave entre vizinhos (brilho/saturacao)
    "variety": 0.9,      # penaliza enquadramento (hash) e tema repetidos entre vizinhos/sequencia
    "originality": 0.3,  # penaliza titulos genericos muito comuns
    "why_pt": {"semantic": "o sentido do trecho manda", "variety": "evita montagem redundante", "continuity": "evita salto de atmosfera sem motivo"},
}
GENERIC = {"nature", "beautiful", "landscape", "view", "scenery", "background"}


def weights():
    p = ROOT / "contracts" / "vnc_curation_weights_v1.json"
    return json.loads(p.read_text(encoding="utf8")) if p.exists() else DEFAULT_WEIGHTS


def hamming(a, b):
    return bin(int(a) ^ int(b)).count("1")


THEMES = ("rain", "drop", "storm", "thunder", "sea", "wave", "ocean", "beach", "fog", "mist", "forest", "tree", "mountain", "hill", "cloud", "sky", "sun", "dawn", "lake", "river", "valley",
          "snow", "candle", "flame", "fire", "hand", "trail", "path", "road", "field", "meadow", "night", "star", "reflection", "waterfall", "dark")


def themes_of(words):
    """Temas (vocabulario fechado) presentes numa lista de palavras/consultas (ex.: 'dark-clouds' -> dark, cloud)."""
    toks = " ".join(w.replace("-", " ") for w in words).lower().split()
    return {t for t in THEMES if any(t in w for w in toks)}


def title_themes(title):
    ws = set(title.lower().split())
    return {t for t in THEMES if any((w in ("hand", "hands") if t == "hand" else t in w) for w in ws)}


def theme(title):
    ws = set(title.lower().split())
    for t in THEMES:
        if any((w in ("hand", "hands") if t == "hand" else t in w) for w in ws):
            return t
    return None


def unary(c, unit, W):
    m = c["m"]
    sem = min(1.0, 0.25 * c.get("kw_hit", 0) + (0.5 if c.get("mood_ok", True) else 0) + (0.25 if unit.get("emotion") and unit["emotion"] != "arco_padrao" and c.get("kw_hit", 0) else 0))
    tech = min(m["sharp"], 12) / 12
    mot = 1.0 - min(abs(m["motion"] - 5.0) / 8.0, 1.0)
    lo, hi = c["mood_range"]; mid = (lo + hi) / 2
    mood = 1.0 - min(abs(m["brightness"] - mid) / (hi - lo + 40), 1.0)
    need = unit.get("duration", 0)
    dur = 1.0 if c["dur"] >= need else max(0.0, c["dur"] / max(need, 0.1))
    if c["dur"] > need * 3:
        dur -= 0.2
    orig = 0.0 if (set(c["title"].lower().split()) & GENERIC) else 1.0
    return (W["semantic"] * sem + W["technical"] * tech + W["motion"] * mot + W["mood_fit"] * mood + W["duration_fit"] * dur + W["originality"] * orig
            - 0.4 * max(0.0, m["saturation"] - 110) / 80 - 0.25 * max(0, m["cut_ratio"] - 4) / 5)


def pair(a, b, W):
    s = 0.0
    s -= W["continuity"] * min(abs(a["m"]["brightness"] - b["m"]["brightness"]) / 90.0, 1.0) * 0.6
    s -= W["continuity"] * min(abs(a["m"]["saturation"] - b["m"]["saturation"]) / 120.0, 1.0) * 0.4
    if hamming(a["phash"], b["phash"]) < 14:
        s -= W["variety"] * 0.8      # mesmo enquadramento seguido
    ta, tb = theme(a["title"]), theme(b["title"])
    if ta and ta == tb:
        s -= W["variety"] * 0.5      # mesmo tema em cenas vizinhas
    return s


def select_sequence(plan, cands_by_scene, beam=400, W=None):
    """Retorna (lista de candidatos escolhidos por cena, utilidade, trace). Sem repeticao de clipe na sequencia. None se alguma cena nao tem candidato."""
    W = W or weights()
    states = [([], 0.0, set())]
    for unit in plan:
        cs = cands_by_scene.get(unit["scene"]) or []
        if not cs:
            return None, 0.0, {"bloqueio": f"{unit['scene']}: sem candidato valido"}
        nxt = []
        for seq, u, used in states:
            for c in cs:
                if (c.get("source", "m"), c["id"]) in used:
                    continue
                g = u + unary(c, unit, W) + (pair(seq[-1], c, W) if seq else 0.0)
                # variedade global: tema usado >2 vezes na sequencia
                th = theme(c["title"])
                if th and sum(theme(x["title"]) == th for x in seq) >= 2:
                    g -= W["variety"] * (0.6 + 0.8 * (sum(theme(x['title']) == th for x in seq) - 1))
                nxt.append((seq + [c], g, used | {(c.get("source", "m"), c["id"])}))
        nxt.sort(key=lambda s: -s[1]); states = nxt[:beam]
        if not states:
            return None, 0.0, {"bloqueio": f"{unit['scene']}: candidatos esgotados pela regra anti-repeticao"}
    seq, u, _ = states[0]
    return seq, round(u, 3), {"beam": beam, "weights": {k: v for k, v in W.items() if k != "why_pt"}}
