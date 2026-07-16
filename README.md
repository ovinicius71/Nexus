# Personal Organizer Bot

Um agente pessoal que organiza sua vida a partir de mensagens soltas enviadas ao longo do dia.
Você manda tarefas, ideias, eventos e anotações pelo Telegram; o bot classifica, estrutura e
armazena tudo — e, conforme os dados se acumulam, passa a encontrar conexões e dar dicas sobre
sua rotina.

> **Status:** Fase 1 (Fundação) — o bot recebe mensagens de texto e salva o conteúdo cru no
> SQLite. A classificação com IA e os demais recursos chegam nas próximas fases.

## Visão geral da arquitetura

- **Captura:** bot no Telegram (`python-telegram-bot`, async)
- **Persistência:** SQLite via SQLAlchemy, atrás de uma **camada de repositório**
  (facilita uma migração futura para Postgres)
- **Configuração:** `.env` + `pydantic-settings`
- **IA (próximas fases):** API da Anthropic (Claude Haiku para classificar, Sonnet para insights)

### Estrutura do projeto

```
src/organizer/
├── config.py          # Settings a partir do .env
├── logging_setup.py   # logging estruturado
├── db/
│   ├── models.py      # Entry, Person, EntryPerson, Correction (schema completo)
│   ├── engine.py      # engine, session factory, init_db()
│   └── repository.py  # EntryRepository (acesso a dados)
├── bot/app.py         # handlers do Telegram (/start, texto) + restrição por chat_id
└── main.py            # entrypoint
tests/                 # testes da camada de repositório
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
- `ALLOWED_CHAT_ID` — seu chat id (o bot ignora qualquer outro chat). Uma forma simples de
  descobrir: fale com o [@userinfobot](https://t.me/userinfobot), que responde com seu id.
- `DATABASE_URL` — opcional; padrão `sqlite:///organizer.db`.
- `LOG_LEVEL` — opcional; padrão `INFO`.

## Como rodar

```bash
python -m organizer.main
```

No Telegram, envie `/start` e depois qualquer mensagem de texto. O bot responde com uma
confirmação, por exemplo: `✅ Salvo (#1) às 14:30`.

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

## Roadmap (próximas fases)

- **Fase 2:** classificação com Claude Haiku (tipo, título, prazo, prioridade, pessoas, projeto)
  + correções via botões inline que viram few-shot examples.
- **Fase 3:** consultas (`/tarefas`, `/hoje`, `/ideias`, `/eventos`, `/buscar`).
- **Fase 4:** export para um vault do Obsidian (markdown + frontmatter YAML).
- **Fase 5:** memória semântica (embeddings) e sugestão de conexões entre notas.
- **Fase 6:** insights e proatividade (`/review` semanal com Claude Sonnet).
