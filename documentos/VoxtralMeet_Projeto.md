# VoxtralMeet — Projeto Completo
### App de Transcrição e Tradução de Reuniões em Tempo Real
**Mac Mini M4 · Rust + Python · 100% Local**

---

## 1. Visão Geral

Aplicação desktop para macOS que captura o áudio de reuniões diretamente no sistema operacional (sem bots ou convidados extras), transcreve em tempo real usando o modelo Voxtral rodando localmente, traduz opcionalmente via LLM (local ou nuvem), e gera atas estruturadas ao final de cada sessão.

```
Áudio do sistema (BlackHole)
          ↓
   [Rust Core]
   Captura → Voxtral GGUF → texto transcrito
          ↓  WebSocket local
   [Python Orchestrator]
   Tradução → Pós-processamento → Ata em Markdown
          ↓
   [Tauri UI]
   Interface menu bar — transcrição ao vivo na tela
```

---

## 2. Stack Tecnológica

### Rust (Core de Performance)
| Componente | Crate | Função |
|---|---|---|
| Captura de áudio | `cpal` | Acessa CoreAudio do macOS |
| Inferência Voxtral | `wgpu` | GPU compute via Metal (M4) |
| Servidor WebSocket | `axum` + `tokio` | Streaming de texto para Python |
| Interface UI | `tauri` | App nativo macOS com webview |
| Leitura GGUF | Projeto `voxtral-mini-realtime-rs` | Já implementado pela comunidade |

### Python (Orquestração)
| Componente | Lib | Função |
|---|---|---|
| Cliente WebSocket | `websockets` | Recebe texto do Rust |
| Tradução local | `mlx-lm` (Gemma 3) | Tradução offline opcional |
| Tradução nuvem | `anthropic` / `openai` | Claude Haiku ou GPT-4o mini |
| Geração de ata | LLM via prompt | Resume e estrutura a transcrição |
| Servidor HTTP | `fastapi` | Expõe endpoints para o Tauri |
| Configurações | `pydantic-settings` | Gerencia config do app |

### Modelo de Transcrição
| Item | Detalhe |
|---|---|
| Modelo | `TrevorJS/voxtral-mini-realtime-gguf` |
| Tamanho | 2.51 GB (Q4_0) |
| Latência | ~480ms |
| Idiomas | 13 (PT, EN, ES, FR, DE...) |
| Runtime | `voxtral-mini-realtime-rs` via WGPU + Metal |

### Captura de Áudio do Sistema
| Ferramenta | Função |
|---|---|
| `BlackHole 2ch` | Driver de áudio virtual (instalar uma vez) |
| Audio MIDI Setup | App nativo macOS para criar Aggregate Device |
| `cpal` no Rust | Lê do Aggregate Device em tempo real |

---

## 3. Arquitetura Detalhada

### 3.1 Camada de Captura (Rust)

O `cpal` lista os dispositivos de áudio disponíveis e abre um stream no **Aggregate Device** criado pelo usuário no Audio MIDI Setup — este device combina microfone + BlackHole, capturando tanto a voz do usuário quanto o áudio dos participantes remotos.

```
Pseudo-código:

LISTAR dispositivos de áudio
SELECIONAR "Aggregate Device" (configurável)
ABRIR stream com:
  - sample rate: 16000 Hz
  - channels: 1 (mono)
  - buffer: 80ms por chunk (= 1 token Voxtral)

PARA CADA chunk de áudio recebido:
  ACUMULAR até atingir window de 480ms
  ENVIAR para o módulo Voxtral
```

### 3.2 Módulo Voxtral (Rust)

Usa diretamente o código do `voxtral-mini-realtime-rs` adaptado para macOS com Metal. O GGUF é carregado em memória quando a sessão começa e liberado ao terminar.

```
Pseudo-código:

AO INICIAR SESSÃO:
  CARREGAR voxtral-q4.gguf via wgpu (Metal backend)
  CARREGAR tekken.json (tokenizer)
  INICIALIZAR kv-cache para streaming infinito

PARA CADA window de 480ms de áudio:
  PROCESSAR audio → tokens via encoder
  DECODIFICAR tokens → texto
  PUBLICAR texto via WebSocket para Python
  ATUALIZAR kv-cache (sliding window attention)

AO ENCERRAR SESSÃO:
  LIBERAR modelo da memória
  FECHAR WebSocket
```

