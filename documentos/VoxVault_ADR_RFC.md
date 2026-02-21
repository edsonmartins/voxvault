# VoxVault — ADRs e RFCs
### Architecture Decision Records & Requests for Comments
**voxvault.tech · IntegrAllTech · 2026**

---

## Índice

### Architecture Decision Records (ADRs)
Decisões técnicas já tomadas e consolidadas no projeto.

| ID | Título | Status |
|---|---|---|
| ADR-001 | Rust como runtime de inferência e captura de áudio | ✅ Aceito |
| ADR-002 | Voxtral GGUF Q4_0 como modelo de transcrição | ✅ Aceito |
| ADR-003 | Python como camada de orquestração e tradução | ✅ Aceito |
| ADR-004 | WebSocket como bridge Rust ↔ Python | ✅ Aceito |
| ADR-005 | Tauri + React para interface desktop | ✅ Aceito |
| ADR-006 | BlackHole como driver de captura de áudio do sistema | ✅ Aceito |
| ADR-007 | Carregamento sob demanda do modelo (lazy loading) | ✅ Aceito |
| ADR-008 | Ata de reunião gerada via LLM com prompt estruturado | ✅ Aceito |

### Requests for Comments (RFCs)
Propostas abertas para discussão e decisão futura.

| ID | Título | Status |
|---|---|---|
| RFC-001 | Estratégia de armazenamento e indexação de atas | 🔵 Em discussão |
| RFC-002 | Suporte a múltiplos idiomas simultâneos na mesma reunião | 🔵 Em discussão |
| RFC-003 | Identificação de múltiplos falantes (Speaker Diarization) | 🔵 Em discussão |
| RFC-004 | Modelo de distribuição e licenciamento do produto | 🔵 Em discussão |
| RFC-005 | Estratégia de expansão cross-platform (Windows / Linux) | 🔵 Em discussão |

---

---

# ARCHITECTURE DECISION RECORDS

---

## ADR-001 — Rust como runtime de inferência e captura de áudio

**Status:** ✅ Aceito  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)

### Contexto

O VoxVault precisa de dois componentes de alta performance rodando simultaneamente: captura de áudio em tempo real com latência mínima e inferência do modelo Voxtral com processamento de chunks de 480ms. Qualquer atraso perceptível no pipeline de captura → inferência → exibição degradaria a experiência do usuário.

A escolha da linguagem para o core impacta diretamente performance, acesso ao hardware macOS e viabilidade de futura expansão cross-platform.

### Decisão

Usar **Rust** como linguagem do core de performance, responsável por captura de áudio (`cpal`), inferência Voxtral (via `wgpu` + Metal), servidor WebSocket (`axum` + `tokio`) e interface desktop (`tauri`).

### Alternativas Consideradas

| Alternativa | Prós | Contras |
|---|---|---|
| **Swift** | Nativo macOS, acesso direto a AVFoundation | Exclusivo Apple, curva alta, mlx-audio não disponível nativamente |
| **Python puro** | Ecossistema mlx-audio pronto, mais rápido para desenvolver | GIL limita paralelismo real, latência de captura inconsistente |
| **C++** | Performance máxima, controle total | Complexidade alta, sem garantias de segurança de memória |
| **Rust** ✅ | Performance de C++, segurança de memória, cross-platform, `voxtral-mini-realtime-rs` já existe | Curva de aprendizado inicial |

### Consequências

**Positivas:**
- O projeto `voxtral-mini-realtime-rs` já implementa o GGUF do Voxtral em Rust com WGPU — reaproveitamento direto
- WGPU abstrai Metal (macOS), Vulkan (Linux) e DirectX 12 (Windows) — mesmo código roda em qualquer plataforma futuramente
- `cpal` acessa CoreAudio no macOS de forma idiomática sem bindings frágeis
- Ausência de garbage collector elimina pauses durante transcrição ao vivo
- Tauri gera binários nativos muito menores que Electron (~5MB vs ~200MB)

**Negativas:**
- Curva de aprendizado do Rust para quem vem de Java/Python
- Tempo de compilação mais longo durante desenvolvimento
- Ecossistema de IA/ML menos maduro que Python

---

## ADR-002 — Voxtral GGUF Q4_0 como modelo de transcrição

**Status:** ✅ Aceito  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)

### Contexto

