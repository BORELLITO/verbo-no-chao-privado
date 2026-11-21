"""Memoria persistente global de midia do VERBO NO CHAO (antirrepeticao entre episodios).

Fonte da verdade: contracts/vnc_media_ledger_v1.json (versionado no git = auditavel e duravel) + contracts/vnc_clip_registry_v1.json (legado por ID,
continua sendo lido: tudo que esta la vale como 'confirmed' por identificador).

Estados por entrada: reserved -> confirmed | released. 'legacy' = vindo so do registro antigo (sem impressao digital).
Garantias:
  - reserva em lote TUDO-OU-NADA sob trava de arquivo (flock) + recarga do disco dentro da trava (transacional dentro de um runner);
  - entre execucoes: workflow com concurrency group exclusivo + push sem force (nao-fast-forward falha, nada e perdido);
  - mesmo episodio pode re-reservar as proprias entradas (idempotente);
  - episodio diferente nunca reserva midia 'reserved' ou 'confirmed' de outro; 'released' volta a ficar livre;
  - confirmed nunca e liberado por esta API.
Duplicatas: mesmo ID, mesmo sha256 do arquivo, mesma filmagem (origin_id), impressao visual (dHash de 3 quadros) e titulo equivalente entre fontes.
Caso inconclusivo = BLOQUEIA (conservador); so um override humano versionado em contracts/vnc_dedupe_overrides.json libera.
"""
import contextlib, datetime, fcntl, json, os, re, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "contracts" / "vnc_media_ledger_v1.json"
REGISTRY = ROOT / "contracts" / "vnc_clip_registry_v1.json"
OVERRIDES = ROOT / "contracts" / "vnc_dedupe_overrides.json"
HAM_BLOCK = 6        # <= : mesma imagem (bloqueio)
HAM_INCONCLUSIVE = 10  # 7..10 em >=2 quadros : suspeito (bloqueio conservador)
ACTIVE = ("reserved", "confirmed")


class MemoryError_(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def key(source, cid):
    return f"{str(source).lower()}:{cid}"


def title_key(title):
    """Chave de titulo p/ detectar a mesma filmagem listada em fontes diferentes (ignora palavras vazias/numeros)."""
    stop = {"a", "an", "the", "of", "on", "in", "at", "with", "and", "coverr", "mixkit", "pexels", "stock", "video", "footage"}
    w = [x for x in re.findall(r"[a-z]+", str(title).lower()) if x not in stop]
    return " ".join(sorted(set(w))) if len(w) >= 3 else ""


def hamming(a, b):
    return bin(int(a) ^ int(b)).count("1")


def empty():
    return {"schema_version": "1.0.0", "project": "verbo-no-chao", "rule_pt": "Nenhuma midia usada em um episodio pode aparecer em outro.", "entries": {}}


def load(path=LEDGER):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf8")) if p.exists() else empty()


def _save(led, path):
    p = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".ledger-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf8") as f:
        json.dump(led, f, ensure_ascii=False, indent=1, sort_keys=True); f.write("\n"); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)  # escrita atomica


@contextlib.contextmanager
def transaction(path=LEDGER):
    """Trava exclusiva + recarga do disco; grava atomicamente ao sair sem erro."""
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    lock = open(str(p) + ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        led = load(p)
        yield led
        _save(led, p)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN); lock.close()


def legacy_ids(reg, led=None):
    """{key: episodio} de TUDO que o registro antigo marca como usado/descartado (qualquer fonte)."""
    out = {}
    for ep, d in (reg or {}).get("episodes", {}).items():
        for c in d.get("used", []):
            out[key(c["source"], c["id"])] = ep
        for lst in d.get("discarded_versions", {}).values():
            for c in lst:
                out[key(c["source"], c["id"])] = ep
    return out


def _overrides(path=OVERRIDES):
    p = Path(path)
    if not p.exists():
        return set()
    return {frozenset((o["a"], o["b"])) for o in json.loads(p.read_text(encoding="utf8")).get("distinct_pairs", []) if o.get("reason_pt")}


