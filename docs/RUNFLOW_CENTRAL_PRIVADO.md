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

## Generalizacao por episodio (2026-11-20)
- Config por episodio: `episodes/<ID>.json` (modelo: `episodes/_MODELO_EPISODIO.json`). `agents/vnc_master_build.py` e `agents/vnc_cover.py` leem essa config; `e01_master_build.py`/`e01_cover.py` sao apenas atalhos.
- `timing: contract` (E01, legado) ou `timing: whisper` (episodios novos): `agents/vnc_align.py` alinha o roteiro das 12 cenas as palavras do Whisper small, confere com Whisper base (mediana de divergencia <= 0,15 s, cobertura >= 80%), calcula fronteiras de cena no meio das pausas, gera legendas karaoke automaticas (bloqueia se >2 cues com regra tipografica quebrada) e .srt.
- Sem antecipacao de legenda no modo whisper (a de 70 ms corrigia o contrato Scribe do E01).
- Gate novo `check_episode_config`: config completa, sha256 completo da voz, 12 cenas com texto, quadros da capa precisam ser clipes da selecao (registrados, sem repeticao).
- Autoteste de regressao: `timing_override: whisper` em `run/runflow.json` roda o E01 pelo caminho novo (run 44852037830): 86,17 s, 182 palavras alinhadas (0 interpoladas), conferencia small x base mediana 0,02 s, 43 cues. Nao e video para publicar.
- Sync independente (contrato) segue so para E01; episodios novos usam a conferencia small x base dentro do build.

## Identidade fixa travada (2026-11-21)
- `agents/vnc_style.py` (constantes e funcoes do estilo) + `contracts/vnc_style_lock_v1.json` (valores aprovados no E01). Logo (posicao/tamanho/opacidade/animacao), final de cinema (tempos), legenda (estilo/posicao/karaoke lilas), credito/CTA, cadeia de audio/video e formato final sao conferidos: testes -> gates -> build (aborta com exit 8 `style_lock`).
- Regressao E01 (contrato) no GitHub, run 44888717691: style_lock_errors [], 1080x1920, 86,17 s, folha de quadros igual ao aprovado. O sha do mp4 difere do v2 (reencode), a estrutura nao.
- Voz: `vnc-ingest-voice.yml` (unico com escrita) grava `assets/voice/<EP>.mp3` com sha conferido e apaga o link assinado; o build usa o arquivo. Gate `check_voice_source`.

## Curadoria automática (stage `curate`)
- Runflow: `{"episode":"E02","stages":["curate"]}` → job `curate` lista o Mixkit (licença livre, robots OK), filtra (vertical, curto, estático, frenético, cortes, brilho fora do clima da cena, pessoas/cidade), remove quase-duplicatas (dHash) e devolve contact sheet + JSON em base64 nos logs. NADA é escolhido automaticamente: a aprovação é do Claude.
- Limites: só Mixkit (Coverr bloqueia busca por robots; Pexels exige chave). Listagem serial com backoff (o Mixkit dá 429 sob paralelismo). Licença é do site, não por clipe (NÃO VERIFICADO por clipe).
- Teste real (E02, run 44891661241): 12 cenas com candidatos; fracos: S01 (chuva noturna: só chuva diurna/bokeh), S04 (1 vela), S11 (3).
- Curadoria v2 (run 44894776786): até 30 candidatos analisados/cena, 6 por cena, um clipe nunca aparece em 2 cenas, teto de 9 min na listagem, job 40 min (~17 min reais). Exclusões globais de tom (religioso específico, festa, chroma, abóbora etc.). Pontos fracos ainda: S01 (chuva noturna real inexistente no Mixkit), S04 (velas), S10 (mãos).
