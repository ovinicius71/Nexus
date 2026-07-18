# 📢 Post do LinkedIn — Nexus (experimento de 1 semana)

Documento de trabalho para o post sobre o **Nexus**. A ideia: usar o bot por **uma semana**
e publicar contando a história com a metodologia **STAR** (Situação · Tarefa · Ação · Resultado).

> **Como usar:** rode o experimento por 7 dias, anote os números na seção _"Dados da semana"_,
> escolha um dos rascunhos, cole os números e publique. Poste junto de um **print ou GIF** do bot
> em ação (aumenta muito o alcance).

---

## 🎯 Estrutura STAR (o mapa da narrativa)

| Etapa | No post |
| --- | --- |
| **S — Situação** | Uma das partes mais difíceis da faculdade é organizar **tempo, ideias e tarefas**. Eu usava o **Obsidian** para isso. |
| **T — Tarefa** | Com o tempo, esbarrei em **limitações**: capturar uma ideia no corrido dava atrito, tudo era **manual** (criar arquivo, taguear, linkar) e o app **não tinha inteligência** — não classificava, não conectava sozinho, não me lembrava do que eu adiava. |
| **A — Ação** | Construí o **Nexus**: um bot de Telegram que **captura mensagens soltas**, classifica com **IA (Claude)**, guarda no SQLite, encontra **conexões semânticas** e ainda **exporta para o próprio Obsidian** — juntando a captura sem atrito com a organização que eu já gostava. |
| **R — Resultado** | Depois de **1 semana** usando: [preencher com números + aprendizados]. |

---

## ✍️ Rascunho principal (pronto para colar)

> Substitua os trechos `[entre colchetes]` pelos seus dados reais da semana.

---

**Uma das coisas mais difíceis da faculdade não é o conteúdo. É a organização.**

Tempo, ideias, tarefas, aquele insight que aparece no meio do ônibus… tudo competindo pela mesma
cabeça. Por um bom tempo eu tentei resolver isso com o **Obsidian** — e ele é ótimo para *pensar*.

Mas no dia a dia eu esbarrava sempre nas mesmas paredes:

- 📝 **Capturar dava atrito** — abrir o app, criar o arquivo, escolher a pasta… e a ideia se perdia.
- 🏷️ **Tudo era manual** — taguear, definir prazo, linkar nota com nota.
- 🤖 **Faltava inteligência** — o Obsidian guarda o que eu escrevo, mas não me diz *"isso se conecta
  com aquela nota de duas semanas atrás"* nem *"você vem adiando essa tarefa"*.

Então decidi construir a ferramenta que eu queria usar: o **Nexus**. 🧠

É um **bot de Telegram** onde eu jogo mensagens soltas ao longo do dia — e ele:

- 🧩 **classifica** cada uma com IA (Claude) em tarefa/ideia/evento/nota, com prazo, prioridade,
  projeto e pessoas — sem inventar nada que eu não escrevi;
- 🔗 **conecta** notas parecidas usando embeddings locais (offline) e me sugere links;
- 💬 **responde perguntas** sobre as minhas próprias notas (RAG);
- 🧠 gera um **review semanal** com os padrões da minha rotina;
- 📤 e **exporta tudo para o Obsidian** — porque a captura sem atrito virou a porta de entrada, e o
  Obsidian continua sendo onde eu penso.

Passei **uma semana** usando de verdade. O resultado:

- 📥 **[X]** entradas capturadas sem sair do Telegram
- 🔗 **[Y]** conexões entre ideias que eu não teria feito na mão
- ⏱️ **[um aprendizado concreto — ex.: "parei de perder ideia no corrido"]**
- 🧠 e o review da semana me mostrou **[um padrão real que o review apontou]**

No fim, o que mais me marcou foi perceber quanto de organização é, na verdade, um problema de
**atrito de captura** — e como um pouco de IA no lugar certo resolve isso.

⚙️ Por baixo: Python, `python-telegram-bot`, SQLAlchemy + SQLite, `sentence-transformers` + `sqlite-vec`
para memória semântica local, e a API da Anthropic (Claude Haiku para o barato/frequente, Sonnet para
as análises). Tudo aberto no meu GitHub 👇

🔗 github.com/ovinicius71/Nexus

Se você também sofre com organização na faculdade (ou no trabalho), me conta nos comentários como
você resolve — e se toparia testar algo assim. 💬

#Python #IA #InteligenciaArtificial #Claude #Anthropic #ProdutividadePessoal #Obsidian
#EngenhariaDeComputacao #DesenvolvimentoDeSoftware #Backend #ProjetosPessoais

---

## ✍️ Variação curta (para quem prefere post enxuto)

**Uma das coisas mais difíceis da faculdade é a organização — de tempo, ideias e tarefas.**

Eu usava o Obsidian, mas esbarrava sempre no mesmo: capturar dava atrito, tudo era manual e faltava
inteligência para conectar as coisas.

Então construí o **Nexus**: um bot de Telegram que captura minhas mensagens soltas, **classifica com
IA (Claude)**, encontra **conexões semânticas** entre as notas e ainda **exporta para o Obsidian**.

Testei por uma semana: **[X entradas]**, **[Y conexões]** e um review que me mostrou **[padrão]**.

🛠️ Python · Claude (Anthropic) · SQLite + sqlite-vec · embeddings locais
🔗 github.com/ovinicius71/Nexus

#Python #IA #Claude #Produtividade #Obsidian #EngenhariaDeComputacao

---

## 📊 Dados da semana (preencher enquanto usa)

Anote ao longo dos 7 dias — depois é só transportar para o rascunho.

- Entradas capturadas: **____**
- Tarefas concluídas: **____**
- Conexões sugeridas / aceitas: **____ / ____**
- Correções de classificação que você fez: **____**
- O que o `/review` da semana apontou (um padrão real): **_______________________________**
- Um momento concreto em que o bot ajudou (história pequena e específica): **_________________**
- Uma limitação/atrito que ainda notou (honestidade dá credibilidade): **_____________________**

> 💡 Um comando útil para fechar a semana: `/review` (resumo com tarefas adiadas, temas em alta,
> ideias órfãs e padrões de rotina). Bons números para o post saem daí.

---

## 🚀 Dicas de publicação

- **Gancho na 1ª linha.** O LinkedIn corta o texto em ~3 linhas — a primeira frase precisa prender.
  ("Uma das coisas mais difíceis da faculdade não é o conteúdo. É a organização.")
- **Mídia vende.** Anexe um **print do card de classificação** ou um **GIF curto** do fluxo
  (mandar msg → card → /review). Posts com imagem/vídeo alcançam bem mais.
- **Conte uma história específica**, não só features. O momento "perdi uma ideia no ônibus e o bot
  salvou" conecta mais que uma lista.
- **Mostre o engenheiro.** A linha da stack sinaliza suas skills para recrutadores.
- **CTA + link.** Pergunta no fim (gera comentário) e link do GitHub.
- **Quantidade de hashtags:** 3–5 costuma render melhor que 10+.
- **Horário:** dias de semana pela manhã ou início da noite costumam ter mais alcance.
- **Responda os comentários** na 1ª hora — impulsiona o alcance.
