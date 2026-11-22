"""Identidade fixa VNC (regras travadas). Fonte unica das constantes do estilo aprovado do E01.

Tudo que o dono aprovou como "o padrao do canal" mora aqui e e conferido contra
contracts/vnc_style_lock_v1.json: logo (posicao/tamanho/opacidade/animacao do final), final de cinema (tempos),
legenda (posicao, fonte, karaoke lilas), creditos/CTA e cadeia de audio/video. Mudar o lock = mudar a identidade do canal:
so com pedido expresso do dono. Modulo puro (so stdlib): roda nos testes e no build.
"""
import hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "contracts" / "vnc_style_lock_v1.json"

W, H = 1080, 1920
TAIL_HOLD = 3.0           # s do ultimo clipe apos a voz
TAIL_BLACK = 6.5          # s de preto com a logo/CTA
LOGO_TOP_SIZE, LOGO_TOP_Y, LOGO_TOP_ALPHA = 210, 105, 0.8
LOGO_END_SIZE, LOGO_END_CENTER_Y = 600, 0.39
LOGO_GROW_START, LOGO_GROW_DUR = 0.5, 2.4              # relativo ao fim da voz
LOGO_DARK_FADE_START, LOGO_DARK_FADE_DUR = 1.5, 0.9
LOGO_LIGHT_FADE_START, LOGO_LIGHT_FADE_DUR = 1.6, 1.0
KARAOKE_HIGHLIGHT = "&H00F2B0C4"                        # lilas
CAPTION_BASE = "&H00EEF1F2"
CREDIT = dict(start=3.4, end_from_T=0.9, fad=(800, 900))
CTA1 = dict(start=4.5, end_from_T=1.0, fad=(700, 800))
CTA2 = dict(start=6.0, end_from_T=1.0, fad=(700, 800))

STYLE_TEMPLATES = (  # {fam} = fonte da legenda
    "Style: Credit,{fam},40,&H00D8D8E6,&H00D8D8E6,&H00141210,&H00000000,0,0,0,0,100,100,2,0,1,0,0,8,90,90,1090,1",
    "Style: CTA1,{fam},60,&H00EEF1F2,&H00EEF1F2,&H00141210,&H00000000,-1,0,0,0,100,100,0.6,0,1,0,0,8,90,90,1205,1",
    "Style: CTA2,{fam},50,&H00F2B0C4,&H00F2B0C4,&H00141210,&H00000000,-1,0,0,0,100,100,0.6,0,1,0,0,8,90,90,1330,1",
)


def ts(x):
    return f"0:{int(x // 60):02d}:{x % 60:05.2f}"


def _sec(x):
    h, mi, se = x.split(":"); return int(h) * 3600 + int(mi) * 60 + float(se)


def finalize_ass(at, adur, T, reference, cta, cap_lead, final):
    """Legenda karaoke (do pipeline) -> ASS final: estilos de credito/CTA, dialogos do final de cinema, lead, sem marca de QA."""
    fam = re.search(r"Style: Caption,([^,]+),", at)[1]
    at = at.replace(",8,90,90,118,1", ",2,90,90,40,1")
    at = re.sub(r"(Dialogue: 1,0:00:00\.00,)(\S+?)(,QA)", lambda m: m[1] + f"0:01:{T - 60:05.2f}" + m[3], at, count=1)
    if "[Events]" in at:
        at = at.replace("[Events]", "\n".join(s.format(fam=fam) for s in STYLE_TEMPLATES) + "\n\n[Events]", 1)
    def line(st, d, text):
        return f"Dialogue: 2,{ts(adur + d['start'])},{ts(T - d['end_from_T'])},{st},,0,0,0,,{{\\fad({d['fad'][0]},{d['fad'][1]})}}{text}\n"
    at = at.rstrip("\n") + "\n" + line("Credit", CREDIT, reference) + line("CTA1", CTA1, cta[0]) + line("CTA2", CTA2, cta[1])
    def _shift(m):
        a, b = max(0.0, _sec(m[1]) - cap_lead), max(0.0, _sec(m[2]) - cap_lead)
        return f"Dialogue: 0,{ts(a)},{ts(b)},Caption,"
    at = re.sub(r"Dialogue: 0,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),Caption,", _shift, at)
    if final:
        at = re.sub(r"Dialogue: 1,[^\n]*,QA,[^\n]*\n?", "", at)
    return at


