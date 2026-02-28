# Prompt para Claude Code — VoxVault: Integração Apple Foundation Models (Tradução)

## Contexto do Projeto

VoxVault é um aplicativo macOS de transcrição de reuniões em tempo real.
Stack: **Rust Core** (Voxtral Q4 via Burn/Metal) → WebSocket → **Python Orchestrator** (FastAPI) → SSE → **Tauri/React**.

O Python Orchestrator já possui um sistema de providers de tradução configurável
via `VOXVAULT_TRANSLATION_MODE` no `.env` (valores: `disabled`, `claude`, `openai`, `openrouter`, `local`).

## Objetivo

Adicionar o modo `apple` como novo provider de tradução, utilizando o
**Apple Foundation Models SDK** (on-device, macOS 26+, Apple Intelligence).

A tradução deve ser usada **apenas para segmentos curtos de transcrição em tempo real**.
Resumos e geração de atas continuam usando o provider OpenRouter já existente.

## Requisitos de Negócio

- **Zero custo por token** — on-device, sem chamadas a APIs externas
- **LGPD compliant** — texto nunca sai do dispositivo
- **Não quebrar nada** — fallback silencioso para texto original se Apple FM indisponível
- **Interface idêntica** aos outros providers — mesma assinatura de método `translate()`

## SDK Reference — Apple Foundation Models Python

```python
# Instalação (submodule ou pip)
# pip install -e ./python-apple-fm-sdk/
# Repositório: https://github.com/apple/python-apple-fm-sdk

import apple_fm_sdk as fm

# Verificar disponibilidade (SEMPRE fazer antes de usar)
model = fm.SystemLanguageModel()
ok, reason = model.is_available()
# ok=False se: Apple Intelligence desativado, macOS < 26, hardware incompatível

# Criar sessão com instruções de sistema
session = fm.LanguageModelSession(
    instructions="System instructions here"
)

# Inferência assíncrona — retorna objeto, converter com str()
response = await session.respond(prompt="texto aqui")
result = str(response).strip()

# Erros possíveis
# fm.ExceededContextWindowSizeError — contexto cheio (~4K tokens)
# fm.GuardrailViolationError        — conteúdo bloqueado
# fm.GenerationError                — erro genérico
```

**Importante:** O SDK é importado com `import apple_fm_sdk as fm`.
Fazer import lazy (dentro do método) para não quebrar em máquinas sem o SDK instalado.

## Tarefa 1 — Criar `python-orchestrator/providers/apple_provider.py`

Criar a classe `AppleTranslationProvider` com:

### Estrutura da classe

```python
class AppleTranslationProvider:
    def __init__(self): ...
    async def initialize(self) -> bool: ...   # retorna True se disponível
    async def translate(self, text: str, target_lang: str = "pt") -> str: ...
    async def translate_batch(self, segments: list[str], target_lang: str = "pt") -> list[str]: ...
    def reset_session(self, target_lang: str | None = None): ...
    
    @property
    def is_available(self) -> bool: ...
```

### Comportamentos obrigatórios

**`initialize()`:**
- Import lazy de `apple_fm_sdk` dentro do método (não no topo do arquivo)
- Chamar `model.is_available()` e logar o motivo se False
- Setar `self._available = False` se ImportError ou modelo indisponível
- Nunca lançar exceção — apenas retornar bool

**`translate()`:**
- Manter **uma sessão `LanguageModelSession` por `target_lang`** (dict `self._sessions`)
  para reutilizar contexto entre segmentos consecutivos da mesma reunião
- Usar `asyncio.Lock` para evitar race conditions em chamadas simultâneas
- Se `text` vazio ou só espaços, retornar `text` imediatamente (sem chamar o modelo)
- Se `self._available` for False, retornar `text` original sem logar warning excessivo
- Em caso de `ExceededContextWindowSizeError`: descartar a sessão do idioma, criar nova, tentar UMA vez mais
- Em qualquer outra exceção: logar o erro e retornar `text` original (nunca lançar)
- Converter response com `str(response).strip()`

**Prompt de tradução:**
```
instructions = """
You are a professional real-time meeting transcript translator.
Rules:
- Translate accurately and naturally, preserving the speaker's tone
- Keep technical terms, proper nouns and acronyms as-is
- Return ONLY the translated text — no explanations, no quotes, no preamble
- If the text is already in the target language, return it unchanged
- Preserve line breaks from the original
"""

# Para o prompt, usar formato direto:
prompt = f"Translate to {lang_name}:\n{text}"
```

