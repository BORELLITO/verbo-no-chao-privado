"""Agente de VALIDACAO DE ROTEIRO (VNC). Automatico, sem custo, deterministico + conferencia do texto biblico em fonte publica.
Entrada: episodes/<EP>.json. Saida: episodes/<EP>_roteiro_review.json {status, issues[], checks{}, limitacoes}.
Status: APROVADO_AUTOMATICO | REPROVADO | (nunca "aprovado final": aprovacao editorial/teologica final = dono).
Regras travadas do canal: tom cristao sobrio, zero promessa milagrosa/prosperidade, Habacuque c/ injustica coletiva (quando for o livro), 12 cenas,
sem repeticao de roteiro/referencia entre episodios, texto de cada cena pronto para narrar (pt-BR), plano visual por cena.
"""
import json, re, sys, unicodedata, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WPS, PAUSE = 2.6, 1.0
SEC_PER_WORD = 0.379      # calibrado no E02: 214 palavras = 81,16 s de voz (inclui pausas entre cenas)
TAIL_S = 9.5              # final de cinema fixo (voz + 9,5 s)
TOTAL_MIN, TOTAL_MAX = 62.0, 72.0   # regra do dono (2026-11-21): video final entre 65 e 70 s (tolerancia 62-72)
HOOK_MAX_WORDS = 12       # gancho: primeira frase fala-se em <= ~4,5 s
BLOCKS = ["opening", "connection", "biblical_reference", "reflection", "application", "conclusion"]
BOOKS = {"genesis": 50, "exodo": 40, "levitico": 27, "numeros": 36, "deuteronomio": 34, "josue": 24, "juizes": 21, "rute": 4, "1 samuel": 31, "2 samuel": 24, "1 reis": 22, "2 reis": 25,
         "1 cronicas": 29, "2 cronicas": 36, "esdras": 10, "neemias": 13, "ester": 10, "jo": 42, "salmos": 150, "proverbios": 31, "eclesiastes": 12, "cantares": 8, "isaias": 66,
         "jeremias": 52, "lamentacoes": 5, "ezequiel": 48, "daniel": 12, "oseias": 14, "joel": 3, "amos": 9, "obadias": 1, "jonas": 4, "miqueias": 7, "naum": 3, "habacuque": 3,
         "sofonias": 3, "ageu": 2, "zacarias": 14, "malaquias": 4, "mateus": 28, "marcos": 16, "lucas": 24, "joao": 21, "atos": 28, "romanos": 16, "1 corintios": 16, "2 corintios": 13,
         "galatas": 6, "efesios": 6, "filipenses": 4, "colossenses": 4, "1 tessalonicenses": 5, "2 tessalonicenses": 3, "1 timoteo": 6, "2 timoteo": 4, "tito": 3, "filemom": 1,
         "hebreus": 13, "tiago": 5, "1 pedro": 5, "2 pedro": 3, "1 joao": 5, "2 joao": 1, "3 joao": 1, "judas": 1, "apocalipse": 22}
API_BOOK = {"habacuque": "habakkuk", "salmos": "psalms", "joao": "john", "mateus": "matthew", "marcos": "mark", "lucas": "luke", "isaias": "isaiah", "jeremias": "jeremiah",
            "lamentacoes": "lamentations", "miqueias": "micah", "naum": "nahum", "romanos": "romans", "tiago": "james", "hebreus": "hebrews", "proverbios": "proverbs", "eclesiastes": "ecclesiastes",
            "jo": "job", "daniel": "daniel", "amos": "amos", "oseias": "hosea", "joel": "joel", "jonas": "jonah", "malaquias": "malachi", "zacarias": "zechariah", "sofonias": "zephaniah"}
# promessa milagrosa / prosperidade / manipulacao / coercao / politica partidaria / pseudociencia
FORBIDDEN = [
    (r"\b(milagre|milagres|milagroso)\b", "promessa/ideia milagrosa"), (r"\bgarant\w+", "garantia"), (r"\bcertamente (vai|ira|irá)", "certeza de resultado"),
    (r"\bdeus (vai|ira|irá) (resolver|curar|abrir|mudar|dar|libertar|restaurar)", "promessa de intervencao especifica"), (r"\bvoce (vai|ira|irá) (vencer|prosperar|receber|ser curad)", "promessa a pessoa"),
    (r"\b(prosperidade|enriquec|riqueza|dinheiro|bençao financeira|bencao financeira)", "prosperidade/dinheiro"), (r"\b(decrete|declare|reivindique|determine) (a|sua|vitoria|bencao)", "teologia da prosperidade"),
    (r"\b(cura|curado|curada)\b", "promessa de cura"), (r"\b(culpa sua|voce e culpado|falta de fe)\b", "culpabilizacao"), (r"\b(partido|eleicao|presidente|esquerda|direita|bolsonaro|lula)\b", "politica partidaria"),
    (r"\b(compartilhe|marque \d+ pessoas|ou vai)\b.*\b(azar|maldicao)\b", "chantagem espiritual"), (r"\bdeixe de (tomar|usar) (remedio|medicamento)", "risco medico"),
]
WARN = {"VISUAL"}
HEDGES = ("talvez", "pode", "é possível", "nem sempre", "nem toda", "não promete", "sem inventar", "não precisa", "às vezes")
STOP = set("a o as os de da do das dos e em no na nos nas um uma para por com que se ao à é não mais mas seu sua ele ela isso este esta ser foi vai há já também como sobre entre ou".split())


