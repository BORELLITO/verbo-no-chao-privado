"""QA de audio do video final feito pela maquina (sem escuta humana): loudness integrado, pico, clipping, silencios longos
e balanco voz x trilha. A conferencia voz == roteiro ja e feita pelo Whisper na montagem (VNC_TIMING).
Uso: python -m agents.vnc_audio_qa <video.mp4> [voz.mp3]   -> imprime VNC_AUDIO_QA {...} e VNC_AUDIO_QA_STATUS APROVADO|REPROVADO
Limites (Shorts/Reels/TikTok): -19 a -12 LUFS integrado, true peak <= -0.5 dBTP, sem clipping, silencio <= 1.6 s no meio."""
import json, re, subprocess, sys

LUFS = (-19.0, -12.0); TP_MAX = -0.5; SIL_MAX = 1.6


def _ff(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True, text=True).stderr


def medir(path):
    e = _ff(["-i", path, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"])
    blk = e.split("Summary:")[-1]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", blk); tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", blk)
    v = _ff(["-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"])
    mx = re.search(r"max_volume:\s+(-?[\d.]+) dB", v)
    s = _ff(["-i", path, "-vn", "-af", "silencedetect=noise=-45dB:d=0.8", "-f", "null", "-"])
    dur = re.search(r"Duration:\s+(\d+):(\d+):([\d.]+)", e)
    total = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3)) if dur else 0
    sil = [(float(a), float(b)) for a, b in re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+)", s)]
    meio = [round(b - a, 2) for a, b in sil if a > 0.5 and b < total - 0.5]
    return {"lufs": float(i.group(1)) if i else None, "true_peak_db": float(tp.group(1)) if tp else None,
            "max_volume_db": float(mx.group(1)) if mx else None, "silencios_meio_s": meio, "duracao_s": round(total, 2)}


def avaliar(m, voz=None):
    erros = []
    if m["lufs"] is None or not (LUFS[0] <= m["lufs"] <= LUFS[1]): erros.append(f"loudness {m['lufs']} LUFS fora de {LUFS}")
    if m["true_peak_db"] is None or m["true_peak_db"] > TP_MAX: erros.append(f"true peak {m['true_peak_db']} dB acima de {TP_MAX}")
    if m["max_volume_db"] is not None and m["max_volume_db"] >= -0.1: erros.append("clipping (max_volume ~0 dB)")
    if any(x > SIL_MAX for x in m["silencios_meio_s"]): erros.append(f"silencio longo no meio: {m['silencios_meio_s']}")
    if voz is not None:
        d = voz["lufs"] - m["lufs"] if voz.get("lufs") is not None and m["lufs"] is not None else None
        m["voz_menos_mix_lu"] = d
        if d is not None and d > 6: erros.append(f"mix {d:.1f} LU abaixo da voz sozinha: trilha pode estar encobrindo")
    return erros


def main(argv):
    m = medir(argv[1]); voz = medir(argv[2]) if len(argv) > 2 else None
    erros = avaliar(m, voz)
    print("VNC_AUDIO_QA", json.dumps(m, ensure_ascii=False))
    for e in erros: print("VNC_AUDIO_QA_ERRO", e)
    print("VNC_AUDIO_QA_STATUS", "APROVADO" if not erros else "REPROVADO")
    return 0 if not erros else 6


if __name__ == "__main__":
    sys.exit(main(sys.argv))
