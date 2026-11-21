"""Agente-mestre de portoes do Runflow: confere CADA bloco e trava o fluxo se algo falhar (sem IA, sem gasto).
  pre  <EP>            roteiro -> voz -> postagem            (antes da montagem)
  post <EP> <report>   montagem -> legenda/alinhamento -> video -> musica (depois da montagem)
Regras de duracao/gancho (65-70 s) valem do E03 em diante; E01/E02 so avisam."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAIL_S = 9.5
BAND = (62.0, 72.0)
PLAT_LIMITS = {"tiktok": 2200, "youtube_titulo": 100, "youtube_descricao": 5000, "instagram": 2200}


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
    return errs


def render_posting(cfg):
    p, ref, title = cfg["posting"], cfg["reference"], " ".join(cfg["title_lines"])
    tags = " ".join(p["hashtags"]); hook = p["hook"].upper()
    return {
        "tiktok": f"{hook} {p['resumo']} {p['pergunta']} {tags}",
        "instagram": f"{hook}\n\n{p['resumo']}\n\n{p['pergunta']} Conte nos comentários.\n\n💬 Comente\n📩 Envie para alguém que está esperando\n🔖 Salve para voltar depois\n\n{tags}",
        "youtube_titulo": f"{p.get('titulo_curto') or hook.rstrip('?')} | {ref}"[:100],
        "youtube_descricao": f"{ref}: {p['resumo']}\n\n{p['pergunta']} Conte nos comentários e inscreva-se no canal.\n\n{tags} #Shorts",
    }


def render_posting_file(ep, cfg):
    t = render_posting(cfg)
    return (f'VERBO NO CHÃO — {ep} "{" ".join(cfg["title_lines"])}" — {cfg["reference"]}\nLEGENDAS DE POSTAGEM POR PLATAFORMA (publicar é decisão do dono)\n\n'
            f'=== TIKTOK ({len(t["tiktok"])} caracteres) ===\n{t["tiktok"]}\n\n=== INSTAGRAM REELS ===\n{t["instagram"]}\n\n'
            f'=== YOUTUBE SHORTS ===\nTítulo ({len(t["youtube_titulo"])} caracteres):\n{t["youtube_titulo"]}\n\nDescrição:\n{t["youtube_descricao"]}\n')


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
    m = report.get("music") or {}
    if f and m.get("seconds") and m["seconds"] < f.get("seconds", 0): errs.append("MUSICA: trilha mais curta que o video")
    return errs


def main(argv):
    cmd, ep = argv[0], argv[1]
    errs = pre(ep) if cmd == "pre" else post(ep, json.loads(Path(argv[2]).read_text(encoding="utf8")))
    for e in errs: print("VNC_PIPELINE_FAIL", e)
    if cmd == "post" and not errs and _cfg(ep).get("posting"):
        print("VNC_POSTING_BEGIN"); print(render_posting_file(ep, _cfg(ep))); print("VNC_POSTING_END")
    print("VNC_PIPELINE_OK" if not errs else f"VNC_PIPELINE_BLOCKED {len(errs)}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