### 3.3 Bridge WebSocket (Rust → Python)

O Rust sobe um servidor WebSocket local na porta 8765. O Python se conecta como cliente. O texto chega em chunks de ~1-3 palavras por vez (streaming real).

```
Pseudo-código Rust (servidor):

INICIAR WebSocket server em ws://localhost:8765
AGUARDAR conexão do Python

QUANDO texto transcrito disponível:
  ENVIAR mensagem JSON:
  {
    "type": "transcript",
    "text": "bom dia pessoal",
    "language": "pt",
    "timestamp": 1234567890,
    "is_final": false
  }

QUANDO chunk final (pausa detectada):
  ENVIAR com "is_final": true
```

### 3.4 Orquestrador Python

Recebe o texto do Rust, decide se traduz, acumula para geração de ata, e expõe tudo via FastAPI para a UI.

```
Pseudo-código:

CONECTAR em ws://localhost:8765
INICIALIZAR buffer de transcrição vazio
INICIALIZAR configurações (idioma alvo, modo tradução, API key)

PARA CADA mensagem recebida do WebSocket:

  SE is_final == true:
    SE tradução habilitada:
      SE modo == "local":
        texto_traduzido = CHAMAR Gemma3_local(texto, idioma_alvo)
      SENÃO:
        texto_traduzido = CHAMAR API_nuvem(texto, idioma_alvo)
    SENÃO:
      texto_traduzido = texto original

    ADICIONAR ao buffer_transcrição:
    {
      timestamp,
      texto_original,
      texto_traduzido,
      idioma_detectado
    }

    PUBLICAR via FastAPI SSE para UI

AO ENCERRAR SESSÃO:
  GERAR ata via LLM com buffer_transcrição completo
  SALVAR em markdown com timestamp
```

### 3.5 Módulo de Tradução Python

Abstrai a fonte da tradução — local ou nuvem — com interface idêntica.

```
Pseudo-código:

FUNÇÃO traduzir(texto, idioma_origem, idioma_alvo, modo):

  SE modo == "local":
    prompt = "Traduza de {idioma_origem} para {idioma_alvo}.
              Responda APENAS com a tradução.
              Texto: {texto}"
    RETORNAR Gemma3.generate(prompt, max_tokens=200)

  SE modo == "claude":
    RETORNAR claude.messages.create(
      model="claude-haiku-4-5",
      messages=[{role: user, content: prompt}]
    )

  SE modo == "openai":
    RETORNAR openai.chat.completions.create(
      model="gpt-4o-mini",
      messages=[{role: user, content: prompt}]
    )
```

### 3.6 Geração de Ata

Ao encerrar a sessão, o buffer completo da transcrição vai para um LLM que gera a ata estruturada.

```
Pseudo-código:

FUNÇÃO gerar_ata(buffer_transcrição, participantes, titulo_reunião):

  transcrição_completa = JUNTAR todos os textos do buffer

  prompt = """
  Você é um assistente especializado em atas de reunião.

  Título: {titulo_reunião}
  Participantes: {participantes}
  Data/hora: {agora}

  Transcrição completa:
  {transcrição_completa}

  Gere uma ata profissional com:
  1. Resumo executivo (3-5 linhas)
  2. Pontos discutidos
  3. Decisões tomadas
  4. Próximos passos / action items com responsáveis
  5. Pendências

  Formato: Markdown
  """

  RETORNAR LLM.generate(prompt)
  SALVAR como reuniao_{timestamp}.md
```

---

## 4. Interface — Tauri + React

### 4.1 Menu Bar App

O app vive discretamente na barra de menus do macOS. Ao clicar no ícone, abre um painel flutuante com a transcrição ao vivo.