O VoxVault precisa de um modelo de transcrição que rode 100% localmente no Mac Mini M4 com 16GB de RAM unificada, com suporte a português, latência inferior a 1 segundo e qualidade competitiva com soluções cloud como Whisper API.

### Decisão

Usar o modelo **`TrevorJS/voxtral-mini-realtime-gguf`** (Q4_0, 2.51 GB) — quantização 4-bit do Voxtral Mini 4B Realtime da Mistral AI, rodando via runtime Rust com WGPU.

### Alternativas Consideradas

| Alternativa | VRAM/RAM | Latência | Qualidade PT | Problema |
|---|---|---|---|---|
| **Voxtral BF16 original** | 16GB+ | 480ms | 5.03% WER | Excede RAM disponível para uso exclusivo |
| **Voxtral MLX 4-bit** | 3.1GB | 480ms | 5.03% WER | Framework MLX exclusivo para Apple Silicon — não portável |
| **Whisper Large v3** | ~3GB | Batch (não realtime) | ~6% WER | Sem streaming nativo, latência alta |
| **Whisper Turbo** | ~1.5GB | Semi-realtime | ~7% WER | Qualidade inferior, sem streaming verdadeiro |
| **Voxtral GGUF Q4_0** ✅ | 2.51GB | 480ms | ~5.5% WER | Runtime próprio em Rust (não llama.cpp padrão) |

### Consequências

**Positivas:**
- 2.51 GB ocupa apenas ~16% dos 16GB disponíveis — deixa memória para Gemma 3, Python e macOS
- WER de ~5.5% para português é excelente para um modelo quantizado em tempo real
- Runtime Rust com WGPU já testado em produção pelo autor do projeto
- Latência configurável de 80ms a 2.4s permite ajuste fino por caso de uso
- Licença Apache 2.0 — uso comercial permitido sem restrições

**Negativas:**
- Não usa llama.cpp padrão — dependência do projeto `voxtral-mini-realtime-rs` da comunidade
- Projeto ainda em desenvolvimento ativo — possível instabilidade
- Sem suporte oficial da Mistral para este runtime

### Notas

Monitorar issues do llama.cpp para suporte oficial ao `VoxtralForConditionalGeneration`. Quando disponível, migrar para eliminar dependência do projeto de terceiro.

---

## ADR-003 — Python como camada de orquestração e tradução

**Status:** ✅ Aceito  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)

### Contexto

Após definir Rust para o core de performance, é necessário decidir a linguagem para orquestração — tradução, geração de ata, integração com APIs externas e lógica de negócio. Esta camada não tem requisitos de latência crítica (opera sobre texto já transcrito) mas precisa de flexibilidade e ecossistema rico para IA.

### Decisão

Usar **Python 3.11+** com FastAPI para a camada de orquestração, expondo SSE para a UI e conectando via WebSocket ao core Rust.

### Alternativas Consideradas

| Alternativa | Prós | Contras |
|---|---|---|
| **Rust puro** | Sem bridge, menor overhead | Ecossistema IA/ML muito mais limitado, complexidade alta |
| **Java/Spring Boot** | Familiar para o time | Overhead de JVM, ecossistema IA muito menor que Python |
| **Node.js** | Mesmo runtime do frontend Tauri | Ecossistema IA inferior, tipagem fraca |
| **Python** ✅ | Ecossistema IA líder (mlx-lm, anthropic, openai), rápido para prototipar | Runtime mais lento, GIL |

### Consequências

**Positivas:**
- `mlx-lm` para Gemma 3 local já funciona no Apple Silicon
- SDKs oficiais `anthropic` e `openai` são Python-first
- FastAPI é assíncrono nativo — SSE e WebSocket sem bloqueio
- `pydantic-settings` simplifica configuração com validação de tipos
- Curva mínima dado o background do time

**Negativas:**
- Processo Python separado aumenta levemente o uso de memória (~200MB)
- Bridge Rust↔Python via WebSocket adiciona uma camada de comunicação

---

## ADR-004 — WebSocket como bridge Rust ↔ Python

**Status:** ✅ Aceito  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)

### Contexto

Rust (core) e Python (orquestrador) são processos separados. É necessário definir o mecanismo de comunicação entre eles para streaming de texto transcrito em tempo real.

### Decisão

