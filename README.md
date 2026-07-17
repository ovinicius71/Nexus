# Personal Organizer Bot

Um agente pessoal que organiza sua vida a partir de mensagens soltas enviadas ao longo do dia.
Você manda tarefas, ideias, eventos e anotações pelo Telegram; o bot classifica, estrutura e
armazena tudo — e, conforme os dados se acumulam, passa a encontrar conexões e dar dicas sobre
sua rotina.

> **Status:** Fase 4 (Export para Obsidian) — o bot captura, **classifica com Claude Haiku**,
> responde a consultas (`/tarefas`, `/hoje`, `/ideias`, `/eventos`, `/buscar`) e **exporta para um
> vault do Obsidian** (`/export` ou `python -m organizer.export`) com frontmatter YAML e wikilinks.

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
│   └── repository.py  # EntryRepository (dados + classificação + correções + consultas)
├── llm/
│   ├── schema.py      # EntryClassification (pydantic) — saída estruturada
│   └── classifier.py  # chamada ao Claude Haiku + few-shot das correções
├── bot/app.py         # handlers do Telegram: texto, card + correção, consultas, concluir, export
├── export.py          # export para o vault do Obsidian (idempotente)
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

### Comandos de consulta (Fase 3)

- `/tarefas` — tarefas abertas, ordenadas por prazo (mais próximo primeiro) e prioridade; cada
  uma traz um botão **✔️ Concluir**.
- `/hoje` — entradas criadas no dia.
- `/ideias` / `/eventos` — lista por tipo.
- `/buscar <termo>` — busca simples (`LIKE`) em texto e título; a busca semântica vem na Fase 5.

### Export para o Obsidian (Fase 4)

Defina `VAULT_PATH` no `.env` (padrão `vault`). O export pode ser disparado de dois jeitos —
ambos chamam a mesma lógica e **não têm custo de API** (é só leitura do SQLite + escrita de `.md`):

```bash
python -m organizer.export     # script (bom para agendar depois)
```
ou o comando `/export` no Telegram (prático no dia a dia).

Ele gera, de forma **idempotente** (regenera as pastas gerenciadas; rodar de novo não duplica),
um vault num **híbrido PARA + Zettelkasten + LYT/MOCs** — pensado para poucos links, todos com
significado:

```
Home.md                       # MOC-raiz (LYT): liga todas as seções
Projects/<slug>.md            # PARA "Projects": MOC por projeto (trabalho acionável)
Areas/Tarefas.md              # PARA "Areas": todas as tarefas abertas (por prazo/prioridade)
Areas/Agenda.md               #   eventos, por data
Areas/People/<nome>.md        #   MOC por pessoa (relação contínua)
Resources/Ideias.md           # PARA "Resources": índice de ideias (conhecimento)
Resources/Notas.md            #   índice de notas de referência
Archive/Concluidas.md         # PARA "Archive": tarefas concluídas
Journal/YYYY-MM-DD.md         # log cronológico do dia
Slipbox/<id>-<slug>.md        # Zettelkasten: 1 nota atômica plana por entrada
```

- **Zettelkasten:** cada entrada é uma nota atômica em `Slipbox/`, com **frontmatter YAML**
  (id, type, status, due, priority, project, people, tags). No corpo, **só links com significado**
  — o projeto e as pessoas (nada de link para "dia" ou "tipo"). É a base para a descoberta de
  conexões da Fase 5.
- **PARA (Tiago Forte):** organiza por acionabilidade — `Projects` (com projeto), `Areas`
  (tarefas soltas, agenda, pessoas), `Resources` (ideias/notas), `Archive` (concluídas).
- **LYT/MOCs (Nick Milo):** cada pasta PARA tem *Maps of Content* que linkam **para baixo** as
  notas atômicas; a mesma nota pode aparecer em vários MOCs (Tarefas + Projeto + Pessoa). Abra um
  MOC e veja a paisagem inteira de um tópico — ótimo para navegação e para a IA.
- **Tags** por tipo (`#task`, `#idea`…), projeto (`#project/<slug>`) e categoria PARA
  (`#para/project`, `#para/area`, …) para colorir/filtrar o grafo.

Abra a pasta `vault` no Obsidian (*Open folder as vault*). As pastas acima são **geradas**
(regeradas a cada export) — evite colocar notas manuais dentro delas. O vault fica fora do git
(`.gitignore`), então nenhum dado pessoal vai para o repositório.

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
- **Fase 3:** ✅ consultas (`/tarefas`, `/hoje`, `/ideias`, `/eventos`, `/buscar`) + concluir tarefa.
- **Fase 4:** ✅ export para um vault do Obsidian num híbrido PARA + Zettelkasten + LYT/MOCs
  (`/export` + script, notas atômicas + MOCs, frontmatter YAML + wikilinks).
- **Fase 5:** memória semântica (embeddings) e sugestão de conexões entre notas.
- **Fase 6:** insights e proatividade (`/review` semanal com Claude Sonnet).
