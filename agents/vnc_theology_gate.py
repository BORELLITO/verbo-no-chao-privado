"""Agente de aprovacao TEOLOGICA (roteiro) e ESTETICA (video final) do VERBO NO CHAO.
Regra do dono: a aprovacao teologica e estetica e do agente, nao do dono. Nada de voz (gasta credito) nem montagem sem parecer teologico valido.
O agente NAO confia em memoria: cada alegacao do roteiro precisa de dossie pesquisado (fontes https de dominios distintos, versiculos checados no texto biblico).
O dossie fica atrelado ao HASH do texto de cada cena: mudou uma palavra do roteiro => parecer invalido (REFAZER pesquisa).
Uso: python -m agents.vnc_theology_gate theology <EP> | seal <EP> | aesthetic <EP> <sha256_video>"""
import hashlib, json, re, sys, unicodedata, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRST_STRICT = 3
TIPOS = {"textual", "historica", "interpretativa", "aplicacao"}
VEREDITOS = {"SUPORTADO", "SUPORTADO_COM_CAUTELA", "NAO_SUPORTADO"}
HEDGE_AUTOR = ("tradicionalmente", "atribu", "segundo a tradicao", "alguem", "o autor", "o poeta")
AUTORES = r"\b(jeremias|davi|paulo|moises|isaias|salomao|habacuque)\b(?!\s+\d)"   # 'Isaias 41' = titulo do livro, nao afirma autor
SCAN_ABSOLUTO = (r"\b(sempre|nunca|todos|ninguem|tudo)\b", r"\b(prova que|significa exatamente|sem duvida)\b")


def norm(s):
    return re.sub(r"\s+", " ", "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")).strip()


def sha(t): return hashlib.sha256(t.encode("utf8")).hexdigest()[:16]


def domain(u): return (urllib.parse.urlparse(u).hostname or "").lower().removeprefix("www.")


def strict(ep):
    m = re.search(r"(\d+)", ep or ""); return bool(m) and int(m.group(1)) >= FIRST_STRICT


def scene_hashes(cfg): return {s["id"]: sha(s["text"]) for s in cfg["scenes"]}


def dossier_path(ep, root=ROOT): return root / "episodes" / f"{ep}_teologia.json"


def check_theology(ep, root=ROOT, verses=None):
    """verses(ref_str)->texto biblico (None=nao verificado). Retorna (status, erros, avisos)."""
    errs, warns = [], []
    cfg = json.loads((root / "episodes" / f"{ep}.json").read_text(encoding="utf8"))
    p = dossier_path(ep, root)
    if not p.exists(): return "PENDENTE_PESQUISA", [f"dossie teologico ausente: {p.name} (pesquisar fontes e alegacoes antes da voz)"], warns
    d = json.loads(p.read_text(encoding="utf8"))
    if d.get("episode") != ep: errs.append("dossie de outro episodio")
    if d.get("referencia") != cfg.get("reference"): errs.append("referencia do dossie difere da do episodio")
    cur, sealed = scene_hashes(cfg), d.get("cenas_hash") or {}
    for sid, h in cur.items():
        if sealed.get(sid) != h: errs.append(f"{sid}: texto mudou desde a pesquisa (hash) -> refazer o dossie e lacrar")
    claims = d.get("alegacoes") or []
    covered = {c for a in claims for c in a.get("cenas", [])}
    for s in cfg["scenes"]:
        t = norm(s["text"])
        if s["block"] in ("connection", "biblical_reference", "reflection", "conclusion") and s["id"] not in covered:
            errs.append(f"{s['id']}: cena de conteudo sem alegacao pesquisada")
        consenso = {norm(x) for x in (d.get("autoria_consenso") or [])}   # autoria de consenso academico, declarada e selada no dossie
        nomes = {m.group(1) for m in re.finditer(AUTORES, t)}
        if nomes and not nomes <= consenso and not any(h in t for h in HEDGE_AUTOR): errs.append(f"{s['id']}: nomeia autor sem ressalva de tradicao/autoria")
        if re.search(r"\b\d{3,4}\b|seculo", t) and not any(a.get("tipo") == "historica" and s["id"] in a.get("cenas", []) for a in claims):
            errs.append(f"{s['id']}: data/periodo historico sem alegacao 'historica' fontada")
        for pat in SCAN_ABSOLUTO:
            if re.search(pat, t) and not any(s["id"] in a.get("cenas", []) and a.get("veredito") == "SUPORTADO_COM_CAUTELA" for a in claims):
                warns.append(f"{s['id']}: termo absoluto sem alegacao 'com cautela'")
    ids = set()
    for a in claims:
        i = a.get("id", "?")
        if i in ids: errs.append(f"{i}: id duplicado")
        ids.add(i)
        if a.get("tipo") not in TIPOS: errs.append(f"{i}: tipo invalido")
        if a.get("veredito") not in VEREDITOS: errs.append(f"{i}: veredito invalido"); continue
        if a["veredito"] == "NAO_SUPORTADO": errs.append(f"{i}: alegacao NAO SUPORTADA -> reescrever a cena")
        if a["veredito"] == "SUPORTADO_COM_CAUTELA" and len((a.get("mitigacao") or "").strip()) < 20: errs.append(f"{i}: 'com cautela' exige mitigacao concreta")
        if not a.get("cenas") or not set(a["cenas"]) <= set(cur): errs.append(f"{i}: cenas invalidas")
        fontes = a.get("fontes") or []
        urls = [f.get("url", "") for f in fontes]
        if any(not u.startswith("https://") for u in urls): errs.append(f"{i}: fonte sem https")
        need = 1 if a.get("tipo") in ("textual", "aplicacao") else 2
        if len({domain(u) for u in urls if u}) < need: errs.append(f"{i}: exige {need} fonte(s) de dominios distintos")
        if a.get("tipo") in ("historica", "interpretativa") and not any(f.get("tipo") in ("comentario", "enciclopedia", "academico") for f in fontes):
            errs.append(f"{i}: sem fonte de comentario/enciclopedia/academica")
        vs = a.get("versiculos") or []
        if a.get("tipo") == "textual" and not vs: errs.append(f"{i}: alegacao textual sem versiculos")
        if vs and verses:
            txt = " ".join(filter(None, (verses(v) for v in vs)))
            if not txt: errs.append(f"{i}: texto biblico NAO VERIFICADO ({', '.join(vs)})")
            else:
                miss = [k for k in a.get("palavras_chave_no_texto", []) if norm(k) not in norm(txt)]
                if miss: errs.append(f"{i}: palavras-chave ausentes nos versiculos citados: {miss}")
        if not (a.get("risco") or "").strip(): errs.append(f"{i}: risco nao avaliado")
    om = d.get("omissoes_de_contexto") or []
    if not om: errs.append("omissoes_de_contexto vazio: avaliar o que o roteiro deixa de fora (ex.: enquadramento de juizo/pecado, autoria)")
    for o in om:
        if o.get("decisao") not in ("incluir", "ressalvar", "aceitavel") or len((o.get("justificativa") or "").strip()) < 25: errs.append(f"omissao '{o.get('item')}': decisao/justificativa insuficiente")
    if d.get("parecer") != "APROVADO": errs.append("parecer do revisor nao e APROVADO")
    return ("APROVADO_TEOLOGICO" if not errs else "REPROVADO"), errs, warns