Usar **WebSocket local** (ws://localhost:8765) com Rust como servidor (`axum`) e Python como cliente (`websockets`). Mensagens em JSON com schema definido.

### Alternativas Consideradas

| Alternativa | Prós | Contras |
|---|---|---|
| **Shared memory / mmap** | Latência mínima, zero serialização | Complexo, sem tipagem, difícil de debugar |
| **gRPC** | Tipagem forte, contrato claro | Overhead de setup, overkill para comunicação local |
| **Unix sockets** | Mais rápido que TCP local | Menos portável, API menos familiar |
| **HTTP polling** | Simples | Latência alta, não adequado para streaming |
| **WebSocket** ✅ | Streaming real, JSON simples, familiar, libraries maduras | Overhead TCP mínimo para loopback |

### Schema da mensagem definido

```json
{
  "type": "transcript | status | error",
  "text": "texto transcrito",
  "language": "pt | en | es | ...",
  "timestamp": 1234567890123,
  "is_final": true
}
```

### Consequências

**Positivas:**
- Protocolo agnóstico — futura troca de Python por outra linguagem não exige mudança no Rust
- Fácil de debugar com ferramentas como `websocat`
- Latência de loopback localhost é desprezível (<1ms)
- Mesmo protocolo pode ser exposto futuramente para integrações externas

**Negativas:**
- Serialização/deserialização JSON adiciona overhead mínimo mas mensurável
- Requer que o Python seja iniciado antes ou com retry de reconexão

---

## ADR-005 — Tauri + React para interface desktop

**Status:** ✅ Aceito  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)

### Contexto

O VoxVault precisa de uma interface desktop macOS que seja discreta (menu bar), responsiva para exibição de texto em streaming e com visual profissional alinhado ao posicionamento corporativo do produto.

### Decisão

Usar **Tauri 2.x** como framework desktop com **React + TypeScript** para o frontend, incluindo menu bar app nativo via plugin `tauri-plugin-positioner`.

### Alternativas Consideradas

| Alternativa | Bundle size | Performance | Visual nativo | Cross-platform |
|---|---|---|---|---|
| **SwiftUI** | ~5MB | Excelente | Perfeito | ❌ Apple only |
| **Electron + React** | ~200MB | Razoável | Não | ✅ |
| **Tauri + React** ✅ | ~8MB | Excelente | Muito bom | ✅ |
| **Flutter** | ~20MB | Boa | Bom | ✅ |
| **Qt** | ~30MB | Excelente | Bom | ✅ |

### Consequências

**Positivas:**
- Bundle final ~8MB vs ~200MB do Electron — instalador `.dmg` leve
- Rust no backend Tauri = mesmo processo do core, comunicação direta por eventos
- React familiar para desenvolvedores web — menor curva
- Tauri 2.x tem suporte nativo a menu bar apps no macOS
- Cross-platform preparado para Windows e Linux sem reescrever UI

**Negativas:**
- Tauri 2.x ainda relativamente novo — algumas APIs em maturação
- WebView do macOS (WKWebView) pode ter diferenças sutis de renderização

---

## ADR-006 — BlackHole como driver de captura de áudio do sistema

**Status:** ✅ Aceito  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)

### Contexto

Para transcrever reuniões sem bots ou convidados extras, o VoxVault precisa capturar o áudio que chega via Zoom/Meet/Teams **e** o microfone do usuário simultaneamente, de forma que nenhum participante da reunião precise fazer nada diferente do habitual.

### Decisão

Usar **BlackHole 2ch** (open-source, gratuito) como driver de áudio virtual, combinado com um **Aggregate Device** criado via Audio MIDI Setup do macOS, capturado pelo `cpal` no Rust.

### Alternativas Consideradas

| Alternativa | Custo | Complexidade | Qualidade |
|---|---|---|---|
| **BlackHole 2ch** ✅ | Gratuito | Configuração manual única | Alta |
| **Loopback (Rogue Amoeba)** | US$ 99 | Zero configuração | Excelente |
| **SoundFlower** | Gratuito | Configuração manual | Descontinuado, instável |
| **ScreenCaptureKit** (API Apple) | Gratuito | Alto (requer entitlements) | Alta, porém burocrática |

### Consequências

**Positivas:**
- BlackHole é open-source, mantido ativamente, funciona no Apple Silicon
- Aggregate Device é feature nativa do macOS — configuração estável
- Zero latência adicional — captura direta no nível do driver
- Funciona com qualquer app de reunião sem integração específica

