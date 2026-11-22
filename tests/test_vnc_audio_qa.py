from agents import vnc_audio_qa as A

def ok(): return {"lufs": -16.0, "true_peak_db": -1.5, "max_volume_db": -1.5, "silencios_meio_s": []}

def test_mix_normal_aprova(): assert A.avaliar(ok()) == []
def test_clipping_reprova():
    m = ok(); m["true_peak_db"] = 0.2; m["max_volume_db"] = 0.0
    assert A.avaliar(m)
def test_volume_baixo_reprova():
    m = ok(); m["lufs"] = -25.0
    assert A.avaliar(m)
def test_silencio_longo_reprova():
    m = ok(); m["silencios_meio_s"] = [2.4]
    assert A.avaliar(m)