def norm(s):
    return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()


def words(s):
    return [w for w in re.findall(r"[a-zà-ú0-9]+", s.lower()) if w not in STOP and len(w) > 2]


def est_seconds(t):
    return len(t.split()) / WPS + PAUSE


def parse_ref(ref):
    m = re.match(r"^\s*((?:[123]\s*)?[A-Za-zÀ-ú]+)\s+(\d+):(\d+)(?:\s*[–-]\s*(\d+))?\s*$", ref or "")
    if not m:
        return None
    return {"book": norm(m.group(1)).strip(), "ch": int(m.group(2)), "v1": int(m.group(3)), "v2": int(m.group(4) or m.group(3))}


BIBLE_JSON = "https://raw.githubusercontent.com/thiagobodruk/biblia/master/json/acf.json"   # Almeida Corrigida Fiel (pt-BR); lista de 66 livros em ordem canonica


def _get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "vnc-roteiro"}), timeout=40).read()


def fetch_verses(r, getter=None, errors=None):
    """Texto biblico em fonte publica. Tentativas: bible-api.com (Almeida) e JSON ACF no GitHub. Falha => None (NAO VERIFICADO, nunca inventar)."""
    g = getter or _get
    errors = errors if errors is not None else []
    b = API_BOOK.get(r["book"], r["book"])
    try:
        j = json.loads(g(f"https://bible-api.com/{urllib.parse.quote(b)}+{r['ch']}:{r['v1']}-{r['v2']}?translation=almeida"))
        t = " ".join(v.get("text", "") for v in j.get("verses", []))
        if t.strip(): return t
        errors.append("bible-api: vazio")
    except Exception as e:  # noqa
        errors.append("bible-api: " + repr(e)[:80])
    try:
        raw = g(BIBLE_JSON); data = json.loads(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw)
        idx = list(BOOKS).index(r["book"])
        ch = data[idx]["chapters"][r["ch"] - 1]
        t = " ".join(ch[r["v1"] - 1:r["v2"]])
        if t.strip(): return t
        errors.append("acf: vazio")
    except Exception as e:  # noqa
        errors.append("acf: " + repr(e)[:80])
    return None