def conflicts(cand, episode, led, reg=None, overrides=None):
    """Lista de motivos de bloqueio de `cand` para `episode` ([] = livre).
    cand: {source,id,title?,sha256?,phashes?[int...],origin_id?}"""
    k = key(cand["source"], cand["id"]); why = []
    ov = overrides if overrides is not None else _overrides()
    leg = legacy_ids(reg if reg is not None else (json.loads(REGISTRY.read_text(encoding="utf8")) if REGISTRY.exists() else {}))
    if k in leg and leg[k] != episode:
        why.append(f"id_ja_usado_em_{leg[k]}")
    ctk = title_key(cand.get("title", ""))
    for ek, e in led["entries"].items():
        if e["episode"] == episode or e["state"] not in ACTIVE + ("legacy",):
            continue
        pair = frozenset((k, ek))
        if ek == k:
            why.append(f"id_{e['state']}_em_{e['episode']}"); continue
        if pair in ov:
            continue
        if cand.get("sha256") and cand["sha256"] == e.get("sha256"):
            why.append(f"mesmo_arquivo_de_{ek}@{e['episode']}")
        if cand.get("origin_id") and cand["origin_id"] == e.get("origin_id"):
            why.append(f"mesma_filmagem_de_{ek}@{e['episode']}")
        if ctk and ctk == title_key(e.get("title", "")):
            why.append(f"titulo_equivalente_a_{ek}@{e['episode']}(inconclusivo)")
        a, b = cand.get("phashes") or [], e.get("phashes") or []
        if a and b:
            ds = sorted(hamming(x, y) for x in a for y in b)
            if ds[0] <= HAM_BLOCK:
                why.append(f"visual_igual_a_{ek}@{e['episode']}(d={ds[0]})")
            elif sum(d <= HAM_INCONCLUSIVE for d in ds) >= 2:
                why.append(f"visual_suspeito_de_{ek}@{e['episode']}(inconclusivo,d={ds[0]})")
    # tambem os de OUTROS episodios no registro legado com titulo equivalente (clip legado sem hash)
    return why


def reserve(episode, run_id, cands, path=LEDGER, reg=None):
    """Reserva em lote tudo-ou-nada. cands: [{source,id,scene,interval,title,page,license,sha256,phashes,origin_id,dur}].
    Retorna (ok, {key: motivos}). Idempotente para o mesmo episodio."""
    with transaction(path) as led:
        blocked = {}
        for c in cands:
            w = conflicts(c, episode, led, reg)
            if w:
                blocked[key(c["source"], c["id"])] = w
        if blocked:
            raise _Abort(blocked)
        for c in cands:
            k = key(c["source"], c["id"]); old = led["entries"].get(k)
            if old and old["episode"] == episode and old["state"] == "confirmed":
                continue
            led["entries"][k] = {"source": c["source"], "id": str(c["id"]), "episode": episode, "scene": c.get("scene"), "interval": c.get("interval"),
                                 "title": c.get("title", ""), "page": c.get("page", ""), "license": c.get("license"), "sha256": c.get("sha256"),
                                 "phashes": c.get("phashes"), "origin_id": c.get("origin_id"), "dur": c.get("dur"), "state": "reserved",
                                 "run_id": str(run_id), "reserved_at": (old or {}).get("reserved_at", now()), "updated_at": now()}
        # libera reservas antigas do MESMO episodio que sairam da selecao (nunca confirmed)
        keep = {key(c["source"], c["id"]) for c in cands}
        for k, e in list(led["entries"].items()):
            if e["episode"] == episode and e["state"] == "reserved" and k not in keep:
                e["state"] = "released"; e["updated_at"] = now()
    return True, {}


class _Abort(Exception):
    def __init__(self, blocked):
        self.blocked = blocked


def try_reserve(episode, run_id, cands, path=LEDGER, reg=None):
    try:
        return reserve(episode, run_id, cands, path, reg)
    except _Abort as a:
        return False, a.blocked


def confirm(episode, path=LEDGER):
    n = 0
    with transaction(path) as led:
        for e in led["entries"].values():
            if e["episode"] == episode and e["state"] == "reserved":
                e["state"] = "confirmed"; e["updated_at"] = now(); n += 1
    return n


def release(episode, run_id, path=LEDGER):
    """Libera SO reservas (nunca confirmed) criadas por `run_id` quando a entrega nao ocorreu."""
    n = 0
    with transaction(path) as led:
        for e in led["entries"].values():
            if e["episode"] == episode and e["state"] == "reserved" and e["run_id"] == str(run_id):
                e["state"] = "released"; e["updated_at"] = now(); n += 1
    return n


def main(argv):
    cmd, ep = (argv + ["", ""])[:2]
    if cmd == "confirm":
        print("VNC_MEMORY_CONFIRMED", confirm(ep)); return 0
    if cmd == "release":
        print("VNC_MEMORY_RELEASED", release(ep, argv[2])); return 0
    if cmd == "status":
        led = load(); c = {}
        for e in led["entries"].values():
            c[(e["episode"], e["state"])] = c.get((e["episode"], e["state"]), 0) + 1
        print(json.dumps({f"{a}:{b}": n for (a, b), n in sorted(c.items())})); return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
