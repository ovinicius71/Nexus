# Personal Organizer Bot

Um agente pessoal que organiza sua vida a partir de mensagens soltas enviadas ao longo do dia.
Você manda tarefas, ideias, eventos e anotações pelo Telegram; o bot classifica, estrutura e
armazena tudo — e, conforme os dados se acumulam, passa a encontrar conexões e dar dicas sobre
sua rotina.

> **Status:** Fase 2 (Classificação) — o bot recebe texto, salva no SQLite, **classifica com
> Claude Haiku** (tipo, título, prazo, prioridade, projeto, pessoas) e responde com um card e
> botões inline para correção. As correções viram few-shot examples nas próximas classificações.

## Visão geral da arquitetura

- **Captura:** bot no Telegram (`python-telegram-bot`, async)
- **Persistência:** SQLite via SQLAlchemy, atrás de uma **camada de repositório**
  (facilita uma migração futura para Postgres)
- **Configuração:** `.env` + `pydantic-settings`
- **IA:** API da Anthropic — Claude Haiku (`claude-haiku-4-5`) para classificação via structured
  output; Claude Sonnet para insights (fase futura)

### Estrutura do projeto

```
src/organizer/
├── config.py          # Settings a partir do .env
├── logging_setup.py   # logging estruturado
├── db/
│   ├── models.py      # Entry, Person, EntryPerson, Correction (schema completo)
│   ├── engine.py      # engine, session factory, init_db()
│   └── repository.py  # EntryRepository (dados + classificação + correções)
├── llm/
│   ├── schema.py      # EntryClassification (pydantic) — saída estruturada
│   └── classifier.py  # chamada ao Claude Haiku + few-shot das correções
├── bot/app.py         # handlers do Telegram: /start, texto, card + botões de correção
└── main.py            # entrypoint
prompts/classify.md    # prompt de classificação (versionável)
evals/                 # mini-eval de acurácia por campo
tests/                 # testes de repositório e do classificador (LLM mockado)
```

## Setup

Requer **Python 3.11+**.

```bash
# 1. Criar e ativar o ambiente virtual
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

# 2. Instalar o projeto (modo editável) com dependências de dev
pip install -e ".[dev]"

# 3. Configurar as variáveis de ambiente
copy .env.example .env       # Windows
# cp .env.example .env       # Linux/macOS
```

Edite o `.env`:

- `TELEGRAM_BOT_TOKEN` — crie um bot com o [@BotFather](https://t.me/BotFather) e copie o token.
- `ANTHROPIC_API_KEY` — chave da API da Anthropic (necessária a partir da Fase 2).
- `ALLOWED_CHAT_ID` — seu chat id (o bot ignora qualquer outro chat). Uma forma simples de
  descobrir: fale com o [@userinfobot](https://t.me/userinfobot), ou rode o bot e veja o
  `chat_id` no log do terminal ao enviar uma mensagem.
- `DATABASE_URL` — opcional; padrão `sqlite:///organizer.db`.
- `LOG_LEVEL` — opcional; padrão `INFO`.

## Como rodar

```bash
python -m organizer.main
```

No Telegram, envie `/start` e depois qualquer mensagem de texto. O bot classifica e responde com
um card-resumo e botões: **✅ Correto**, **✏️ Tipo** e **✏️ Prazo/Prioridade**. Ao corrigir, a
mudança é gravada em `corrections` e reinjetada como few-shot nas próximas classificações.

### Mini-eval de classificação

Crie um `evals/examples.jsonl` (veja `evals/examples.sample.jsonl` para o formato) com exemplos
rotulados e rode:

```bash
python evals/run_classify_eval.py            # usa evals/examples.jsonl
python evals/run_classify_eval.py caminho.jsonl
```

O script reporta a acurácia por campo (tipo, prazo, prioridade, projeto, pessoas, título).

## Testes

```bash
pytest
```

Os testes usam um SQLite em memória e cobrem a camada de repositório (gravação do texto cru,
timestamp automático, ids incrementais e consultas).

## Verificação manual da persistência

```bash
sqlite3 organizer.db "select id, raw_text, created_at from entries;"
```

## Roadmap

- **Fase 1:** ✅ bot + persistência (captura crua no SQLite).
- **Fase 2:** ✅ classificação com Claude Haiku + correções via botões inline (few-shot) + mini-eval.
- **Fase 3:** consultas (`/tarefas`, `/hoje`, `/ideias`, `/eventos`, `/buscar`).
- **Fase 4:** export para um vault do Obsidian (markdown + frontmatter YAML).
- **Fase 5:** memória semântica (embeddings) e sugestão de conexões entre notas.
- **Fase 6:** insights e proatividade (`/review` semanal com Claude Sonnet).
