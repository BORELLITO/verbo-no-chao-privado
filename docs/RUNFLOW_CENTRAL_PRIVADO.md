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

## Curadoria cinematográfica (caminho canônico: `.github/workflows/vnc-curate.yml`)
Entrada: `run/curate.json` → `{"episode","mode":"select|confirm|release","dry_run","as_episode"(só dry),"force_reselect","release_run","nonce"}`. Sai do Runflow (a antiga etapa `curate` foi removida: um único caminho).
Fluxo (`agents/vnc_curate.py`): roteiro (`episodes/<EP>.json`) → plano narrativo (`vnc_plan.py`: unidades, clima, consultas; `scenes[].visual` escrito pelo Claude > arco padrão vetado > léxico pt-BR) → busca Mixkit (listagem em cache `data/curadoria_cache.json`, TTL 14 d; backoff 429) → análise objetiva das prévias (movimento, brilho, saturação, nitidez, cortes, sha256, dHash de 3 quadros) → travas (formato, duração, clima, correspondência temática mínima, antirrepetição) → reformulação automática se <3 candidatos → seleção global por beam search (`vnc_select.py`, pesos em `contracts/vnc_curation_weights_v1.json` opcional) → direitos por clipe (página cita a licença gratuita + arquivo HD acessível) → reserva tudo-ou-nada na memória (`vnc_memory.py`) → registro legado + seleção no formato do gate + manifesto `episodes/<EP>_curadoria_manifest.json` → commit (permissão de escrita só neste workflow e no de voz).
Memória: `contracts/vnc_media_ledger_v1.json` (estados reserved/confirmed/released; sha256, dHash, origem, licença, intervalo, episódio, run) + registro legado por ID. Idempotente (mesmo episódio reaproveita a própria reserva), `confirm` após entrega válida, `release` só de reservas (nunca confirmed). Inconclusivo (visual 7–10 em ≥2 quadros, título equivalente) BLOQUEIA; só `contracts/vnc_dedupe_overrides.json` (humano, com motivo) libera.
Limites declarados: sem análise visual multimodal (só métricas + plano do Claude); só Mixkit é descoberto automaticamente; clipes legados Coverr/Pexels do E01 só protegidos por ID/título; licença verificada na página de cada clipe, Content ID não verificado; aprovação estética humana NÃO substituída.
Evidências: runs 44900506357 (dry-run simulado), 44901117083 (persistência real, 12 reservas), 44901903422 (idempotência), 44902053471 (release). Episódio de teste E99SIM removido depois.
