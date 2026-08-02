SUMMARY_PROMPT = """\
Matéria: {subject}

O aluno gravou este áudio explicando, com as próprias palavras, o que entendeu da aula.

Gere um resumo claro e útil para revisão futura:
- Organize em pontos principais
- Corrija erros factuais óbvios sem ser pedante
- Complete lacunas importantes de forma breve
- Use linguagem acessível
- Responda somente com o resumo em português, sem prefácio
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