def check_aesthetic(ep, video_sha, root=ROOT):
    """Parecer estetico atrelado ao SHA do video entregue. Revisao quadro a quadro das 12 cenas + final + capa (feita pelo agente, nao pelo dono)."""
    p = root / "episodes" / f"{ep}_estetica.json"
    if not p.exists(): return "PENDENTE", ["parecer estetico ausente"]
    d, errs = json.loads(p.read_text(encoding="utf8")), []
    cfg = json.loads((root / "episodes" / f"{ep}.json").read_text(encoding="utf8"))
    if d.get("video_sha256") != video_sha: errs.append("parecer nao corresponde ao video atual (sha256)")
    cenas = {c.get("cena"): c for c in d.get("cenas", [])}
    for s in cfg["scenes"]:
        c = cenas.get(s["id"])
        if not c: errs.append(f"{s['id']}: sem parecer"); continue
        if c.get("veredito") not in ("APROVADO", "APROVADO_COM_RESSALVA", "REPROVADO"): errs.append(f"{s['id']}: veredito invalido")
        if c.get("veredito") == "REPROVADO": errs.append(f"{s['id']}: REPROVADA ({c.get('nota')})")
        if not all(k in c.get("criterios", {}) for k in ("coerencia_texto_imagem", "luz_no_arco", "legenda_legivel", "sem_pessoas_ou_marcas")): errs.append(f"{s['id']}: criterios incompletos")
        if any(v is False for v in c.get("criterios", {}).values()) and c.get("veredito") == "APROVADO": errs.append(f"{s['id']}: criterio falho com veredito APROVADO")
    for k in ("final", "capa", "ritmo_e_transicoes", "audio_voz_e_trilha"):
        if (d.get(k) or {}).get("veredito") not in ("APROVADO", "APROVADO_COM_RESSALVA"): errs.append(f"{k}: sem aprovacao")
    return ("APROVADO_ESTETICO" if not errs else "REPROVADO"), errs


def main(argv):
    cmd, ep = argv[1], argv[2]
    if cmd == "seal":
        p = dossier_path(ep); d = json.loads(p.read_text(encoding="utf8"))
        cfg = json.loads((ROOT / "episodes" / f"{ep}.json").read_text(encoding="utf8"))
        d["cenas_hash"] = scene_hashes(cfg); p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf8"); print("VNC_TEOLOGIA_SEALED", ep); return 0
    if cmd == "theology":
        from agents import vnc_script_review as R
        cfg = json.loads((ROOT / "episodes" / f"{ep}.json").read_text(encoding="utf8"))
        def verses(v):
            r = R.parse_ref(v); return R.fetch_verses(r) if r else None
        st, errs, warns = check_theology(ep, verses=verses)
        print("VNC_TEOLOGIA_STATUS", st)
        for e in errs: print("VNC_TEOLOGIA_ERRO", e)
        for w in warns: print("VNC_TEOLOGIA_AVISO", w)
        return 0 if st == "APROVADO_TEOLOGICO" else 5
    if cmd == "aesthetic":
        st, errs = check_aesthetic(ep, argv[3]); print("VNC_ESTETICA_STATUS", st)
        for e in errs: print("VNC_ESTETICA_ERRO", e)
        return 0 if st == "APROVADO_ESTETICO" else 5
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
