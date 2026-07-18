# Personal Organizer Bot

Um agente pessoal que organiza sua vida a partir de mensagens soltas enviadas ao longo do dia.
Você manda tarefas, ideias, eventos e anotações pelo Telegram; o bot classifica, estrutura e
armazena tudo — e, conforme os dados se acumulam, passa a encontrar conexões e dar dicas sobre
sua rotina.

> **Status:** Fase 6 (Insights e proatividade) — projeto completo. Além de capturar, classificar,
> consultar, exportar e conectar notas, o bot gera um **review semanal** com Claude Sonnet
> (`/review`) e, quando o histórico fica rico o suficiente, **manda o review sozinho** no Telegram.

## Visão geral da arquitetura

- **Captura:** bot no Telegram (`python-telegram-bot`, async)
- **Persistência:** SQLite via SQLAlchemy, atrás de uma **camada de repositório**
  (facilita uma migração futura para Postgres)
- **Configuração:** `.env` + `pydantic-settings`
- **IA:** API da Anthropic — Claude Haiku (`claude-haiku-4-5`) para classificação e para o filtro
  da busca (structured output); Claude Sonnet (`claude-sonnet-5`) para o review semanal / insights
- **Agendamento:** `JobQueue` do `python-telegram-bot` (APScheduler por baixo) para o review automático
- **Memória semântica:** embeddings locais via `sentence-transformers` (offline, sem custo) +
  `sqlite-vec` para busca por similaridade no próprio SQLite

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
├── embeddings.py      # Embedder local (sentence-transformers, offline)
├── semantic.py        # SemanticIndex sobre sqlite-vec (busca por similaridade)
├── review.py          # monta o snapshot da semana, orquestra e renderiza o review
├── bot/app.py         # handlers do Telegram: texto, card, consultas, conexões, review, export
├── export.py          # export para o vault do Obsidian (idempotente)
└── main.py            # entrypoint
prompts/classify.md    # prompt de classificação (versionável)
prompts/search.md      # prompt do filtro de busca (Haiku)
prompts/review.md      # prompt do review semanal (Sonnet)
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
- Opções avançadas (busca semântica, limiares e review semanal) têm padrões sensatos e estão
  todas documentadas no `.env.example` — só mexa se quiser ajustar (ex.: `TIMEZONE`, `REVIEW_HOUR`).

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
- `/buscar <termo>` — busca por **significado**. Com `SEARCH_RERANK=true` (padrão), o bot junta
  candidatos (match exato + vizinhos semânticos com recall amplo) e o **Claude Haiku** decide quais
  realmente batem com a intenção. Assim buscar `sair` traz *"cinema com a Helen"* e *"chamar a Manu
  para sair"* (conceito de sair), enquanto `joão` continua só com as notas do João. Com
  `SEARCH_RERANK=false`, cai numa **busca híbrida local** (sem custo de API): **Resultados** exatos
  primeiro, depois **Relacionados** por similaridade acima de `SEARCH_THRESHOLD` (padrão `0.45`).
- `/review` — gera a **análise da semana** com Claude Sonnet (ver seção abaixo).

### Memória semântica e conexões (Fase 5)

Ao salvar uma entrada nova, o bot gera um **embedding local** (offline, sem custo de API) e busca
as mais parecidas no `sqlite-vec`. Se a similaridade passar do `SIMILARITY_THRESHOLD` (padrão
`0.6`), ele sugere no Telegram: *"🔗 isso lembra a entrada #X…"* com botões **🔗 Linkar** /
**✕ Ignorar**. Cada resposta é gravada na tabela `connections` (com a similaridade) para calibrar
o limiar depois. Conexões aceitas viram uma seção **Relacionadas** com wikilinks no export do
Obsidian.

- Primeiro uso baixa o modelo (`EMBEDDING_MODEL`, ~120 MB) uma vez.
- Entradas antigas são indexadas automaticamente ao iniciar o bot.

### Review semanal e proatividade (Fase 6)

`/review` monta um **snapshot** do seu banco — as entradas da última semana (cruas) + agregados de
todo o histórico (contagens por tipo/projeto, idade das tarefas abertas, ideias órfãs) — e manda
pro **Claude Sonnet**, que devolve uma análise estruturada em seções:

- ⏳ **tarefas adiadas** (vencidas ou abertas há tempo)
- 📈 **temas em crescimento** (projetos/pessoas/assuntos mais ativos que a média)
- 💡 **ideias órfãs** (ideias sem projeto e sem conexão aceita)
- 🔁 **padrões de rotina** (dias mais cheios, equilíbrio tarefas × ideias)

Regra mantida de ponta a ponta: o modelo **não inventa** dados — cada ponto é ancorado no snapshot.

**Proatividade:** um job semanal (`JobQueue`) roda no dia/hora configurados (padrão **domingo 20h**,
fuso `TIMEZONE`) e, **só quando o histórico é rico o bastante** (`REVIEW_MIN_ENTRIES` entradas **ou**
`REVIEW_MIN_WEEKS` semanas de uso — padrão 200 ou 4), gera o review e **envia sozinho** no Telegram.
Abaixo desse limiar, ele não incomoda. Desligue com `REVIEW_AUTO_ENABLED=false` (o `/review` manual
continua funcionando). Cada review é salvo no banco (tabela `reviews`) e vai para o export do Obsidian.

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
Resources/Reviews.md          #   índice dos reviews semanais (Fase 6)
Journal/YYYY-MM-DD.md         # log cronológico do dia
Journal/Reviews/<data>-<id>.md#   cada review semanal como nota (Fase 6)
Slipbox/<id>-<slug>.md        # Zettelkasten: 1 nota atômica plana por entrada
```

- **Zettelkasten:** cada entrada é uma nota atômica em `Slipbox/`, com **frontmatter YAML**
  (id, type, status, due, priority, project, people, tags). No corpo, **só links com significado**:
  um **up-link** (`Up:`) para o MOC-lar da nota (garante que toda nota fica conectada no grafo,
  mesmo sem projeto/pessoa) e, quando houver, o projeto e as pessoas. Nada de link para "dia".
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
- **Fase 5:** ✅ memória semântica (embeddings locais + sqlite-vec), sugestão de conexões e
  `/buscar` por significado (recall semântico + rerank opcional com Claude Haiku; fallback híbrido local).
- **Fase 6:** ✅ insights e proatividade — `/review` semanal com Claude Sonnet, review automático
  agendado (JobQueue, gatilho de 200+ entradas ou 4+ semanas) e reviews salvos no banco e no Obsidian.