**Negativas:**
- Requer configuração manual pelo usuário (uma única vez)
- Usuário precisa lembrar de redirecionar saída de áudio do app de reunião para BlackHole
- Automação desta configuração requer permissões de acessibilidade no macOS

### Mitigação

Criar wizard de onboarding no primeiro uso com instruções passo a passo e screenshots, verificando automaticamente se o Aggregate Device está configurado corretamente antes de permitir iniciar uma sessão.

---

## ADR-007 — Carregamento sob demanda do modelo (lazy loading)

**Status:** ✅ Aceito  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)

### Contexto

O Mac Mini M4 é uma máquina de uso geral — não é dedicado exclusivamente ao VoxVault. Manter o modelo Voxtral (2.51 GB) carregado permanentemente consumiria memória que poderia ser usada por outras aplicações, especialmente em sessões longas sem reunião.

### Decisão

O modelo é carregado **somente quando o usuário inicia uma sessão** e descarregado imediatamente ao encerrar. O processo Rust permanece em execução (menu bar), mas sem o modelo na memória.

### Alternativas Consideradas

| Alternativa | RAM ociosa | Tempo para iniciar | Complexidade |
|---|---|---|---|
| **Sempre carregado** | ~2.6 GB sempre | 0ms | Baixa |
| **Lazy loading** ✅ | 0 MB ocioso | 3-5 segundos | Média |
| **Pre-warming ao abrir app** | ~2.6 GB por ~30s | 0ms após warmup | Alta |

### Consequências

**Positivas:**
- Mac Mini disponível com memória cheia para outras tarefas quando sem reunião
- Footprint de memória em idle: ~50MB (processo Rust + menu bar)
- Usuário percebe claramente o início da sessão — UX intencional

**Negativas:**
- 3-5 segundos de espera ao iniciar sessão — deve ser comunicado visualmente
- Possível I/O intenso no carregamento — notificação de progresso necessária

### Implementação

Exibir indicator de loading com mensagem "Carregando VoxVault (3-5s)..." e progress bar durante o carregamento do modelo. Após pronto, transição suave para estado "Pronto para transcrever".

---

## ADR-008 — Ata de reunião gerada via LLM com prompt estruturado

**Status:** ✅ Aceito  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)

### Contexto

Ao encerrar uma sessão, o VoxVault precisa transformar a transcrição bruta em uma ata profissional com resumo, decisões, action items e pendências. A qualidade desta saída é crítica para o valor percebido do produto.

### Decisão

Usar o **mesmo LLM configurado para tradução** (local Gemma 3 ou API nuvem) com um **prompt estruturado em sistema** para geração da ata em Markdown, com template fixo de saída.

### Alternativas Consideradas

| Alternativa | Qualidade | Consistência | Custo |
|---|---|---|---|
| **Extração por regras/NLP** | Baixa | Alta | Zero |
| **Modelo fine-tuned para atas** | Alta | Alta | Alto (treino) |
| **LLM genérico + prompt** ✅ | Alta | Média-Alta | Baixo |
| **Template manual pelo usuário** | Variável | Variável | Zero |

### Consequências

**Positivas:**
- Qualidade de ata comparável a redação humana competente
- Flexível — prompt pode ser ajustado sem mudar código
- Reutiliza LLM já configurado — sem custo adicional de infraestrutura
- Suporta reuniões multilíngues (transcrição já está no idioma alvo)

**Negativas:**
- Qualidade depende do LLM escolhido — Gemma 3 local pode ser inferior à API
- Prompts longos (reuniões >1h) podem exceder contexto de modelos menores
- Sem garantia de formato exato sem validação de saída

### Mitigação

Implementar validação de estrutura da ata após geração. Se campos obrigatórios estiverem ausentes, retentar com prompt mais restritivo. Para reuniões muito longas, dividir a transcrição em chunks com sumarização progressiva.

---
---

# REQUESTS FOR COMMENTS

---

## RFC-001 — Estratégia de armazenamento e indexação de atas

**Status:** 🔵 Em discussão  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)  
**Prazo para decisão:** Fase 2 do roadmap

### Problema

