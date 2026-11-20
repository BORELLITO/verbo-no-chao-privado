"""Independent sync check (runner only): Whisper word timestamps on the voice vs the caption word timing contract."""
import hashlib, json, re, statistics, subprocess, sys, unicodedata, urllib.request
from pathlib import Path

link = Path("run/audio_link.txt").read_text().strip()
assert link.startswith("https://elevenlabsusercontent.com/")
data = urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"}), timeout=120).read()
assert hashlib.sha256(data).hexdigest().startswith("35f43519")
Path("/tmp/voice.mp3").write_bytes(data)
from faster_whisper import WhisperModel
m = WhisperModel("small", device="cpu", compute_type="int8")
import imageio_ffmpeg, numpy as np
raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", "/tmp/voice.mp3", "-f", "f32le", "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
audio = np.frombuffer(raw, dtype=np.float32)
segs, _ = m.transcribe(audio, language="pt", word_timestamps=True, vad_filter=False, beam_size=5)
ws = [(w.word.strip(), w.start, w.end) for s in segs for w in s.words]
norm = lambda t: re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFD", t.lower()).encode("ascii", "ignore").decode())
ref = json.loads(Path("contracts/e01_v3_voice_johnes_word_timing_v1.json").read_text())["words"]
# greedy ordered match
j = 0; pairs = []
for r in ref:
    k = norm(r["text"])
    for jj in range(j, min(j + 6, len(ws))):
        if norm(ws[jj][0]) == k:
            pairs.append((r, ws[jj])); j = jj + 1; break
d = [p[0]["start"] - p[1][1] for p in pairs]
de = [p[0]["end"] - p[1][2] for p in pairs]
big = [(p[0]["index"], p[0]["text"], round(p[0]["start"], 2), round(p[1][1], 2)) for p in pairs if abs(p[0]["start"] - p[1][1]) > 0.25]
print("VNC_SYNC", json.dumps({"ref_words": len(ref), "whisper_words": len(ws), "matched": len(pairs),
  "start_offset_median": round(statistics.median(d), 3), "start_offset_mean": round(statistics.mean(d), 3),
  "start_abs_p90": round(sorted(abs(x) for x in d)[int(len(d) * .9)], 3), "end_offset_median": round(statistics.median(de), 3),
  "start_gt_250ms": big[:40], "n_gt_250ms": len(big)}, ensure_ascii=False))
