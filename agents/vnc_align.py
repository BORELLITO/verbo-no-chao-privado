"""Alinhamento generico voz<->roteiro (qualquer episodio). Offline e deterministico, exceto transcribe() (so no runner).

- words_from_scenes: palavras canonicas do roteiro (as 12 cenas concatenadas) + indice de palavra de cada cena.
- align: alinhamento global de edicao entre roteiro e palavras do ASR (reusa align_once do pipeline de legendas).
- cross_check: concordancia entre dois modelos Whisper (small x base); bloqueia se a mediana divergir demais.
- scenes_from_words: fronteiras de cena = inicio da primeira palavra de cada cena (continuo, sem buracos).
"""
import statistics
from agents.e01_v2_caption_pipeline import align_once, norm

SCENE_IDS = [f"S{i:02d}" for i in range(1, 13)]
MAX_UNMATCHED_RATIO = 0.05      # palavras sem correspondencia exata/fonetica no ASR
MAX_EDGE_WORDS = 3
MAX_TRAILING_WORDS = 2
MAX_GAP_INTERP = 0.9            # s: buraco maximo que pode ser interpolado
MAX_MODEL_DISAGREE_MEDIAN = 0.15  # s


class AlignError(RuntimeError):
    pass


def words_from_scenes(scenes):
    """scenes: [{"id": "S01", "text": "..."}]. Retorna (palavras canonicas, indice da 1a palavra de cada cena)."""
    if [s["id"] for s in scenes] != SCENE_IDS:
        raise AlignError("cenas: esperado S01..S12 em ordem")
    words, first = [], []
    for s in scenes:
        toks = s["text"].split()
        if not toks:
            raise AlignError(f"{s['id']}: cena sem texto")
        first.append(len(words))
        for t in toks:
            k = norm(t)
            if not k:
                raise AlignError(f"{s['id']}: token vazio {t!r}")
            words.append({"text": t, "key": k, "scene": s["id"], "block": s.get("block", s["id"])})
    return words, first


def align(canon, asr, duration, strict=True):
    """canon: palavras do roteiro; asr: [{"text","key","start","end"}]. Retorna (palavras com tempo, resumo)."""
    asr = [dict(w, key=w.get("key") or norm(w["text"])) for w in asr if norm(w["text"])]
    got = align_once(canon, asr)
    out, missing = [], 0
    for i, c in enumerate(canon):
        g = got[i]
        if g is None:
            missing += 1
            out.append({**c, "index": i, "start": None, "end": None, "alignment": "INTERPOLATED"})
        else:
            out.append({**c, "index": i, "start": round(max(0.0, g["start"]), 3), "end": round(min(duration, g["end"]), 3), "alignment": g["alignment"]})
    if not strict:  # modelo de conferencia: palavras nao reconhecidas ficam sem tempo e saem da comparacao
        return out, {"words": len(out), "unmatched": missing}
    if missing > max(2, int(MAX_UNMATCHED_RATIO * len(canon))):
        raise AlignError(f"muitas palavras sem correspondencia no ASR: {missing}/{len(canon)}")
    edge = 0; trail = 0
    for i, w in enumerate(out):
        if w["start"] is not None:
            continue
        b = next((out[x] for x in range(i - 1, -1, -1) if out[x]["end"] is not None), None)
        a = next((out[x] for x in range(i + 1, len(out)) if out[x]["start"] is not None), None)
        if b is not None and a is None:
            # palavras finais que o ASR omitiu (ex.: "ou B" no fim da narracao): sem vizinha posterior; ancora logo apos a anterior, dentro da duracao da voz (limite: MAX_TRAILING_WORDS)
            trail += 1
            if trail > MAX_TRAILING_WORDS or b["end"] > duration - 0.15:
                raise AlignError(f"palavra {i} ({w['text']}) sem vizinhas com tempo (final omitido pelo ASR)")
            st = b["end"] + 0.02; en = min(duration, st + 0.3)
            w["start"], w["end"], w["alignment"] = round(st, 3), round(en, 3), "INTERPOLATED_TRAILING"
            continue
        if b is None or a is None:
            raise AlignError(f"palavra {i} ({w['text']}) sem vizinhas com tempo")
        if a["start"] - b["end"] > MAX_GAP_INTERP:
            # buraco grande = pausa longa da narracao (ex.: apos fim de frase) onde o ASR omitiu a palavra: ancora logo apos a vizinha anterior (limite: 3 por episodio)
            edge += 1
            if edge > MAX_EDGE_WORDS:
                raise AlignError(f"buraco grande demais ao interpolar palavra {i} ({w['text']}); {edge} palavras de borda")
            st = b["end"] + 0.02; en = min(a["start"] - 0.05, st + 0.45)
            w["start"], w["end"], w["alignment"] = round(st, 3), round(en, 3), "INTERPOLATED_EDGE"
            continue
        mid = (b["end"] + a["start"]) / 2
        w["start"], w["end"] = round(mid, 3), round(min(duration, mid + 0.04), 3)
    prev = -1.0
    for w in out:
        if not (0 <= w["start"] <= w["end"] <= duration + 0.05) or w["start"] + 0.15 < prev:
            raise AlignError(f"tempo invalido/nao monotonico na palavra {w['index']} ({w['text']})")
        prev = max(prev, w["start"])
    return out, {"words": len(out), "interpolated": missing, "edge_interpolated": edge, "trailing_interpolated": trail, "aliases": sum(w["alignment"] not in ("EXACT", "INTERPOLATED", "INTERPOLATED_EDGE", "INTERPOLATED_TRAILING", "TRAILING_MEASURED_ENERGY") for w in out)}


