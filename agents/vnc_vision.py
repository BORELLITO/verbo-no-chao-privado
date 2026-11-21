"""Analise visual REAL e gratuita dos candidatos: CLIP (openai/clip-vit-base-patch32, open-source) rodando no proprio runner (CPU). Sem API paga, sem envio de midia a terceiros.
O que mede: alinhamento imagem<->descricao da cena (zero-shot) e presenca de classes vetadas (pessoa/rosto, cidade, interior, texto/logo/marca d'agua, render 3D/CGI/cartoon).
O que NAO mede: qualidade estetica final nem deteccao confiavel de video gerado por IA fotorrealista (isso continua sendo revisao humana). Falha de carga => `available()` False e o motor registra 'vision: indisponivel' (nunca finge).
Embeddings medios por clipe ficam no cache (data/curadoria_cache.json: clipemb) => sem reprocessar nem rebaixar."""
import math, subprocess, io

MODEL = "openai/clip-vit-base-patch32"
NEG = {  # classe -> prompts (limiar de eliminacao em THRESH)
    "people": ["a photo of a person", "a close-up of a human face", "a crowd of people"],
    "city": ["a city street with buildings", "skyscrapers in a city", "cars on a road in a town"],
    "indoor": ["an indoor room with furniture", "a kitchen or office interior"],
    "text": ["a screen with text, a logo or a watermark", "a title card with words"],
    "cgi": ["a computer-generated 3D render", "a cartoon or digital illustration", "an AI-generated artificial image"],
}
THRESH = {"people": 0.45, "city": 0.5, "indoor": 0.5, "text": 0.45, "cgi": 0.5}
GENERIC_POS = "a cinematic nature video frame"


def softmax(xs):
    m = max(xs); e = [math.exp(x - m) for x in xs]; z = sum(e)
    return [v / z for v in e]


def cosine(a, b):
    na = math.sqrt(sum(x * x for x in a)) or 1.0; nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def classify(img_emb, pos_embs, neg_embs, scale=100.0):
    """Zero-shot sobre UMA mistura de classes: positivas (descricao da cena) vs cada classe vetada. Retorna {sem, neg:{classe:prob}}.
    sem = massa de probabilidade das positivas; neg[c] = massa da classe c (softmax conjunto => comparavel entre clipes)."""
    names = [("pos", e) for e in pos_embs] + [(c, e) for c, es in neg_embs.items() for e in es]
    probs = softmax([scale * cosine(img_emb, e) for _, e in names])
    sem = sum(p for (n, _), p in zip(names, probs) if n == "pos")
    neg = {}
    for (n, _), p in zip(names, probs):
        if n != "pos":
            neg[n] = neg.get(n, 0.0) + p
    return {"sem": round(sem, 4), "neg": {k: round(v, 4) for k, v in neg.items()}}


def verdict(res, allow=()):
    """Motivo de eliminacao (ou None). `allow` libera classes (ex.: 'people' nunca; cena de maos nao libera rosto)."""
    for c, th in THRESH.items():
        if c in allow:
            continue
        if res["neg"].get(c, 0) > th:
            return f"visual: classe vetada '{c}' ({res['neg'][c]:.2f} > {th})"
    return None


def positives(unit):
    """Descricoes de ingles da cena: significado escrito pelo Claude (visual.meaning_en, se existir) + consultas/preferencias do plano."""
    ps = []
    if unit.get("meaning_en"):
        ps.append(f"a cinematic video frame of {unit['meaning_en']}")
    for q in list(unit.get("queries", []))[:3] + list(unit.get("prefer", []))[:2]:
        ps.append(f"a cinematic landscape video frame of {q.replace('-', ' ')}")
    return ps or [GENERIC_POS]


# ---------- backend real (so no runner) ----------
def to_vec(out, proj_in, proj_out):
    """Compat. de versoes do transformers: get_*_features pode devolver Tensor (<=4.x) ou ModelOutput (5.x). Retorna tensor [n, d] ja projetado.
    proj_in = dimensao de entrada da projecao; proj_out = callable (Linear)."""
    if hasattr(out, "shape"):
        t = out
    else:
        t = getattr(out, "image_embeds", None)
        if t is None: t = getattr(out, "text_embeds", None)
        if t is None: t = getattr(out, "pooler_output", None)
        if t is None: t = out[0]
    if len(t.shape) == 3:          # last_hidden_state -> primeiro token
        t = t[:, 0]
    if t.shape[-1] == proj_in:     # ainda nao projetado
        t = proj_out(t)
    return t


class Clip:
    def __init__(self):
        import torch
        from transformers import CLIPModel, CLIPProcessor
        self.torch = torch
        self.m = CLIPModel.from_pretrained(MODEL).eval(); self.p = CLIPProcessor.from_pretrained(MODEL)

    def embed_images(self, imgs):
        with self.torch.no_grad():
            f = to_vec(self.m.get_image_features(**self.p(images=imgs, return_tensors="pt")), self.m.visual_projection.in_features, self.m.visual_projection)
        return f.tolist()

    def embed_texts(self, texts):
        with self.torch.no_grad():
            f = to_vec(self.m.get_text_features(**self.p(text=texts, return_tensors="pt", padding=True)), self.m.text_projection.in_features, self.m.text_projection)
        return f.tolist()


_BACKEND = {"obj": None, "err": None}


def backend():
    if _BACKEND["obj"] is None and _BACKEND["err"] is None:
        try:
            c = Clip()
            from PIL import Image
            t, i = c.embed_texts(["a test"]), c.embed_images([Image.new("RGB", (224, 224), (90, 90, 90))])   # autoteste: dimensoes e valores finitos
            if len(t[0]) != len(i[0]) or not all(math.isfinite(x) for x in t[0] + i[0]):
                raise RuntimeError(f"autoteste CLIP falhou: dims {len(t[0])}/{len(i[0])}")
            _BACKEND["obj"] = c
        except Exception as e:  # noqa
            _BACKEND["err"] = repr(e)[:120]
    return _BACKEND["obj"]


def unavailable_reason():
    backend()
    return _BACKEND["err"]


def clip_frames(path, ffmpeg, dur, n=3):
    from PIL import Image
    out = []
    for q in (0.2, 0.5, 0.8)[:n]:
        png = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{dur * q:.2f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=-2:224", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
        if png:
            out.append(Image.open(io.BytesIO(png)).convert("RGB"))
    return out


def mean_vec(vs):
    return [sum(c) / len(vs) for c in zip(*vs)]


class Annotator:
    """Anota candidatos com {sem, neg} usando embeddings em cache. Textos embutidos uma vez por conjunto de prompts."""
    def __init__(self, cache, backend_obj=None):
        self.cache = cache.setdefault("clipemb", {}); self.b = backend_obj or backend(); self._t = {}
        self.neg = None

    def _text(self, prompts):
        miss = [p for p in prompts if p not in self._t]
        if miss:
            for p, e in zip(miss, self.b.embed_texts(miss)):
                self._t[p] = e
        return [self._t[p] for p in prompts]

    def annotate(self, c, unit, frames_fn):
        """c: candidato (precisa de c['key']); frames_fn() -> lista de PIL (so chamada se nao ha embedding em cache)."""
        k = c["key"]
        if k not in self.cache:
            fr = frames_fn()
            if not fr:
                return None
            self.cache[k] = [round(x, 4) for x in mean_vec(self.b.embed_images(fr))]
        if self.neg is None:
            self.neg = {c_: self._text(ps) for c_, ps in NEG.items()}
        return classify(self.cache[k], self._text(positives(unit)), self.neg)
