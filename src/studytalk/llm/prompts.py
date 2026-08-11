SUMMARY_PROMPT = """\
Matéria: {subject}

Você vai receber um áudio em que o aluno está estudando e explicando um conteúdo em \
voz alta (tipo "estudando em voz alta").

Gere um resumo seguindo ESTRITAMENTE esta estrutura:

📝 Resumo — {subject} — [Tópico específico]

🎯 O que foi estudado
(1-2 frases, resumindo o que a pessoa tentou explicar)

📌 Conceitos-chave
- Liste os conceitos citados, usando a explicação/palavras do próprio aluno sempre \
que possível, não uma reescrita genérica de livro.

🧮 Exemplo pra gravar
- Crie você mesmo um exemplo curto e memorável (pode ser numérico, analogia, ou \
frase de efeito) que ilustre o conceito explicado.
- Não copie exemplos do aluno nem de livros didáticos — invente algo NOVO, simples \
e fácil de visualizar/lembrar.
- Priorize ser memorável sobre ser completo: 1-2 linhas, no máximo.
- Se fizer sentido, use números "redondos" ou situações do dia a dia (ex: "imagine \
que você está correndo a 36 km/h numa pista...").

⚠️ Pontos de atenção
- Liste hesitações, erros, dúvidas ou trechos em que o aluno pareceu incerto durante \
a fala. Se não houve nenhum, escreva "Nenhum identificado".

🔑 Frase-chave pra lembrar
- Uma frase curta e memorável (pode ser algo que o próprio aluno falou) que resuma a \
ideia central.

🏷️ Tags: #materia #topico #subtopico

Regras de conteúdo:
- Não invente informação sobre o que o aluno disse ou entendeu (o "Exemplo pra \
gravar" é a única exceção — aí você pode criar livremente).
- Priorize o que o aluno efetivamente disse sobre explicações didáticas genéricas.
- Seja conciso: prefira clareza a completude.
- Responda somente com o resumo em português, sem prefácio.

Formatação (obrigatório — o texto será lido no celular, via Telegram):
- Nunca use LaTeX, Markdown de blog (#, ###, ---, **, ```) nem delimitadores $...$
- Escreva fórmulas em texto legível com Unicode, ex.:
  Ax = A · cos(θ)
  Ay = A · sen(θ)
  R = √(Rx² + Ry²)
- Prefira símbolos Unicode (· √ ² θ) ou palavras (seno, cosseno)
- Use HTML simples do Telegram: <b>títulos</b>, <i>ênfase</i>, <code>fórmulas</code>; \
aplique <b> nos títulos de cada seção (🎯, 📌, 🧮, ⚠️, 🔑, 🏷️)
- Listas com • ou - ; não use tags HTML além de b, i e code
- Escape & < > em texto normal como &amp; &lt; &gt; se aparecerem fora de tags
"""

REVIEW_QUESTION_PROMPT = """\
Com base neste resumo de estudo, gere UMA pergunta aberta que force o aluno a explicar com as próprias palavras (recall ativo).
Responda somente com a pergunta, em português.

Resumo:
{summary}
"""

EVALUATE_ANSWER_PROMPT = """\
Você está avaliando se o aluno lembrou o conteúdo.

Pergunta feita:
{question}

Resumo original (gabarito conceitual):
{summary}

O áudio anexo é a resposta do aluno.

Responda em português no formato:
FEEDBACK: <o que acertou, errou ou esqueceu>
SCORE: <0 ou 1>
"""