def other_episodes(ep):
    out = {}
    for f in sorted((ROOT / "episodes").glob("E*.json")):
        if f.stem != ep and re.fullmatch(r"E\d+", f.stem):
            try:
                out[f.stem] = json.loads(f.read_text(encoding="utf8"))
            except Exception:  # noqa
                pass
    return out


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def review(ep, cfg=None, getter=None, others=None, offline=False):
    cfg = cfg or json.loads((ROOT / "episodes" / f"{ep}.json").read_text(encoding="utf8"))
    sc = cfg.get("scenes", []); issues, checks = [], {}
    def bad(code, msg, scene=None):
        issues.append({"code": code, "cena": scene, "msg": msg})
    # 1 estrutura
    checks["cenas"] = len(sc)
    if len(sc) != 12: bad("ESTRUTURA", f"{len(sc)} cenas (exige 12)")
    ids = [s.get("id") for s in sc]
    if ids != [f"S{i:02d}" for i in range(1, len(sc) + 1)]: bad("ESTRUTURA", "ids fora de ordem S01..S12")
    order = [BLOCKS.index(s.get("block")) if s.get("block") in BLOCKS else -1 for s in sc]
    if -1 in order or order != sorted(order): bad("ESTRUTURA", "blocos ausentes ou fora da ordem (opening, connection, biblical_reference, reflection, application, conclusion)")
    if sc and sc[0].get("block") != "opening": bad("ESTRUTURA", "S01 deve abrir com pergunta de identificacao (block opening)", "S01")
    if sc and sc[0].get("text", "").strip()[-1:] != "?": bad("GANCHO", "abertura sem pergunta de identificacao", "S01")
    tl = cfg.get("title_lines") or []
    if len(tl) != 3 or any(not t or "Linha" in t for t in tl): bad("TITULO", "title_lines precisa de 3 linhas reais")
    if not all(isinstance(c, str) and c for c in cfg.get("cta", [])) or len(cfg.get("cta", [])) != 2: bad("CTA", "cta com 2 textos (chamada + pergunta)")
    # 2 duracao/ritmo
    total = 0.0
    for s in sc:
        t = (s.get("text") or "").strip(); d = est_seconds(t); total += d
        if len(t) < 8 or t in ("...", "PREENCHER"): bad("TEXTO", "cena sem texto", s.get("id"))
        if d < 2.0: bad("RITMO", f"cena curta ({d:.1f}s)", s.get("id"))
        if len(t.split()) > 40: bad("RITMO", f"cena longa ({len(t.split())} palavras): quebre em duas frases/cenas", s.get("id"))
    checks["duracao_estimada_s"] = round(total, 1)
    nwords = sum(len((s_.get("text") or "").split()) for s_ in sc)
    total_final = nwords * SEC_PER_WORD + TAIL_S
    checks["palavras"] = nwords; checks["duracao_final_estimada_s"] = round(total_final, 1)
    if sc and not (TOTAL_MIN <= total_final <= TOTAL_MAX):
        bad("DURACAO", f"video final estimado {total_final:.0f}s ({nwords} palavras); regra do dono: 65-70 s (aceita {TOTAL_MIN:.0f}-{TOTAL_MAX:.0f}) = ~{int((65 - TAIL_S) / SEC_PER_WORD)}-{int((70 - TAIL_S) / SEC_PER_WORD)} palavras")
    if sc and total / len(sc) < 4.0 and total_final > TOTAL_MAX: bad("DURACAO", "media <4s por cena (inviavel para 12 clipes)")
    # 2b gancho inicial (regra do dono): trava a pessoa nos primeiros segundos
    if sc:
        first = re.split(r"(?<=[.?!])\s+", (sc[0].get("text") or "").strip())[0]
        fw = first.split(); checks["gancho"] = first
        if len(fw) > HOOK_MAX_WORDS: bad("GANCHO", f"gancho longo ({len(fw)} palavras > {HOOK_MAX_WORDS}): deve caber em ~4 s", "S01")
        if not re.search(r"\b(voc[eê]|seu|sua|te|teu|tua)\b", first.lower()): bad("GANCHO", "gancho sem segunda pessoa (voce): nao conecta com quem assiste", "S01")
        if not (first.endswith("?") or re.match(r"^(e se|e quando|nem|ninguem|nunca|sempre|talvez)\b", norm(first))): bad("GANCHO", "gancho precisa ser pergunta ou afirmacao de choque (e se/nunca/ninguem...)", "S01")
        if re.match(r"^(em|no|na|neste|nesta|hoje|bem-vind|ola|oi)\b", norm(first)): bad("GANCHO", "abertura fraca (contexto/saudacao): comece pela dor do espectador", "S01")
    # 2c variacao do gancho: mesmas 2 primeiras palavras de gancho anterior = molde repetitivo (risco de monetizacao)
    if sc and (cfg.get("number") or 99) >= 3:
        mine = norm(first).split()[:2]
        for oep, o in (others if others is not None else other_episodes(ep)).items():
            osc = o.get("scenes") or [{}]; of = norm(re.split(r"(?<=[.?!])\s+", (osc[0].get("text") or "").strip())[0]).split()[:2]
            if mine and mine == of: bad("GANCHO", f"gancho abre igual ao de {oep} ('{' '.join(mine)}...'): varie a abertura", "S01")
    # 3 tom: proibicoes e cautela
    for s in sc:
        n = norm(s.get("text", ""))
        for rx, why in FORBIDDEN:
            if re.search(rx, n): bad("TOM", f"{why}: '{re.search(rx, n).group(0)}'", s.get("id"))
        if re.search(r"[!]{1,}", s.get("text", "")): bad("TOM", "exclamacao (tom sobrio)", s.get("id"))
        if s.get("text", "").isupper(): bad("TOM", "texto em caixa alta", s.get("id"))
    alltxt = norm(" ".join(s.get("text", "") for s in sc))
    checks["cautela_presente"] = any(h in " ".join(s.get("text", "").lower() for s in sc) for h in HEDGES)
    if not checks["cautela_presente"]: bad("TOM", "sem linguagem de cautela (talvez/pode/nem sempre/sem inventar respostas)")
    # 4 referencia biblica
    r = parse_ref(cfg.get("reference", ""))
    checks["referencia"] = cfg.get("reference")
    if not r: bad("BIBLIA", f"referencia invalida: {cfg.get('reference')}")
    else:
        mx = BOOKS.get(r["book"])
        if not mx: bad("BIBLIA", f"livro desconhecido: {r['book']}")
        elif r["ch"] > mx: bad("BIBLIA", f"capitulo {r['ch']} inexistente em {r['book']} (max {mx})")
        ref_txt = [s for s in sc if s.get("block") == "biblical_reference"]
        if not ref_txt: bad("BIBLIA", "nenhuma cena biblical_reference")
        nums = {1: "um", 2: "dois", 3: "tres", 4: "quatro", 5: "cinco", 6: "seis", 7: "sete", 8: "oito", 9: "nove", 10: "dez"}
        if ref_txt and mx and r["ch"] in nums and nums[r["ch"]] not in norm(" ".join(s["text"] for s in ref_txt)) and str(r["ch"]) not in " ".join(s["text"] for s in ref_txt):
            bad("BIBLIA", f"cenas biblicas nao citam o capitulo ({r['ch']}) da referencia")
        errs = []; verse = None if offline else fetch_verses(r, getter, errs)
        checks["texto_biblico_verificado"] = bool(verse)
        if verse:
            vw = set(words(verse)); sw = words(" ".join(s["text"] for s in ref_txt))
            ov = len([w for w in sw if w in vw or any(w[:5] == x[:5] for x in vw)]) / (len(sw) or 1)
            checks["sobreposicao_lexical_biblia"] = round(ov, 2)
            if ov < 0.12: bad("BIBLIA", f"cenas biblicas quase sem vinculo lexical com o texto ({ov:.2f}); risco de parafrase infiel")
        else:
            checks["nota_biblia"] = "NAO VERIFICADO: fonte biblica inacessivel (nao inventado)"; checks["erros_fonte_biblica"] = errs
        if r["book"] == "habacuque" and "injusti" not in alltxt: bad("BIBLIA", "Habacuque exige o contexto de injustica coletiva")
    # 5 repeticao entre episodios
    for oep, o in (others if others is not None else other_episodes(ep)).items():
        if o.get("reference") == cfg.get("reference"): bad("REPETICAO", f"mesma referencia de {oep}")
        ot = words(" ".join(s.get("text", "") for s in o.get("scenes", [])))
        j = jaccard(words(" ".join(s.get("text", "") for s in sc)), ot)
        checks[f"similaridade_{oep}"] = round(j, 2)
        if j > 0.45: bad("REPETICAO", f"roteiro muito parecido com {oep} (jaccard {j:.2f})")
        osent = {norm(s.get("text", "")) for s in o.get("scenes", [])}
        for s in sc:
            if norm(s.get("text", "")) in osent: bad("REPETICAO", f"frase identica a {oep}", s.get("id"))
    # 6 plano visual por cena
    for s in sc:
        v = s.get("visual") or {}
        if not v.get("queries") or not v.get("mood"): bad("VISUAL", "cena sem plano visual (queries/mood)", s.get("id"))
        if s.get("block") != "conclusion" and "pessoa" in norm(v.get("meaning", "")): bad("VISUAL", "plano pede pessoa (nao ha banco confiavel)", s.get("id"))
    warn = WARN | ({"DURACAO", "GANCHO"} if (cfg.get("number") or 99) <= 2 else set())   # E01 e E02 (anteriores a regra, valida a partir do E03): so aviso
    avisos = [i for i in issues if i["code"] in warn]; issues = [i for i in issues if i["code"] not in warn]   # VISUAL ausente: o motor cai no lexico (aviso, nao bloqueio)
    status = "REPROVADO" if issues else "APROVADO_AUTOMATICO"
    return {"episode": ep, "status": status, "issues": issues, "avisos": avisos, "checks": checks,
            "limitacoes": ["validacao AUTOMATICA de regras do canal + vinculo lexical com o texto biblico; NAO e revisao teologica independente",
                           "parafrase fiel exige leitura humana/teologica: o agente so detecta ausencia de vinculo, promessas, tom e repeticao",
                           "voz e publicacao seguem dependendo do pedido/autorizacao do dono"]}


def main(ep):
    rep = review(ep)
    out = ROOT / "episodes" / f"{ep}_roteiro_review.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf8")
    print("VNC_ROTEIRO_STATUS", rep["status"], "issues", len(rep["issues"]))
    for i in rep["issues"]: print("VNC_ROTEIRO_ISSUE", i["cena"], i["code"], i["msg"])
    print("VNC_ROTEIRO_CHECKS", json.dumps(rep["checks"], ensure_ascii=False))
    return 0 if rep["status"] != "REPROVADO" else 5


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
