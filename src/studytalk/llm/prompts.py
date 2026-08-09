SUMMARY_PROMPT = """\
Matéria: {subject}

O aluno gravou este áudio explicando, com as próprias palavras, o que entendeu da aula.

Gere um resumo claro e útil para revisão futura no Telegram:
- Organize em pontos principais, com seções curtas
- Corrija erros factuais óbvios sem ser pedante
- Complete lacunas importantes de forma breve
- Use linguagem acessível
- Responda somente com o resumo em português, sem prefácio

Formatação (obrigatório — o texto será lido no celular):
- Nunca use LaTeX, Markdown de blog (#, ###, ---) nem delimitadores $...$
- Escreva fórmulas em texto legível com Unicode, ex.:
  Ax = A · cos(θ)
  Ay = A · sen(θ)
  R = √(Rx² + Ry²)
- Prefira símbolos Unicode (· √ ² θ) ou palavras (seno, cosseno)
- Use HTML simples do Telegram: <b>títulos</b>, <i>ênfase</i>, <code>fórmulas</code>
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