O VoxVault atualmente salva atas como arquivos Markdown em `~/Documents/Reunioes`. À medida que o volume de reuniões cresce, surgem problemas: como buscar reuniões antigas? Como filtrar por participante, projeto ou período? Como evitar perda de dados?

### Proposta A — Filesystem + índice local (SQLite)

Mantém arquivos Markdown como fonte de verdade, mas cria um banco SQLite local com metadados indexados.

```
~/Documents/VoxVault/
├── sessions/
│   ├── 2026-02-21_reuniao-q3.md
│   └── 2026-02-22_alinhamento-tech.md
└── voxvault.db          ← SQLite com metadados
    ├── sessions (id, title, date, duration, participants, path)
    └── action_items (id, session_id, owner, task, due_date, done)
```

**Prós:** Simples, sem dependência externa, arquivos portáveis, backup trivial  
**Contras:** Busca full-text limitada, sem sync entre máquinas

### Proposta B — Banco vetorial local (SQLite + sqlite-vec)

Mesmo que A, mas adiciona embeddings vetoriais das atas para busca semântica — "encontre reuniões onde discutimos precificação".

```
voxvault.db
├── sessions (metadados)
├── action_items
└── embeddings (session_id, vector BLOB)  ← sqlite-vec extension
```

**Prós:** Busca semântica poderosa, ainda sem dependência externa  
**Contras:** Gerar embeddings requer modelo adicional (~100MB), maior complexidade

### Proposta C — Obsidian Vault como backend

Salva atas em formato compatível com Obsidian, com frontmatter YAML para metadados, permitindo que usuários usem Obsidian para navegar e buscar.

```yaml
---
title: Reunião Q3 Rio Quality
date: 2026-02-21
duration: 47min
participants: [Edson, Carlos, Maria]
tags: [q3, rio-quality, financeiro]
---
```

**Prós:** Usuários que já usam Obsidian têm integração imediata, backlinks automáticos  
**Contras:** Dependência de terceiro, não universal

### Questões em aberto

1. Qual o volume esperado de reuniões por mês por usuário?
2. Busca semântica é um diferencial valorizado ou complexidade desnecessária na v1?
3. Há interesse em sync entre múltiplos Macs (iCloud Drive, Dropbox)?

### Recomendação preliminar

Iniciar com **Proposta A** na Fase 2, com arquitetura preparada para evoluir para **Proposta B** na v1.1 se a busca se mostrar necessária. Proposta C pode ser um plugin opcional.

---

## RFC-002 — Suporte a múltiplos idiomas simultâneos na mesma reunião

**Status:** 🔵 Em discussão  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)  
**Prazo para decisão:** Fase 3 do roadmap

### Problema

O Voxtral detecta idioma automaticamente por chunk de áudio. Em reuniões multilíngues (ex: parte em PT, parte em EN, parte em ES), cada chunk pode ter idioma diferente. Como apresentar isso ao usuário de forma clara?

### Cenário atual (v1)

Configuração única: idioma alvo fixo para toda a sessão. Todos os chunks são traduzidos para o mesmo idioma independente do idioma detectado.

```
[EN] → [PT]   ✅ traduz
[PT] → [PT]   ✅ passa sem traduzir (mesmo idioma)
[ES] → [PT]   ✅ traduz
```

### Proposta A — Tradução universal para idioma alvo

Mantém o comportamento atual. Tudo vai para o idioma alvo, independente do idioma de origem.

**Prós:** Simples, consistente, fácil de implementar  
**Contras:** Usuário perde nuances quando o idioma original já é o alvo

### Proposta B — Exibição bilíngue por chunk

Cada chunk exibe original + tradução quando os idiomas diferem. Quando o idioma é o mesmo do alvo, exibe apenas uma linha.

```
UI:
[EN] Good morning, the numbers look great
[PT] Bom dia, os números parecem ótimos

[PT] Precisamos revisar o contrato até sexta
(sem tradução — já está no idioma alvo)
```

**Prós:** Rico, informativo, preserva o original para contexto  
**Contras:** UI pode ficar verbosa em reuniões muito multilíngues

### Proposta C — Modo "língua franca"

Usuário define um idioma de trabalho. O app exibe somente nesse idioma, traduzindo tudo o que não estiver nele. Inclui indicador visual do idioma original detectado.

```
[🇧🇷] Bom dia, os números parecem ótimos      ← original PT
[🇺🇸→🇧🇷] Bom dia, os números parecem ótimos  ← traduzido de EN
```

