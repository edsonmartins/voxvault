# VoxVault

Transcrição de reuniões em tempo real com IA local, tradução automática e geração de atas — tudo rodando no seu Mac.

## O que é o VoxVault?

VoxVault é um aplicativo desktop para macOS que captura o áudio do sistema (reuniões no Zoom, Google Meet, Teams, etc.), transcreve em tempo real usando o modelo Voxtral rodando localmente na GPU, e exibe o texto token por token conforme é decodificado.

Diferente de serviços na nuvem, todo o processamento de fala acontece no próprio dispositivo — sem enviar áudio para servidores externos. A tradução e geração de atas são opcionais e utilizam APIs de LLM.

## Funcionalidades

- **Transcrição em tempo real** — texto aparece palavra por palavra conforme o modelo decodifica, com latência de ~3 segundos
- **100% local** — inferência do Voxtral Q4 (2.5GB) via GPU Metal no Apple Silicon
- **Streaming token-by-token** — cada token decodificado é enviado imediatamente ao frontend via WebSocket → SSE
- **Tradução automática** — traduz transcrições para português, inglês, espanhol e outros idiomas (via Claude, OpenAI, OpenRouter ou modelo local)
- **Geração de atas** — sintetiza o transcript completo em ata estruturada com resumo executivo, decisões, itens de ação e pendências
- **Sessões persistentes** — grava transcrições em SQLite para consulta posterior
- **Interface discreta** — janela compacta (420×600) com modo stealth para compartilhamento de tela
- **Detecção automática de idioma** — identifica o idioma falado automaticamente

## Arquitetura

```
┌─────────────────────────────────────────────────────┐
│  Tauri Desktop App (React + TypeScript)             │
│  ├── TranscriptView — exibe texto em tempo real     │
│  ├── StatusBar — estado da conexão                  │
│  └── SettingsPanel — configurações                  │
└──────────────┬──────────────────────────────────────┘
               │ SSE (Server-Sent Events)
┌──────────────▼──────────────────────────────────────┐
│  Python Orchestrator (FastAPI, porta 8766)           │
│  ├── Recebe transcrições via WebSocket              │
│  ├── Tradução assíncrona (não bloqueia o pipeline)  │
│  ├── Gerenciamento de sessões                       │
│  ├── Geração de atas via LLM                        │
│  └── Broadcast SSE para múltiplos clientes          │
└──────────────┬──────────────────────────────────────┘
               │ WebSocket (porta 8765)
┌──────────────▼──────────────────────────────────────┐
│  Rust Core (voxvault-core)                          │
│  ├── Captura de áudio do sistema (cpal)             │
│  ├── Processamento de áudio (buffer, chunking)      │
│  ├── Voxtral Engine — inferência Q4 na GPU (Burn)   │
│  │   └── StreamingTranscriber — decode token a token│
│  └── WebSocket Server (Axum)                        │
└─────────────────────────────────────────────────────┘
```

## Fluxo de Dados

```
[Áudio do sistema] → cpal (500ms buffers)
    → AudioProcessor (acumula 3s)
    → Mel Spectrogram → Voxtral Encoder (~200ms)
    → Decode autogressivo token por token (~40ms/token)
        → "Bom"           → WS(parcial) → SSE → UI
        → "Bom dia"       → WS(parcial) → SSE → UI (substitui anterior)
        → "Bom dia a todos" → WS(final)  → SSE → UI (fixa no histórico)
```

## Pré-requisitos

- **macOS 14+** (Sonoma ou superior)
- **Apple Silicon** (M1/M2/M3/M4) — necessário para GPU Metal
- **16GB RAM** recomendado (modelo Q4 usa ~2.5GB VRAM)
- **Rust** (rustup)
- **Node.js** 18+
- **Python** 3.11+

## Instalação

### 1. Clonar o repositório

```bash
git clone --recurse-submodules https://github.com/edsonmartins/voxvault.git
cd voxvault
```

### 2. Baixar modelos

```bash
bash scripts/download-models.sh
```

Isso baixa o modelo Voxtral Q4 (~2.5GB) e o tokenizer para `models/`.

### 3. Configurar o Python Orchestrator

