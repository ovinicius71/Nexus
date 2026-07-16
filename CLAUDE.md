
# Projeto: Personal Organizer Bot (bot de organização pessoal com IA)

## Contexto e visão

Sou estudante de Engenharia da Computação, foco em ML/AI e backend. Quero construir um agente pessoal que organiza minha vida: eu envio, ao longo do dia, mensagens soltas com acontecimentos, tarefas, ideias e anotações, e o agente classifica, estrutura e armazena tudo. Com o tempo, conforme acumula dados, ele deve encontrar conexões não óbvias entre minhas notas e me dar dicas sobre minha rotina.

Este repo será público no meu portfólio, então qualidade de código, README e decisões documentadas importam.

## Decisões de arquitetura (já definidas — não questionar, apenas implementar)

- **Captura:** bot no Telegram (futuramente um app próprio, fora de escopo agora)
- **Fonte de verdade:** SQLite (migração futura para Postgres deve ser fácil — usar camada de repositório)
- **Export:** markdown com frontmatter YAML para um vault do Obsidian
- **LLM:** API da Anthropic — Claude Haiku para classificação de entradas, Sonnet para análises/insights
- **Classificação rica por entrada:** tipo, título-resumo, prazo, prioridade, pessoas, projeto — campos ausentes ficam `null`, o modelo NUNCA deve inventar prazo ou prioridade que não estão no texto
- **Insights:** reativos (comandos) no início; proatividade só quando houver dados suficientes (fase final)
- **Entrada na v1:** apenas texto
- **Execução:** local, `python` + `.env` (sem Docker por enquanto)
- **Idioma:** código, nomes e comentários em inglês; README.md em português

## Metodologia de trabalho (IMPORTANTE)

Trabalhe **por fases, uma de cada vez**. Ao concluir uma fase:

1. Rode os testes e mostre como eu valido manualmente (comandos exatos)
2. Resuma o que foi feito e as decisões tomadas
3. **PARE e peça minha validação explícita antes de iniciar a próxima fase**

Não implemente fases futuras antecipadamente. Se algo estiver ambíguo, pergunte antes de codar.

## Stack

- Python 3.11+, `python-telegram-bot` (v21+, async)
- `anthropic` SDK (structured output via tool use ou JSON mode)
- SQLite via `sqlite3` ou SQLAlchemy (preferir SQLAlchemy pela migração futura)
- `pydantic` para schemas, `python-dotenv` para config
- `pytest` para testes
- `.gitignore` deve excluir: `.env`, `*.db`, vault de export — **nenhum dado pessoal pode ir para o repo**

## Schema de dados (ponto de partida — refine se justificar)

```sql
entries(
  id, raw_text, created_at,
  type,        -- idea | task | event | note
  title,       -- short generated summary
  due_date,    -- nullable
  priority,    -- high | medium | low | null
  project,     -- normalized slug, nullable
  status,      -- open | done | archived (tasks)
  llm_json     -- full model response, for audit
)
people(id, name)
entry_people(entry_id, person_id)
corrections(id, entry_id, field, old_value, new_value, corrected_at)
```

A tabela `corrections` é central: cada correção minha vira few-shot example no prompt de classificação (aprendizado incremental barato).

## Fases

### Fase 1 — Fundação: bot + persistência

- Estrutura do projeto (src layout), config via `.env` (tokens Telegram e Anthropic)
- Bot recebe mensagens de texto e salva cru no SQLite com timestamp
- Restringir o bot ao meu chat_id (variável no `.env`)
- Comando `/start` e confirmação simples de salvamento
- README inicial em PT com setup

### Fase 2 — Classificação com LLM

- Ao receber mensagem: chamar Claude Haiku com structured output → preencher os campos da entrada
- Prompt de classificação em arquivo separado e versionável (ex: `prompts/classify.md`)
- Regra crítica: campos não inferíveis do texto = `null` (sem alucinação)
- Responder no Telegram com card-resumo da classificação + botões inline: ✅ correto | ✏️ corrigir tipo | ✏️ corrigir prazo/prioridade
- Correções gravadas em `corrections` e injetadas como few-shot examples nas próximas classificações (últimas N correções)
- Mini-eval: script `evals/run_classify_eval.py` que roda o classificador sobre um JSONL de exemplos rotulados (eu fornecerei ~30-50) e reporta acurácia por campo

### Fase 3 — Consultas

- Comandos: `/tarefas` (abertas, ordenadas por prazo/prioridade), `/hoje` (entradas do dia), `/ideias`, `/eventos`
- Marcar tarefa como feita via botão inline
- Busca livre: `/buscar <termo>` (LIKE simples nesta fase; semântica vem depois)

### Fase 4 — Export para Obsidian

- Script/comando que exporta para um vault: `daily/YYYY-MM-DD.md` com o fluxo do dia + notas atômicas para ideias em `ideas/`
- Frontmatter YAML (type, project, people, tags) e wikilinks `[[]]` para projetos e pessoas
- Export idempotente (rodar duas vezes não duplica)

### Fase 5 — Memória semântica e conexões

- Embeddings de cada entrada (sqlite-vec ou Chroma; justificar a escolha)
- Ao salvar uma entrada nova: buscar top-k similares; acima de um limiar, o bot sugere "isso se conecta com [nota X de tal data] — quer linkar?"
- Aceitar/rejeitar sugestão vira feedback gravado (para calibrar o limiar depois)
- `/buscar` passa a usar busca semântica

### Fase 6 — Insights e proatividade

- `/review`: agente com Claude Sonnet analisa a semana (entradas + histórico agregado) e gera: tarefas recorrentemente adiadas, temas em crescimento, ideias órfãs, padrões de rotina
- Gatilho de proatividade: quando o banco tiver 200+ entradas OU 4+ semanas de uso, agendar (APScheduler) o review semanal automático via mensagem no Telegram
- Guardar os reviews gerados no banco e no export do Obsidian

## Critérios de qualidade

- Testes para a camada de repositório e para o parser da resposta do LLM
- Tratamento de erro em toda chamada de API (retry com backoff, mensagem amigável no Telegram em falha)
- Logging estruturado (nível configurável no `.env`)
- README em PT atualizado ao fim de cada fase: setup, arquitetura, decisões e screenshots/exemplos

Comece pela **Fase 1**.
