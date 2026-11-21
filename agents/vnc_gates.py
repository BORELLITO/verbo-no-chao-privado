"""VNC gates: travas deterministicas do Runflow (sem IA, sem rede). Falha = exit 1 = bloqueia o build.

Uso:
  python -m agents.vnc_gates preflight  <EPISODIO> <selecao.json> [--music <id>]
  python -m agents.vnc_gates workflows
  python -m agents.vnc_gates register   <EPISODIO> <selecao.json> [--music <id> --music-title T]
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "contracts" / "vnc_clip_registry_v1.json"
ALLOWED_SOURCES = {"coverr", "mixkit", "pexels"}
SCENES = [f"S{i:02d}" for i in range(1, 13)]
# chamadas que nunca podem existir no motor (R3/R4 e publicacao sao do dono)
FORBIDDEN_PATTERNS = {
    "R4_voz_nova": [r"api\.elevenlabs\.io/v\d+/text-to-speech", r"creative_generate_speech"],
    "R3_visual_ia": [r"api\.elevenlabs\.io/v\d+/(image|video)", r"creative_generate_(image|video)"],
    "publicacao": [r"googleapis\.com/upload/youtube", r"open\.tiktokapis\.com", r"graph\.facebook\.com", r"graph\.instagram\.com"],
}
WRITE_WORKFLOWS = {"vnc-ingest-voice.yml", "vnc-curate.yml"}  # unico com escrita: grava a voz aprovada
SKIP_SCAN = {"vnc_gates.py", "test_vnc_gates.py"}


def load_registry(path=REGISTRY):
    return json.loads(Path(path).read_text(encoding="utf8"))


def _key(src, cid):
    return (str(src).lower(), str(cid))


def ids_of_other_episodes(reg, episode):
    """Todo clipe (usado ou descartado) de OUTROS episodios: proibido reaproveitar."""
    out = {}
    for ep, d in reg.get("episodes", {}).items():
        if ep == episode:
            continue
        for c in d.get("used", []):
            out[_key(c["source"], c["id"])] = ep
        for lst in d.get("discarded_versions", {}).values():
            for c in lst:
                out[_key(c["source"], c["id"])] = ep
    return out


def check_selection(sel, episode, reg):
    """Retorna lista de erros (vazia = ok)."""
    errs = []
    clips = sel.get("clips") or []
    scenes = [c.get("scene") for c in clips]
    if scenes != SCENES:
        errs.append(f"cenas_invalidas: esperado S01..S12 em ordem, veio {scenes}")
    if sel.get("publication_authorized") not in (False, None):
        errs.append("selecao_autoriza_publicacao")
    seen, other = set(), ids_of_other_episodes(reg, episode)
    used_here = {_key(c["source"], c["id"]) for c in reg.get("episodes", {}).get(episode, {}).get("used", [])}
    for c in clips:
        src, cid = c.get("source"), c.get("id")
        if not src or not cid:
            errs.append(f"{c.get('scene')}: sem source/id"); continue
        if str(src).lower() not in ALLOWED_SOURCES:
            errs.append(f"{c['scene']}: fonte nao permitida {src}")
        low = str(cid).lower()
        if "premium" in low or "-ai-" in low or low.startswith("ai-"):
            errs.append(f"{c['scene']}: clipe premium/IA proibido ({cid})")
        k = _key(src, cid)
        if k in seen:
            errs.append(f"{c['scene']}: clipe repetido dentro do episodio ({src}:{cid})")
        seen.add(k)
        if k in other:
            errs.append(f"{c['scene']}: clipe ja usado/descartado em {other[k]} ({src}:{cid})")
        if k not in used_here:
            errs.append(f"{c['scene']}: clipe nao registrado em episodes.{episode}.used ({src}:{cid}); rode 'register' antes")
    return errs


def check_episode_config(ep, sel, root=ROOT):
    """episodes/<ID>.json completo e coerente com a selecao."""
    f = root / "episodes" / f"{ep}.json"
    if not f.exists():
        return [f"falta episodes/{ep}.json"]
    c = json.loads(f.read_text(encoding="utf8")); errs = []
    for k in ("id", "number", "title_lines", "reference", "timing", "audio_link_file", "music_page", "cta", "selection", "cover"):
        if k not in c:
            errs.append(f"config: falta '{k}'")
    if errs:
        return errs
    if c["id"] != ep: errs.append("config: id difere do episodio")
    if c["timing"] not in ("contract", "whisper"): errs.append("config: timing invalido")
    if len(c["title_lines"]) != 3: errs.append("config: title_lines precisa de 3 linhas")
    if len(c["cta"]) != 2: errs.append("config: cta precisa de 2 textos")
    sha = c.get("audio_sha256", "")
    if c["timing"] == "whisper":
        if not re.fullmatch(r"[0-9a-f]{64}", sha): errs.append("config: audio_sha256 completo (64 hex) obrigatorio")
        sc = c.get("scenes", [])
        if [x.get("id") for x in sc] != SCENES: errs.append("config: scenes S01..S12 obrigatorias")
        elif any(not str(x.get("text", "")).strip() or "..." == str(x.get("text")).strip() for x in sc): errs.append("config: cena sem texto")
    elif not (c.get("audio_sha256_prefix") and c.get("audio_sha256_suffix")) and not sha:
        errs.append("config: falta sha da voz")
    ids = {c_["id"] for c_ in sel.get("clips", [])}
    for pos in ("top", "bottom"):
        if c["cover"].get(pos, [None])[0] not in ids:
            errs.append(f"config: quadro da capa '{pos}' precisa ser clipe da selecao (registrado, sem repeticao)")
    return errs


def check_voice_source(ep, root=ROOT):
    """Producao precisa da voz persistida (assets/voice/<EP>.mp3) ou, enquanto nao ingerida, do link assinado."""
    c = json.loads((root / "episodes" / f"{ep}.json").read_text(encoding="utf8"))
    ok = (root / "assets" / "voice" / f"{ep}.mp3").exists() or (root / c["audio_link_file"]).exists()
    return [] if ok else [f"voz do {ep}: nem assets/voice/{ep}.mp3 nem {c['audio_link_file']}"]


def check_style_lock():
    """Identidade fixa (logo, final de cinema, legenda, karaoke, audio): codigo == lock aprovado."""
    from agents import vnc_style
    return vnc_style.check_constants() if vnc_style.LOCK_PATH.exists() else ["falta contracts/vnc_style_lock_v1.json"]


def check_music(music_id, episode, reg):
    errs = []
    for m in reg.get("music_used", []):
        if str(m.get("id") or m.get("mixkit_id")) == str(music_id) and m.get("episode") != episode:
            errs.append(f"trilha {music_id} ja usada em {m.get('episode')}")
    return errs


def check_workflows(root=ROOT):
    """Cada workflow: permissoes somente leitura, timeout, checkout fixado por SHA, sem cron, sem chamadas proibidas."""
    errs = []
    wf = sorted((root / ".github" / "workflows").glob("*.yml"))
    if not wf:
        errs.append("nenhum workflow")
    for p in wf:
        t = p.read_text(encoding="utf8")
        if re.search(r"^\s*schedule:", t, re.M):
            errs.append(f"{p.name}: cron/schedule proibido")
        want = "write" if p.name in WRITE_WORKFLOWS else "read"
        if not re.search(rf"^permissions:\s*\n\s+contents:\s*{want}\s*$", t, re.M):
            errs.append(f"{p.name}: falta permissions contents: {want}")
        if "timeout-minutes:" not in t:
            errs.append(f"{p.name}: falta timeout-minutes")
        for m in re.finditer(r"uses:\s*actions/checkout@(\S+)", t):
            if not re.fullmatch(r"[0-9a-f]{40}", m.group(1)):
                errs.append(f"{p.name}: checkout sem SHA fixo")
        if "concurrency:" not in t:
            errs.append(f"{p.name}: falta concurrency (execucao duplicada)")
    return errs


def scan_forbidden(root=ROOT):
    errs = []
    for base in ("agents", ".github/workflows"):
        for p in (root / base).rglob("*"):
            if not p.is_file() or p.suffix not in (".py", ".yml") or p.name in SKIP_SCAN:
                continue
            t = p.read_text(encoding="utf8", errors="ignore")
            for rule, pats in FORBIDDEN_PATTERNS.items():
                for pat in pats:
                    if re.search(pat, t):
                        errs.append(f"{rule}: {p.relative_to(root)} casa {pat}")
    return errs


def check_curate_config(root=ROOT):
    """run/curate.json: modo valido; dry-run nunca persiste; simulacao exige dry_run; episodio real nao pode ser 'as_episode' de outro."""
    errs, p = [], root / "run" / "curate.json"
    if not p.exists():
        return ["falta run/curate.json"]
    c = json.loads(p.read_text(encoding="utf8"))
    if c.get("mode", "select") not in ("select", "confirm", "release"):
        errs.append("curate.json: mode invalido")
    if c.get("as_episode") and not c.get("dry_run"):
        errs.append("curate.json: as_episode (simulacao) exige dry_run=true")
    if c.get("mode") == "release" and not c.get("release_run"):
        errs.append("curate.json: release exige release_run")
    return errs


def register(episode, sel, reg, music=None, music_title=None):
    ep = reg.setdefault("episodes", {}).setdefault(episode, {"used": [], "discarded_versions": {}})
    have = {_key(c["source"], c["id"]) for c in ep["used"]}
    for c in sel["clips"]:
        if _key(c["source"], c["id"]) not in have:
            ep["used"].append({"source": c["source"], "id": c["id"], "scene": c["scene"], "version": sel.get("version", "v1")})
    if music:
        reg.setdefault("music_used", []).append({"id": str(music), "title": music_title or "", "episode": episode})
    return reg


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "workflows":
        errs = check_workflows() + scan_forbidden()
    elif cmd == "curate-preflight":
        ep = argv[1]
        errs = check_workflows() + scan_forbidden() + check_style_lock() + ([] if (ROOT / "episodes" / f"{ep}.json").exists() else [f"falta episodes/{ep}.json"]) + check_curate_config()
    elif cmd in ("preflight", "register"):
        ep, selp = argv[1], argv[2]
        music = argv[argv.index("--music") + 1] if "--music" in argv else None
        title = argv[argv.index("--music-title") + 1] if "--music-title" in argv else None
        sel, reg = json.loads(Path(selp).read_text(encoding="utf8")), load_registry()
        if cmd == "register":
            REGISTRY.write_text(json.dumps(register(ep, sel, reg, music, title), ensure_ascii=False, indent=1) + "\n", encoding="utf8")
            print("VNC_GATES_REGISTERED", ep); return 0
        errs = check_selection(sel, ep, reg) + check_episode_config(ep, sel) + check_style_lock() + check_voice_source(ep) + (check_music(music, ep, reg) if music else []) + check_workflows() + scan_forbidden()
    else:
        print(__doc__); return 2
    for e in errs:
        print("VNC_GATES_FAIL", e)
    print("VNC_GATES_OK" if not errs else f"VNC_GATES_BLOCKED {len(errs)}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