def cross_check(a, b):
    """Diferenca de inicio por palavra entre dois alinhamentos do mesmo roteiro. Bloqueia se a mediana passar do limite."""
    d = [abs(x["start"] - y["start"]) for x, y in zip(a, b) if x["start"] is not None and y["start"] is not None]
    if len(d) < 0.8 * len(a):
        raise AlignError(f"conferencia cobre so {len(d)}/{len(a)} palavras")
    med = statistics.median(d)
    res = {"median_abs_start_diff": round(med, 3), "p90": round(sorted(d)[int(len(d) * .9)], 3), "n_gt_300ms": sum(x > 0.3 for x in d), "compared": len(d), "total": len(a)}
    if med > MAX_MODEL_DISAGREE_MEDIAN:
        raise AlignError(f"modelos divergem: mediana {med:.3f}s > {MAX_MODEL_DISAGREE_MEDIAN}s")
    return res


def scenes_from_words(words, first_idx, adur):
    """Fronteira = meio da pausa entre a ultima palavra de uma cena e a primeira da seguinte (como o refit aprovado do E01)."""
    starts = [0.0] + [round((words[i - 1]["end"] + words[i]["start"]) / 2, 3) for i in first_idx[1:]]
    ends = starts[1:] + [adur]
    return [{"id": SCENE_IDS[k], "start_seconds": round(starts[k], 3), "end_seconds": round(ends[k], 3),
             "duration_seconds": round(ends[k] - starts[k], 3)} for k in range(len(SCENE_IDS))]


def voiced_spans(samples, sr, t_from, t_to, thresh_db=-38.0, win=0.01, merge_gap=0.06):
    """Trechos com voz medidos na energia do audio (RMS de 10 ms) entre t_from e t_to. Sem modelo: so medicao."""
    import math
    n = int(win * sr); spans = []; cur = None
    i0 = int(max(0.0, t_from) * sr); i1 = min(len(samples), int(t_to * sr))
    for i in range(i0, i1 - n + 1, n):
        seg = samples[i:i + n]
        rms = math.sqrt(sum(float(x) * float(x) for x in seg) / n)
        on = 20 * math.log10(max(rms, 1e-9)) > thresh_db
        t = i / sr
        if on and cur is None: cur = [t, t + win]
        elif on: cur[1] = t + win
        elif cur is not None:
            spans.append(cur); cur = None
    if cur is not None: spans.append(cur)
    merged = []
    for a, b in spans:
        if merged and a - merged[-1][1] <= merge_gap: merged[-1][1] = b
        else: merged.append([a, b])
    return merged


def refine_trailing(words, samples, sr, duration):
    """Palavras finais omitidas pelo ASR (INTERPOLATED_TRAILING): troca o tempo estimado pelo MEDIDO na energia da voz.
    Janela = trechos com voz depois da ultima palavra reconhecida; palavras repartidas por peso (letras+2) dentro dela.
    Retorna (palavras, resumo). Sem voz medida na janela => AlignError (nao inventa tempo)."""
    idx = [i for i, w in enumerate(words) if w.get("alignment") == "INTERPOLATED_TRAILING"]
    if not idx: return words, {"trailing_measured": 0}
    last = next((words[i] for i in range(idx[0] - 1, -1, -1) if words[i].get("end") is not None), None)
    if last is None: raise AlignError("sem palavra reconhecida antes do final omitido")
    spans = voiced_spans(samples, sr, last["end"] + 0.12, duration + 0.05)   # +0.12: fim da palavra anterior (Whisper pode errar ~0.1 s) nao conta como palavra nova
    spans = [sp for sp in spans if sp[1] - sp[0] >= 0.08]
    if not spans: raise AlignError("final omitido pelo ASR e sem voz medida depois da ultima palavra reconhecida")
    n = len(idx)
    if len(spans) >= n:
        pick = spans[-n:] if len(spans) > n else spans
        for k, i in enumerate(idx): words[i]["start"], words[i]["end"] = round(pick[k][0], 3), round(min(duration, pick[k][1]), 3)
    else:
        a, b = spans[0][0], spans[-1][1]; wt = [len(norm(words[i]["text"])) + 2 for i in idx]; tot = sum(wt); t = a
        for k, i in enumerate(idx):
            en = t + (b - a) * wt[k] / tot
            words[i]["start"], words[i]["end"] = round(t, 3), round(min(duration, en), 3); t = en
    for i in idx: words[i]["alignment"] = "TRAILING_MEASURED_ENERGY"
    return words, {"trailing_measured": n, "voiced_spans": [[round(x, 3), round(y, 3)] for x, y in spans]}


def decode_mono16k(audio_path):
    import subprocess, numpy as np, imageio_ffmpeg
    raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(audio_path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, 16000


def transcribe(audio_path, model_size):
    """Somente no runner (faster-whisper + ffmpeg do imageio)."""
    import subprocess, numpy as np, imageio_ffmpeg
    from faster_whisper import WhisperModel
    raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(audio_path), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    m = WhisperModel(model_size, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(audio, language="pt", word_timestamps=True, vad_filter=False, beam_size=5)
    return [{"text": w.word.strip(), "key": norm(w.word), "start": float(w.start), "end": float(w.end), "confidence": float(w.probability)} for s in segs for w in s.words if norm(w.word)]