**Prós:** UI limpa, indica origem sem duplicar texto  
**Contras:** Requer design cuidadoso de icons/badges

### Questões em aberto

1. Qual o perfil mais comum de reunião multilíngue dos usuários-alvo?
2. A preservação do texto original tem valor para o usuário ou é ruído?
3. O indicador de idioma de origem é suficiente ou o usuário quer ver o texto original também?

### Recomendação preliminar

Implementar **Proposta A** na v1 por simplicidade. Evoluir para **Proposta C** na v1.1 baseado em feedback real de usuários.

---

## RFC-003 — Identificação de múltiplos falantes (Speaker Diarization)

**Status:** 🔵 Em discussão  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)  
**Prazo para decisão:** Pós v1.0

### Problema

A ata gerada atualmente não distingue quem disse o quê — é uma transcrição contínua. Para reuniões com múltiplos participantes, a ata de action items ficaria mais precisa e útil se soubéssemos "Carlos disse que vai entregar até sexta" vs "Edson disse que vai revisar o contrato".

### Contexto técnico

Speaker diarization é um problema difícil, especialmente quando o áudio de todos os participantes chega misturado pelo canal do Zoom/Meet (o que acontece com a captura via BlackHole). Soluções modernas requerem modelos adicionais.

### Proposta A — Sem diarization (v1)

Manter transcrição contínua sem identificação de falantes. A ata usa linguagem passiva ou genérica para action items.

**Prós:** Zero complexidade adicional  
**Contras:** Ata menos precisa para atribuição de responsabilidades

### Proposta B — pyannote.audio local

Adicionar modelo `pyannote/speaker-diarization-3.1` rodando localmente para segmentar o áudio por falante antes da transcrição.

```
Áudio → pyannote → [Speaker A: 0-15s] [Speaker B: 15-23s] → Voxtral → texto por falante
```

**Prós:** Atribuição precisa, ata rica  
**Contras:** +~1GB RAM, latência adicional, modelo requer licença HuggingFace, funciona melhor com microfones separados

### Proposta C — Identificação assistida pelo usuário

Antes da reunião, usuário cadastra os participantes. O app tenta correlacionar vozes com perfis, mas permite correção manual na revisão da ata.

**Prós:** Mais prático que diarization automática, usuário tem controle  
**Contras:** Trabalho manual de cadastro, correlação automática ainda imperfeita

### Proposta D — Integração com API da plataforma de reunião

Para Zoom/Meet/Teams, usar a API oficial para obter transcrição já com diarization feita pela plataforma, usando o VoxVault apenas para tradução e geração de ata.

**Prós:** Diarization de altíssima qualidade (a plataforma conhece cada stream de áudio separado)  
**Contras:** Quebra o princípio de privacidade local, requer autenticação OAuth por plataforma, limita a plataformas suportadas

### Questões em aberto

1. A atribuição de falas por participante é um requisito crítico ou nice-to-have para o mercado-alvo?
2. Há disposição de aceitar +1GB de RAM e +latência por esse recurso?
3. O princípio "100% local" deve ser preservado ou é negociável para ganhar qualidade?

### Recomendação preliminar

**Proposta A** na v1. Avaliar **Proposta B** ou **C** na v2 baseado em demanda real do mercado.

---

## RFC-004 — Modelo de distribuição e licenciamento do produto

**Status:** 🔵 Em discussão  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)  
**Prazo para decisão:** Antes de lançamento público

### Problema

O VoxVault começa como uso interno na IntegrAllTech, mas o posicionamento é produto de mercado amplo. É necessário definir como o produto será distribuído e monetizado, considerando que o modelo Voxtral e os componentes são open-source Apache 2.0.

### Proposta A — Licença perpétua (one-time purchase)

Usuário paga uma vez e usa para sempre. Atualizações por período limitado (ex: 1 ano).

**Prós:** Preferência crescente no mercado, sem churn de assinatura  
**Contras:** Receita não recorrente, difícil prever fluxo de caixa

### Proposta B — SaaS com assinatura mensal/anual

Modelo freemium com plano gratuito (limitado a X horas/mês) e plano pago.

```
Free:    5 horas/mês, tradução desabilitada
Pro:     Ilimitado, tradução via API, R$ 49/mês
Team:    Multi-usuário, dashboard centralizado, R$ 29/usuário/mês
```