```
┌─────────────────────────────────────────┐
│  🎙 VoxtralMeet                    [×]  │
├─────────────────────────────────────────┤
│  Status: ● Transcrevendo               │
│  Idioma detectado: Inglês → Português   │
├─────────────────────────────────────────┤
│  TRANSCRIÇÃO AO VIVO                    │
│  ─────────────────────────────────────  │
│  [EN] Good morning everyone, let's...   │
│  [PT] Bom dia a todos, vamos...         │
│                                         │
│  [EN] The numbers for Q3 are...         │
│  [PT] Os números do Q3 são...           │
│                                         │
├─────────────────────────────────────────┤
│  [⏹ Encerrar]  [📋 Copiar]  [⚙ Config] │
└─────────────────────────────────────────┘
```

### 4.2 Tela de Configurações

```
┌─────────────────────────────────────────┐
│  ⚙ Configurações                        │
├─────────────────────────────────────────┤
│  Dispositivo de áudio:                  │
│  [Aggregate Device ▼]                   │
│                                         │
│  Tradução:                              │
│  ( ) Desabilitada                       │
│  ( ) Local — Gemma 3 (mais lento)       │
│  (●) API — Claude Haiku (recomendado)   │
│                                         │
│  API Key: [•••••••••••••••••]           │
│                                         │
│  Idioma alvo: [Português ▼]             │
│                                         │
│  Salvar atas em: [~/Documents/Reunioes] │
│  [Salvar]                               │
└─────────────────────────────────────────┘
```

---

## 5. Estrutura de Pastas do Projeto

```
voxtral-meet/
│
├── rust-core/                        ← Projeto Rust (Tauri + Voxtral)
│   ├── src-tauri/
│   │   ├── src/
│   │   │   ├── main.rs               ← Entry point Tauri
│   │   │   ├── audio/
│   │   │   │   ├── capture.rs        ← cpal: captura do Aggregate Device
│   │   │   │   └── processor.rs      ← chunking e buffer de áudio
│   │   │   ├── voxtral/
│   │   │   │   ├── model.rs          ← carregamento do GGUF
│   │   │   │   ├── inference.rs      ← loop de inferência streaming
│   │   │   │   └── tokenizer.rs      ← wrapper do tekken.json
│   │   │   └── server/
│   │   │       └── websocket.rs      ← axum WebSocket server
│   │   └── Cargo.toml
│   │
│   └── src/                          ← Frontend React (UI Tauri)
│       ├── App.tsx
│       ├── components/
│       │   ├── TranscriptView.tsx    ← exibe texto ao vivo via SSE
│       │   ├── StatusBar.tsx         ← status da sessão
│       │   └── Settings.tsx          ← configurações
│       └── hooks/
│           └── useTranscript.ts      ← hook para consumir SSE
│
├── python-orchestrator/              ← Projeto Python
│   ├── main.py                       ← entry point FastAPI + WebSocket client
│   ├── services/
│   │   ├── translation.py            ← abstração local/nuvem
│   │   ├── minutes_generator.py      ← geração de ata
│   │   └── session_manager.py        ← gerencia estado da sessão
│   ├── config.py                     ← pydantic-settings
│   └── requirements.txt
│
└── models/                           ← Modelos locais
    ├── voxtral-q4.gguf               ← 2.51 GB
    └── tekken.json                   ← tokenizer
```

---

## 6. Configuração do Ambiente macOS

### 6.1 Audio MIDI Setup (uma vez, manual)

```
1. Instalar BlackHole:
   brew install blackhole-2ch

2. Abrir: Applications → Utilities → Audio MIDI Setup

3. Clicar no "+" → "Create Aggregate Device"

4. Nomear: "VoxtralMeet Input"

5. Marcar:
   ✅ Built-in Microphone (ou microfone externo)
   ✅ BlackHole 2ch

6. No Zoom/Meet/Teams:
   - Saída de áudio: BlackHole 2ch
   (assim o áudio dos participantes passa pelo BlackHole)

7. O app captura do "VoxtralMeet Input"
   que tem os dois canais combinados
```

### 6.2 Dependências de desenvolvimento

```bash
# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
cargo install tauri-cli

# Node (para o frontend Tauri)
brew install node

# Python
brew install python@3.11
pip install fastapi uvicorn websockets anthropic openai pydantic-settings

# Opcional: Gemma 3 local para tradução offline
pip install mlx-lm
mlx_lm.convert --hf-path google/gemma-3-4b-it --mlx-path models/gemma3
```

---

## 7. Fluxo Completo de Uma Sessão