**Mapeamento de idiomas** (dict `LANG_NAMES`):
```python
LANG_NAMES = {
    "pt": "Brazilian Portuguese", "pt-BR": "Brazilian Portuguese",
    "en": "English", "es": "Spanish", "fr": "French",
    "de": "German", "it": "Italian", "ja": "Japanese",
}
```

**`reset_session()`:**
- Se `target_lang` informado: remove só aquela sessão do dict
- Se `None`: limpa todo o dict `self._sessions`
- Útil para chamar entre reuniões diferentes

**Singleton no módulo:**
```python
_provider_instance: AppleTranslationProvider | None = None

async def get_apple_provider() -> AppleTranslationProvider:
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = AppleTranslationProvider()
        await _provider_instance.initialize()
    return _provider_instance
```

## Tarefa 2 — Modificar `python-orchestrator/main.py`

### 2a. Adicionar `apple` à lógica de provider

Localizar a função/lógica que instancia o provider de tradução baseado em
`VOXVAULT_TRANSLATION_MODE` e adicionar o caso `apple`:

```python
if TRANSLATION_MODE == "apple":
    from providers.apple_provider import get_apple_provider
    return await get_apple_provider()
```

### 2b. Pré-inicializar no startup

No evento de startup do FastAPI (`@app.on_event("startup")` ou `lifespan`),
adicionar pré-inicialização quando `TRANSLATION_MODE == "apple"`:

```python
if TRANSLATION_MODE == "apple":
    from providers.apple_provider import get_apple_provider
    provider = await get_apple_provider()
    if provider.is_available:
        logger.info("Apple Translation Provider pronto (on-device)")
    else:
        logger.warning("Apple FM indisponível — tradução desabilitada")
```

### 2c. Reset entre sessões

No endpoint `POST /api/session/stop` (ou equivalente que encerra uma sessão de gravação),
adicionar reset do contexto Apple após encerrar a sessão:

```python
if TRANSLATION_MODE == "apple":
    from providers.apple_provider import get_apple_provider
    provider = await get_apple_provider()
    provider.reset_session()  # limpa contexto acumulado da reunião
```

### 2d. Health check

No endpoint `GET /api/health`, adicionar informação do provider Apple:

```python
if TRANSLATION_MODE == "apple":
    from providers.apple_provider import get_apple_provider
    provider = await get_apple_provider()
    health_data["apple_fm_available"] = provider.is_available
```

## Tarefa 3 — Atualizar `.env.example`

Adicionar o novo modo na documentação do `.env.example`:

```dotenv
# Modo de tradução: disabled | claude | openai | openrouter | local | apple
# apple = on-device via Apple Foundation Models (macOS 26+, Apple Intelligence)
#         Zero custo, LGPD compliant, sem internet. Ideal para segmentos curtos.
VOXVAULT_TRANSLATION_MODE=disabled
```

## Tarefa 4 — Criar `python-orchestrator/test_apple_translation.py`

Script de validação standalone (não usa pytest, roda direto com `python`):

```
python test_apple_translation.py
```

Deve testar:
1. Disponibilidade do modelo Apple
2. EN → PT com 5 tipos de segmento: curto, médio, técnico (com NF-e/DANFE/SEFAZ), com números R$, já em PT (não deve mudar)
3. PT → EN com 2 segmentos
4. Batch de 3 segmentos
5. Imprimir latência de cada tradução e média final
6. Exibir veredicto: `< 1s = Excelente`, `1-2s = Bom`, `> 2s = considere tradução assíncrona`

## Restrições

- **Não modificar** nenhum provider existente (`claude_provider.py`, `openai_provider.py`, etc.)
- **Não modificar** a interface do método de tradução que já está sendo chamado no pipeline —
  o `apple_provider` deve se encaixar sem alterar os call sites existentes
- **Import lazy** do `apple_fm_sdk` em todo o código (nunca no topo do arquivo) —
  o Orchestrator deve iniciar normalmente em máquinas sem o SDK instalado
- O SDK está disponível em `python-apple-fm-sdk/` na raiz do projeto (submodule ou pasta local)
  e deve ser instalado com `pip install -e ./python-apple-fm-sdk/`

## Validação Final

Após implementar, verificar:

```bash
# 1. Instalar SDK
pip install -e ./python-apple-fm-sdk/

# 2. Testar qualidade da tradução
python test_apple_translation.py

# 3. Ligar o modo no .env e iniciar o Orchestrator
VOXVAULT_TRANSLATION_MODE=apple python main.py

# 4. Confirmar no health check
curl http://localhost:8766/api/health
# Esperado: { ..., "apple_fm_available": true, "translation_mode": "apple" }

# 5. Confirmar que TRANSLATION_MODE=disabled ainda funciona (sem SDK)
VOXVAULT_TRANSLATION_MODE=disabled python main.py
```