def final_filter(adur, T, t0, ass_path):
    return (f"[0:v]fade=t=out:st={adur + 0.6:.2f}:d=2.4:color=black,tpad=stop_mode=add:stop_duration={TAIL_BLACK}:color=black[bv];"
            f"[2:v]format=rgba,fade=t=in:st=0.5:d=1.0:alpha=1[ls];"
            f"[4:v]format=rgba,setpts=PTS+{t0:.3f}/TB[lq];"
            f"[bv][ls]overlay=eof_action=pass:format=gbrp:enable='lt(t,{t0:.3f})'[o1];"
            f"[o1][lq]overlay=eof_action=pass:format=gbrp[ov];"
            f"[ov]ass={ass_path}:original_size={W}x{H}:fontsdir=assets/fonts,fade=t=out:st={T - 1.2:.2f}:d=1.2,format=yuv420p[v];"
            f"[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,apad,atrim=0:{T:.2f},asplit=2[vo][vk];"
            f"[3:a]aresample=48000,loudnorm=I=-26:TP=-3:LRA=7,aresample=48000,atrim=0:{T:.2f},afade=t=in:st=0:d=2.5,volume='1+1.2*clip((t-{adur:.2f})/2.5,0,1)':eval=frame[m];"
            f"[m][vk]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=500[md];"
            f"[md]afade=t=out:st={T - 3.5:.2f}:d=3.5[mf];"
            f"[vo][mf]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.95[a]")


def skeleton(fc, ass_path, adur, T, t0):
    """Cadeia de filtros com so os valores que dependem do episodio (tempos e caminho) trocados por marcas; o resto (loudnorm, overlay, fades fixos...) fica travado."""
    dyn = {f"{adur + 0.6:.2f}": "<A06>", f"{T - 1.2:.2f}": "<TM12>", f"{T - 3.5:.2f}": "<TM35>", f"{T:.2f}": "<T>", f"{adur:.2f}": "<A>", f"{t0:.3f}": "<T0>"}
    out = fc.replace(str(ass_path), "<ASS>")
    for k in sorted(dyn, key=len, reverse=True):
        out = out.replace(k, dyn[k])
    return out


def constants():
    return {
        "frame": [W, H], "tail_hold": TAIL_HOLD, "tail_black": TAIL_BLACK,
        "logo_top": [LOGO_TOP_SIZE, LOGO_TOP_Y, LOGO_TOP_ALPHA],
        "logo_end": [LOGO_END_SIZE, LOGO_END_CENTER_Y, LOGO_GROW_START, LOGO_GROW_DUR],
        "logo_fades": [LOGO_DARK_FADE_START, LOGO_DARK_FADE_DUR, LOGO_LIGHT_FADE_START, LOGO_LIGHT_FADE_DUR],
        "karaoke": [KARAOKE_HIGHLIGHT, CAPTION_BASE],
        "credit_cta": [CREDIT, CTA1, CTA2], "styles": list(STYLE_TEMPLATES),
    }


def _norm_events(at, adur, T):
    """Dialogos de credito/CTA com tempos relativos a voz/fim (independente do episodio e do texto)."""
    out = []
    for m in re.finditer(r"Dialogue: 2,(\S+?),(\S+?),(\w+),,0,0,0,,(\{\\fad\([^)]*\)\})", at):
        out.append([m[3], round(_sec(m[1]) - adur, 2), round(T - _sec(m[2]), 2), m[4]])
    return out


def make_lock(final_ass, adur, T, fc, ass_path, t0, logo_sig=None):
    cap = re.search(r"^Style: Caption,.*$", final_ass, re.M)[0]
    return {"_aviso": "Identidade fixa do canal (aprovada pelo dono no E01). Mudar so com pedido expresso do dono.",
            "constants": constants(), "caption_style": cap, "events": _norm_events(final_ass, adur, T),
            "filter_skeleton_sha256": hashlib.sha256(skeleton(fc, ass_path, adur, T, t0).encode()).hexdigest(), "logo_signature": logo_sig}


def load_lock():
    return json.loads(LOCK_PATH.read_text(encoding="utf8"))