```
USUÁRIO clica "Iniciar Reunião" na menu bar
  ↓
Tauri emite evento "session:start" para rust-core
  ↓
Rust:
  1. Carrega voxtral-q4.gguf (3-5 segundos)
  2. Abre stream de áudio do Aggregate Device
  3. Inicia WebSocket server na porta 8765
  4. Notifica UI: "Pronto"
  ↓
Python:
  1. Conecta no WebSocket do Rust
  2. Aguarda chunks de texto
  ↓
[DURANTE A REUNIÃO]
  Áudio chega → Rust processa → texto → WebSocket
  Python recebe → traduz → FastAPI SSE → UI exibe
  ↓
USUÁRIO clica "Encerrar"
  ↓
Tauri emite "session:stop"
  ↓
Rust:
  - Para captura de áudio
  - Libera modelo da memória
  - Fecha WebSocket
  ↓
Python:
  - Chama geração de ata com buffer completo
  - Salva reuniao_{timestamp}.md em ~/Documents/Reunioes
  - Notifica UI com caminho do arquivo
  ↓
UI exibe: "Ata salva em ~/Documents/Reunioes/reuniao_2026-02-21.md"
          [Abrir no Finder]
```

---

## 8. Estimativa de Memória RAM em Uso

| Componente | RAM |
|---|---|
| Voxtral GGUF (Q4) | ~2.6 GB |
| Runtime Rust + Tauri | ~150 MB |
| Python + FastAPI | ~200 MB |
| Gemma 3 local (se ativo) | ~2.5 GB |
| macOS overhead | ~4.0 GB |
| **Total (sem Gemma)** | **~7.0 GB ✅** |
| **Total (com Gemma)** | **~9.5 GB ✅** |

Com 16GB de RAM unificada no M4, sobram ~6.5GB de folga confortável.

---

## 9. Formato da Ata Gerada

```markdown
# Ata de Reunião — Revisão Q3 Rio Quality
**Data:** 21/02/2026 · 14h00  
**Duração:** 47 minutos  
**Participantes:** Edson, Carlos, Maria (EN)

---

## Resumo Executivo
Reunião focada em revisão dos resultados do Q3 e planejamento
das ações para o Q4. Foram definidas metas de crescimento de
15% e aprovado orçamento para novo sistema de ERP.

## Pontos Discutidos
- Resultados financeiros do Q3: receita R$ 42M (+8% vs Q2)
- Análise de clientes inadimplentes: 3,2% da carteira
- Proposta de expansão para Londrina e Cascavel

## Decisões Tomadas
- Aprovada expansão para Londrina no Q1/2027
- Budget de R$ 180k aprovado para novo ERP
- Meta de redução de inadimplência para 2,5% até dezembro

## Action Items
| Responsável | Tarefa | Prazo |
|---|---|---|
| Edson | Especificação técnica do ERP | 07/03/2026 |
| Carlos | Pesquisa de mercado Londrina | 14/03/2026 |
| Maria | Relatório inadimplência Q3 | 28/02/2026 |

## Pendências
- Definição do fornecedor de ERP (aguarda 3 propostas)
- Aprovação da diretoria para expansão geográfica
```

---

## 10. Roadmap de Desenvolvimento

### Fase 1 — Validação (1-2 semanas)
- Configurar BlackHole + Aggregate Device no Mac Mini
- Compilar `voxtral-mini-realtime-rs` com Metal no M4
- Testar transcrição via CLI com áudio real de reunião
- Validar qualidade do português

### Fase 2 — Backend Python (1 semana)
- WebSocket client conectando no servidor Rust
- Módulo de tradução (Claude Haiku API primeiro)
- FastAPI com SSE para streaming de texto
- Geração básica de ata

### Fase 3 — Interface Tauri (2 semanas)
- Setup do projeto Tauri + React
- Menu bar app com painel flutuante
- Exibição ao vivo da transcrição
- Tela de configurações

### Fase 4 — Polimento (1 semana)
- Tradução local com Gemma 3 MLX
- Ata em markdown com formatação profissional
- Notificações do sistema macOS
- Instalador `.dmg` para distribuição interna

---

*Projeto VoxtralMeet — IntegrAllTech · 2026*
