"""Agente-mestre de portoes do Runflow: confere CADA bloco e trava o fluxo se algo falhar (sem IA, sem gasto).
  pre  <EP>            roteiro -> voz -> postagem            (antes da montagem)
  post <EP> <report>   montagem -> legenda/alinhamento -> video -> musica (depois da montagem)
Regras de duracao/gancho (65-70 s) valem do E03 em diante; E01/E02 so avisam."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAIL_S = 9.5
BAND = (62.0, 72.0)
PLAT_LIMITS = {"tiktok": 400, "youtube_titulo": 60, "youtube_descricao": 5000, "instagram": 2200}   # modelo E01 aprovado: TikTok ~340, titulo YouTube <=60
MAX_HASHTAGS = 5


def _cfg(ep, root=ROOT):
    return json.loads((root / "episodes" / f"{ep}.json").read_text(encoding="utf8"))


def strict(cfg):
    return (cfg.get("number") or 99) >= 3


def bloco_postagem(cfg):
    p = cfg.get("posting")
    if not p:
        return ["POSTAGEM: falta o bloco 'posting' em episodes/<EP>.json"] if strict(cfg) else []
    errs = []
    for k in ("hook", "resumo", "pergunta", "hashtags"):
        if not p.get(k):
            errs.append(f"POSTAGEM: falta '{k}'")
    if errs:
        return errs
    t = render_posting(cfg)
    for k, lim in PLAT_LIMITS.items():
        if len(t[k]) > lim:
            errs.append(f"POSTAGEM: {k} com {len(t[k])} > {lim} caracteres")
    if len(p["hashtags"]) > MAX_HASHTAGS:
        errs.append(f"POSTAGEM: {len(p['hashtags'])} hashtags > {MAX_HASHTAGS}")
    return errs


def render_posting(cfg):
    p, ref, title = cfg["posting"], cfg["reference"], " ".join(cfg["title_lines"])
    tags = " ".join(p["hashtags"]); hook = p["hook"].upper()
    return {
        "tiktok": f"{hook} {p['resumo']} {p['pergunta']} {tags}",
        "instagram": f"{hook}\n\n{p['resumo']}\n\n{p['pergunta']} Conte nos comentários.\n\n💬 Comente\n📩 Envie para alguém que está esperando\n🔖 Salve para voltar depois\n\n{tags}",
        "youtube_titulo": f"{p.get('titulo_curto') or hook.rstrip('?')} | {ref}",
        "youtube_descricao": f"{ref}: {p['resumo']}\n\n{p['pergunta']} Conte nos comentários e inscreva-se no canal.\n\n{tags} #Shorts",
    }


def render_posting_file(ep, cfg):
    t = render_posting(cfg)
    return (f'VERBO NO CHÃO — {ep} "{" ".join(cfg["title_lines"])}" — {cfg["reference"]}\nLEGENDAS DE POSTAGEM POR PLATAFORMA (publicar é decisão do dono)\n\n'
            f'=== TIKTOK ({len(t["tiktok"])} caracteres) ===\n{t["tiktok"]}\n\n=== INSTAGRAM REELS ===\n{t["instagram"]}\n\n'
            f'=== YOUTUBE SHORTS ===\nTítulo ({len(t["youtube_titulo"])} caracteres):\n{t["youtube_titulo"]}\n\nDescrição:\n{t["youtube_descricao"]}\n')


def pre_voice(ep, root=ROOT, review=None):
    """Nada de gastar credito antes de provar que o resto da linha fecha: roteiro, postagem e 12 clipes ja selecionados/registrados."""
    from agents import vnc_gates as GT
    cfg, errs = _cfg(ep, root), []
    if review is None:
        from agents import vnc_script_review as R; review = R.review
    rep = review(ep)
    if rep["status"] == "REPROVADO": errs += [f"ROTEIRO: {i['code']} {i['msg']}" for i in rep["issues"]]
    errs += bloco_postagem(cfg)
    if strict(cfg):
        sp = root / (cfg.get("selection") or f"contracts/{ep.lower()}_scene_clip_selection.json")
        if not sp.exists(): errs.append("CLIPES: selecao de 12 clipes ausente (rode a curadoria antes da voz)")
        else: errs += ["CLIPES: " + e for e in GT.check_selection(json.loads(sp.read_text(encoding="utf8")), ep, GT.load_registry(root / "contracts" / "vnc_clip_registry_v1.json"))]
    return errs


def pre(ep, root=ROOT, review=None, seconds=None):
    import hashlib
    errs, cfg = [], _cfg(ep, root)
    # BLOCO 1 roteiro
    if review is None:
        from agents import vnc_script_review as R; review = R.review
    rep = review(ep)
    if rep["status"] == "REPROVADO":
        errs += [f"ROTEIRO: {i['code']} {i['msg']}" for i in rep["issues"]]
    # BLOCO 2 voz
    v = root / "assets" / "voice" / f"{ep}.mp3"
    if not v.exists():
        errs.append("VOZ: assets/voice/<EP>.mp3 ausente (rode run/voice.json mode=generate)")
    else:
        sha = hashlib.sha256(v.read_bytes()).hexdigest()
        if cfg.get("audio_sha256") != sha:
            errs.append("VOZ: sha256 do arquivo difere do episodes/<EP>.json")
        if strict(cfg):
            if seconds is None:
                from agents.vnc_voice import mp3_seconds as seconds
            total = seconds(v) + TAIL_S
            if not BAND[0] <= total <= BAND[1]:
                errs.append(f"VOZ: video final previsto {total:.1f}s fora de {BAND[0]:.0f}-{BAND[1]:.0f}s")
    # BLOCO 3 postagem
    errs += bloco_postagem(cfg)
    return errs


def _ending_errors(ep, report, cfg):
    """Final de cinema: E01/E02 = A (legado). E03+ = variante da rotacao do contrato, camadas com licenca conferida no build e QA de contraste aprovado."""
    from agents import vnc_endings as EN
    e = report.get("ending") or {}
    if e.get("forced") and strict(cfg): return ["FINAL: variante forcada (ensaio) nao vale em episodio novo"]
    if not strict(cfg):
        return [] if (e.get("variant", "A") == "A" or e.get("forced")) else [f"FINAL: episodio legado deve manter o final A (veio {e.get('variant')})"]
    errs, want = [], EN.choose(ep)
    if e.get("error"): return [f"FINAL: falha na montagem do final {want}: {e['error'][:120]}"]
    if e.get("variant") != want: errs.append(f"FINAL: variante {e.get('variant')} != {want} (rotacao do contrato)")
    if e.get("contract_sha256") != EN.contract_sha(): errs.append("FINAL: contrato de finais diferente do aprovado")
    need = set(str(i) for i in EN.layer_ids(want).values()); have = {str(x.get("id")) for x in e.get("layers", []) if "Free License" in str(x.get("license", ""))}
    if need != have: errs.append(f"FINAL: licenca das camadas de luz nao conferida {sorted(need - have)}")
    q = e.get("qa") or {}
    if not q or q.get("ultimo_quadro_max") is None or any(k.startswith("contraste_") and v < (4.5 if k == "contraste_cta1" else 3.0) for k, v in q.items() if isinstance(v, (int, float))):
        errs.append("FINAL: QA de contraste/preto ausente ou reprovado")
    return errs


def post(ep, report, root=ROOT):
    errs, cfg = [], _cfg(ep, root)
    if report.get("errors"): errs.append(f"MONTAGEM: cenas com erro {report['errors']}")
    if report.get("style_lock_errors"): errs.append(f"ESTILO: {report['style_lock_errors']}")
    f = report.get("final") or {}
    if (f.get("w"), f.get("h")) != (1080, 1920): errs.append(f"VIDEO: formato {f.get('w')}x{f.get('h')} != 1080x1920")
    if strict(cfg) and not BAND[0] <= f.get("seconds", 0) <= BAND[1]: errs.append(f"VIDEO: duracao {f.get('seconds')}s fora de {BAND[0]:.0f}-{BAND[1]:.0f}s")
    a = report.get("align") or {}; cc = a.get("cross_check") or {}
    if not cc: errs.append("LEGENDA: sem conferencia cruzada Whisper small x base")
    else:
        if cc.get("median_abs_start_diff", 9) > 0.08: errs.append(f"LEGENDA: divergencia mediana {cc['median_abs_start_diff']}s > 0.08")
        if cc.get("n_gt_300ms", 99) > 0.05 * max(cc.get("total", 1), 1): errs.append(f"LEGENDA: {cc['n_gt_300ms']} palavras com divergencia > 300ms")
    if a.get("interpolated", 0) > 0.05 * max(a.get("words", 1), 1): errs.append(f"LEGENDA: {a['interpolated']} palavras interpoladas demais")
    errs += _ending_errors(ep, report, cfg)
    m = report.get("music") or {}
    if f and m.get("seconds") and m["seconds"] < f.get("seconds", 0): errs.append("MUSICA: trilha mais curta que o video")
    return errs


def main(argv):
    cmd, ep = argv[0], argv[1]
    errs = pre(ep) if cmd == "pre" else pre_voice(ep) if cmd == "pre-voice" else post(ep, json.loads(Path(argv[2]).read_text(encoding="utf8")))
    for e in errs: print("VNC_PIPELINE_FAIL", e)
    if cmd == "post" and not errs and _cfg(ep).get("posting"):
        print("VNC_POSTING_BEGIN"); print(render_posting_file(ep, _cfg(ep))); print("VNC_POSTING_END")
    print("VNC_PIPELINE_OK" if not errs else f"VNC_PIPELINE_BLOCKED {len(errs)}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