def check_constants(lock=None):
    lock = lock or load_lock()
    return [] if json.loads(json.dumps(constants())) == lock["constants"] else ["style_lock: constantes do codigo diferem do lock aprovado"]


def check_final_ass(at, adur, T, lock=None):
    lock = lock or load_lock(); errs = []
    cap = re.search(r"^Style: Caption,.*$", at, re.M)
    if not cap or cap[0] != lock["caption_style"]:
        errs.append("legenda: estilo Caption (fonte/tamanho/posicao/cores) diferente do padrao")
    fam = re.search(r"Style: Caption,([^,]+),", at)
    for t in lock["constants"]["styles"]:
        if fam and t.format(fam=fam[1]) not in at:
            errs.append(f"estilo ausente/alterado: {t.split(',')[0]}")
    if _norm_events(at, adur, T) != lock["events"]:
        errs.append("final de cinema: tempos/efeitos de Credito/CTA diferem do padrao")
    caps = re.findall(r"^Dialogue: 0,(\S+?),(\S+?),Caption,,0,0,0,,(.*)$", at, re.M)
    if len(caps) < 20:
        errs.append("legenda: poucos eventos Caption")
    hi = [c for c in caps if KARAOKE_HIGHLIGHT in c[2]]
    if len(hi) < 0.6 * len(caps):
        errs.append("legenda: karaoke lilas ausente em muitos eventos (so pausas entre palavras podem ficar sem destaque)")
    if any(c[2].count(KARAOKE_HIGHLIGHT) != 1 for c in hi):
        errs.append("legenda: destaque karaoke precisa marcar exatamente uma palavra por evento")
    if any(_sec(c[1]) > adur + 0.3 for c in caps):
        errs.append("legenda: evento depois do fim da voz")
    if any(c[2].count("\\N") > 1 for c in caps):
        errs.append("legenda: mais de 2 linhas")
    if ",QA," in at:
        errs.append("marca de QA presente no final")
    return errs


def check_filter(fc, ass_path, adur, T, t0, lock=None):
    lock = lock or load_lock()
    return [] if hashlib.sha256(skeleton(fc, ass_path, adur, T, t0).encode()).hexdigest() == lock["filter_skeleton_sha256"] else ["cadeia de audio/video (filtros) difere do padrao"]


def logo_signature(d):
    """Assinatura geometrica das camadas da logo (caixa + opacidade media de quadros amostrados): robusta a diferencas de arredondamento."""
    import numpy as np
    from PIL import Image
    d = Path(d); frames = sorted(d.glob("f_*.png")); picks = [d / "static.png"] + frames[::8] + [frames[-1]]
    sig = []
    for p in picks:
        a = np.asarray(Image.open(p).convert("RGBA"))[..., 3]; ys, xs = np.where(a > 16)
        sig.append([int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()), round(float(a.mean()), 2)] if len(xs) else [0, 0, 0, 0, 0.0])
    return {"n_frames": len(frames), "boxes": sig}


def check_logo(d, adur, T, lock=None, tol_px=1, tol_mean=1.0):
    lock = lock or load_lock(); want = lock.get("logo_signature")
    if not want:
        return []
    got = logo_signature(d)
    if got["n_frames"] != want["n_frames"] or len(got["boxes"]) != len(want["boxes"]):
        return ["logo: numero de quadros da animacao difere do padrao"]
    for g, w in zip(got["boxes"], want["boxes"]):
        if any(abs(a - b) > tol_px for a, b in zip(g[:4], w[:4])) or abs(g[4] - w[4]) > tol_mean:
            return ["logo: posicao/tamanho/opacidade das camadas diferem do padrao"]
    return []


def apply_quadro_color(at, color):
    """Cor propria do destaque karaoke para um QUADRO (ex.: Fora do Contexto). Chamar DEPOIS de check_final_ass (o lock continua valendo para o padrao).
    So troca a tag de destaque das legendas; estilos CTA/Credito e demais episodios (sem 'karaoke_color') nao mudam."""
    if not color: return at
    if not re.fullmatch(r"&H00[0-9A-F]{6}", color) or color == KARAOKE_HIGHLIGHT: raise ValueError("karaoke_color invalida: use &H00BBGGRR diferente do lilas")
    return at.replace("{\\1c" + KARAOKE_HIGHLIGHT + "&}", "{\\1c" + color + "&}")
