# Runflow central (repo privado) — 2026-11-20

Entrada unica: `run/runflow.json` (episodio, selecao de clipes, trilha, etapas) + push em main -> `.github/workflows/vnc-runflow.yml`.
Etapas: `gates` (sempre) -> `build` -> `sync` -> `cover`. Qualquer falha em `gates` bloqueia o resto.

## Travas em codigo (`agents/vnc_gates.py`, testadas em `tests/test_vnc_gates.py`)
- 12 cenas S01..S12 em ordem; fonte so coverr/mixkit/pexels; sem premium/IA; sem repetir clipe dentro do episodio.
- Clipe usado OU descartado em outro episodio = bloqueado. Clipe tem que estar registrado em `contracts/vnc_clip_registry_v1.json` antes (`python -m agents.vnc_gates register EPn selecao.json --music ID`).
- Trilha ja usada em outro episodio = bloqueada.
- Selecao nao pode autorizar publicacao.
- Todo workflow: `contents: read`, timeout, concurrency, checkout por SHA, sem cron.
- Proibido no codigo: chamada de voz/imagem/video do ElevenLabs (R3/R4) e APIs de publicacao.
- `build`, `sync` e `cover` ainda sao especificos do E01: outro episodio falha com `ENGINE_NOT_GENERALIZED` (nao simula sucesso).

## Suite legada
`tests/` herdada do repo publico: 19 testes falham aqui so porque exigem workflows/previews que existem apenas no repo publico. Nao sao gate do privado.