```bash
cd python-orchestrator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edite o `.env` conforme necessário (tradução, chaves de API, etc.).

### 4. Instalar dependências do frontend

```bash
cd ../rust-core
npm install
```

### 5. Compilar o Rust Core

```bash
cargo build --release -p voxvault-core
```

## Uso

### Iniciar os serviços

**Terminal 1 — Rust Core (transcrição):**
```bash
cd rust-core
cargo run --release --bin voxvault-cli -- \
  --device "NoMachine Audio Adapter" \
  --model-path ../models/voxtral-q4.gguf \
  --tokenizer-path ../models/tekken.json \
  --min-duration 3
```

Use `--list-devices` para ver os dispositivos de áudio disponíveis.

**Terminal 2 — Python Orchestrator:**
```bash
cd python-orchestrator
source .venv/bin/activate
python main.py
```

**Terminal 3 — Tauri App:**
```bash
cd rust-core
npx tauri dev
```

### Dispositivo de áudio virtual

Para capturar áudio de reuniões, configure um dispositivo de áudio virtual (como BlackHole ou Loopback) que redirecione o áudio do sistema para o VoxVault.

## Configuração

### Variáveis de ambiente (`.env`)

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `VOXVAULT_TRANSLATION_MODE` | `disabled` | Modo de tradução: `disabled`, `claude`, `openai`, `openrouter`, `local` |
| `VOXVAULT_TARGET_LANGUAGE` | `pt` | Idioma alvo para tradução |
| `VOXVAULT_ANTHROPIC_API_KEY` | — | Chave da API Anthropic (para modo `claude`) |
| `VOXVAULT_OPENAI_API_KEY` | — | Chave da API OpenAI (para modo `openai`) |
| `VOXVAULT_OPENROUTER_API_KEY` | — | Chave da API OpenRouter (para modo `openrouter`) |
| `VOXVAULT_RUST_WS_URL` | `ws://localhost:8765` | URL do WebSocket do Rust Core |
| `VOXVAULT_API_PORT` | `8766` | Porta da API Python |
| `VOXVAULT_SESSIONS_DIR` | `~/Documents/VoxVault/sessions` | Diretório para sessões |
| `VOXVAULT_DB_PATH` | `~/Documents/VoxVault/voxvault.db` | Caminho do banco SQLite |

### CLI do Rust Core

| Argumento | Padrão | Descrição |
|-----------|--------|-----------|
| `--device` | `VoxtralMeet Input` | Nome do dispositivo de áudio |
| `--model-path` | `../../models/voxtral-q4.gguf` | Caminho do modelo Voxtral |
| `--tokenizer-path` | `../../models/tekken.json` | Caminho do tokenizer |
| `--ws-port` | `8765` | Porta do WebSocket |
| `--min-duration` | `3.0` | Duração mínima (segundos) antes de transcrever |
| `--max-duration` | `30.0` | Duração máxima por chunk |
| `--buffer-ms` | `500` | Tamanho do buffer de áudio (ms) |

## API REST

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `GET` | `/api/transcript/stream` | SSE com transcrições em tempo real |
| `POST` | `/api/session/start` | Iniciar sessão de gravação |
| `POST` | `/api/session/stop` | Encerrar sessão |
| `GET` | `/api/session/current` | Verificar sessão ativa |
| `POST` | `/api/minutes/generate` | Gerar ata da reunião |
| `GET` | `/api/settings` | Obter configurações |
| `PUT` | `/api/settings` | Atualizar configurações |
| `GET` | `/api/health` | Health check |

## Stack Tecnológica

| Camada | Tecnologia |
|--------|-----------|
| Inferência | Voxtral Mini Q4 GGUF via Burn + WGPU (Metal) |
| Áudio | cpal (CoreAudio no macOS) |
| Backend Rust | Axum, Tokio, WebSocket |
| Orquestrador | FastAPI, SQLAlchemy, websockets |
| Tradução | Claude Haiku / GPT-4o-mini / Gemma 3 (OpenRouter) |
| Frontend | React 19, TypeScript, Vite |
| Desktop | Tauri v2 |
| Banco de dados | SQLite (async via aiosqlite) |

## Licença

Apache-2.0