**Prós:** Receita previsível, escala bem  
**Contras:** Contradiz o diferencial "100% local" se exigir autenticação online

### Proposta C — Open Core

Core open-source (captura + transcrição), features avançadas pagas (tradução, ata, dashboard, sync).

**Prós:** Distribuição orgânica via open-source, monetização nas features premium  
**Contras:** Complexidade de manter duas versões, concorrência de forks

### Proposta D — Licença por empresa (B2B)

Venda direta para empresas com contrato anual. Sem limitação por usuário — licença por domínio/CNPJ.

```
Startup (<50 funcionários):  R$ 2.400/ano
PME (50-500):                R$ 9.600/ano
Enterprise (500+):           Sob consulta
```

**Prós:** Alinhado ao posicionamento corporativo, ticket médio alto, sem gestão de usuários individuais  
**Contras:** Ciclo de venda mais longo, suporte mais exigente

### Questões em aberto

1. O VoxVault deve exigir conexão com servidor para validar licença ou ser 100% offline?
2. Como distribuir atualizações sem comprometer o princípio de privacidade?
3. Qual o segmento prioritário — PMEs ou enterprise?

### Recomendação preliminar

**Proposta D** (B2B por empresa) para o mercado corporativo, com período de **Proposta A** (licença perpétua) para early adopters durante beta. Evitar SaaS que exija dados em nuvem — contradiz o posicionamento de privacidade que é o principal diferencial.

---

## RFC-005 — Estratégia de expansão cross-platform (Windows / Linux)

**Status:** 🔵 Em discussão  
**Data:** Fevereiro 2026  
**Autores:** Edson (IntegrAllTech)  
**Prazo para decisão:** Pós v1.0

### Problema

O VoxVault v1 é exclusivo macOS. O mercado corporativo brasileiro usa majoritariamente Windows. Uma eventual expansão para Windows ampliaria significativamente o TAM (Total Addressable Market).

### Situação atual de portabilidade

| Componente | macOS | Windows | Linux |
|---|---|---|---|
| Rust + WGPU | Metal ✅ | DirectX 12 🟡 | Vulkan 🟡 |
| `cpal` (áudio) | CoreAudio ✅ | WASAPI 🟡 | PipeWire/ALSA 🟡 |
| Tauri + React | ✅ | ✅ | ✅ |
| BlackHole | ✅ | ❌ | ❌ |
| Python + FastAPI | ✅ | ✅ | ✅ |

O maior bloqueio é o **driver de captura de áudio** — BlackHole é macOS only.

### Equivalentes por plataforma

| Plataforma | Equivalente ao BlackHole | Maturidade |
|---|---|---|
| Windows | VB-Cable (gratuito) ou Virtual Audio Cable | Alta |
| Linux | PipeWire virtual sink | Alta |

### Proposta A — macOS first, Windows depois (recomendado)

Lançar v1 exclusivo macOS, validar produto-mercado, depois portar para Windows com VB-Cable como dependência equivalente.

**Prós:** Foco total no MVP, base de usuários Apple tende a ser mais inovadora e pagar mais  
**Contras:** Exclui maioria do mercado corporativo BR no curto prazo

### Proposta B — macOS + Windows simultâneos

Desenvolver abstração de captura de áudio desde o início, suportando BlackHole e VB-Cable.

**Prós:** Mercado maior desde o início  
**Contras:** Dobra complexidade de QA, testes e suporte

### Questões em aberto

1. Qual percentual dos clientes-alvo usa Mac vs Windows?
2. A IntegrAllTech tem capacidade de suporte para múltiplas plataformas simultaneamente?
3. Faz sentido usar a RTX 3060 no Ubuntu como banco de testes para o port Linux desde a Fase 1?

### Recomendação preliminar

**Proposta A** — macOS exclusivo na v1. A arquitetura Rust + WGPU + Tauri já é cross-platform por design, então o port futuro será incremental. O Ubuntu com RTX 3060 já disponível pode servir como ambiente de teste Linux de forma orgânica.

---

## Histórico de Revisões

| Versão | Data | Descrição |
|---|---|---|
| 1.0 | 21/02/2026 | Versão inicial — 8 ADRs + 5 RFCs |

---

*VoxVault · voxvault.tech · IntegrAllTech · 2026*
