"""Portao numerico da capa vertical (sem rede, sem IA). Falha = exit 9 no vnc_cover ANTES de imprimir a capa (nao entregar).
Confere: formato, area segura, legibilidade (contraste), conceito tristeza->luz, quadros nitidos e NAO repeticao (dHash + ids) contra capas anteriores.
Uso offline: python -m agents.vnc_cover_gate register <EP> <capa.jpg> <topo_id> <baixo_id>   (apos a capa ser aprovada/entregue)"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "contracts" / "vnc_cover_registry_v1.json"
W, H = 1080, 1920
SAFE_Y = (300, 1620)          # grade do Instagram
TOP_ROWS, BOT_ROWS = (0, 290), (1650, 1920)   # so quadro de clipe (sem logo/texto)
MIN_CONTRAST_WHITE, MIN_CONTRAST_GOLD = 3.0, 2.5   # texto grande (WCAG AA = 3:1)
MIN_SHARP = 1.5               # E02 aprovado: topo 4,2 / base 5,1
MIN_DHASH_DIST = 12           # de 128 bits (2 regioes x 64): capa nova nao pode parecer uma anterior
GOLD_LUM, WHITE_LUM = 0.60, 0.90


def lin(c):
    c = np.asarray(c, dtype=float) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def rel_lum(rgb):
    r = lin(rgb); return float(0.2126 * r[..., 0] + 0.7152 * r[..., 1] + 0.0722 * r[..., 2]) if r.ndim == 1 else float((0.2126 * r[..., 0] + 0.7152 * r[..., 1] + 0.0722 * r[..., 2]).mean())


def contrast(l1, l2):
    a, b = max(l1, l2), min(l1, l2); return (a + 0.05) / (b + 0.05)


def sharp(a):
    g = a.mean(axis=2); return float(np.abs(np.diff(g, axis=0)).mean() + np.abs(np.diff(g, axis=1)).mean())


def dhash(a):
    im = Image.fromarray(a.astype("uint8")).convert("L").resize((9, 8), Image.LANCZOS); g = np.asarray(im, dtype=float)
    return "".join("1" if x else "0" for x in (g[:, 1:] > g[:, :-1]).flatten())


def region_hashes(img):
    a = np.asarray(img.convert("RGB"), dtype=float)
    return dhash(a[TOP_ROWS[0]:TOP_ROWS[1]]) + dhash(a[BOT_ROWS[0]:BOT_ROWS[1]])


def ham(a, b): return sum(x != y for x, y in zip(a, b))


def load_registry(p=REG):
    return json.loads(Path(p).read_text(encoding="utf8")) if Path(p).exists() else {"covers": {}}


def check(cfg, img, metrics, reg=None, strict=True):
    """metrics (do vnc_cover): y_bottom, widths[], kicker, lines, band_lum (luminancia relativa do fundo atras do titulo, sem texto)."""
    errs, ep = [], cfg["id"]
    if img.size != (W, H): errs.append(f"formato {img.size} != {W}x{H}")
    if metrics["y_top"] < SAFE_Y[0] or metrics["y_bottom"] > SAFE_Y[1]: errs.append(f"texto fora da area segura (y {metrics['y_top']:.0f}-{metrics['y_bottom']:.0f}; seguro {SAFE_Y})")
    if max(metrics["widths"]) > 0.88 * W: errs.append(f"linha de texto larga demais ({max(metrics['widths']):.0f}px > {0.88 * W:.0f})")
    ok_kick = {f"EPISÓDIO {cfg.get('cover_number', cfg['number']):02d}"}   # legado
    try:
        from agents import vnc_naming as _N
        ok_kick.add(_N.kicker(ep))   # padrao unico atual: "<QUADRO> · EPISÓDIO <N>"
    except Exception: pass
    if metrics["kicker"] not in ok_kick: errs.append("kicker nao confere com o numero do episodio")
    if metrics["lines"] != 3: errs.append(f"titulo com {metrics['lines']} linhas (exige 3)")
    cw, cg = contrast(WHITE_LUM, metrics["band_lum"]), contrast(GOLD_LUM, metrics["band_lum"])
    if cw < MIN_CONTRAST_WHITE or cg < MIN_CONTRAST_GOLD: errs.append(f"contraste baixo atras do titulo (branco {cw:.1f}, dourado {cg:.1f})")
    a = np.asarray(img.convert("RGB"), dtype=float)
    t, b = a[TOP_ROWS[0]:TOP_ROWS[1]], a[BOT_ROWS[0]:BOT_ROWS[1]]
    if sharp(t) < MIN_SHARP or sharp(b) < MIN_SHARP: errs.append(f"quadro sem nitidez (topo {sharp(t):.1f}, base {sharp(b):.1f})")
    if rel_lum(t) >= rel_lum(b): errs.append("conceito tristeza->luz perdido: o topo precisa ser mais escuro que a base")
    if len(set(metrics.get("cover_ids", []))) != 2: errs.append("quadros do topo e da base devem ser de clipes diferentes")
    if strict:
        reg = reg if reg is not None else load_registry(); hh = region_hashes(img)
        for oep, c in reg.get("covers", {}).items():
            if oep == ep: continue
            if c.get("dhash") and ham(hh, c["dhash"]) < MIN_DHASH_DIST: errs.append(f"capa parecida demais com a de {oep} (distancia {ham(hh, c['dhash'])} < {MIN_DHASH_DIST})")
            if set(map(str, metrics.get("cover_ids", []))) & set(map(str, c.get("ids", []))): errs.append(f"quadro de capa ja usado na capa de {oep}")
    return errs


def register(ep, img_path, ids, p=REG):
    reg = load_registry(p); reg.setdefault("covers", {})[ep] = {"dhash": region_hashes(Image.open(img_path)), "ids": [str(i) for i in ids]}
    Path(p).write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf8")


if __name__ == "__main__":
    if sys.argv[1] == "register": register(sys.argv[2], sys.argv[3], sys.argv[4:6]); print("VNC_COVER_REGISTERED", sys.argv[2])
