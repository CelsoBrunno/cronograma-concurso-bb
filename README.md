# Estudos BB — Agente Comercial

Organizador local de estudos para o concurso do Banco do Brasil (Escriturário / Agente Comercial).  
Não substitui o Gran Cursos: controla **progresso do edital**, **horas líquidas** e **acertos/erros** das questões feitas em outra plataforma.

## O que tem

- 9 disciplinas e ~405 tópicos importados do HTML do Gran
- Status por tópico: pendente → estudando → completo → revisado
- % do edital coberto (geral e por disciplina)
- Cronômetro com pausa (tempo líquido) + log de questões **no mesmo fluxo**
- Fila do dia com repetição espaçada simples
- Dashboard e histórico de sessões
- Painel inicial com o plano do dia
- Cronograma automático (estimativa de tempo por aula)
- SQLite local (sem login)

## Como rodar

```bash
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_topicos
python manage.py runserver
```

Abra http://127.0.0.1:8000/

## Cronograma

1. Abra **Cronograma**
2. Escolha a data para encerrar, os dias da semana e a estimativa por aula
3. Clique em **Gerar / regenerar cronograma**

O sistema calcula quantos minutos por dia são necessários para as aulas pendentes caberem até essa data. O painel mostra o bloco de hoje. As durações das videoaulas vêm do Gran (`00:31:42` etc.); o plano soma um extra configurável para questões (padrão +15 min).

## Fluxo típico

1. Veja a **Fila do dia** ou abra uma disciplina
2. Clique em **Sessão** / **Estudar**
3. Estude no Gran com o cronômetro rodando (pause quando parar)
4. Ao finalizar, informe **acertos/erros** e opcionalmente mude o status do tópico
5. O sistema agenda a próxima revisão (1 → 2 → 4 → … dias; volta para 1 se aproveitamento &lt; 60%)

## Reimportar tópicos

```bash
python manage.py seed_topicos
```

Para apagar e recriar a lista de tópicos (não apaga o histórico de sessões de forma agressiva, mas status dos tópicos some):

```bash
python manage.py seed_topicos --reset
```

Os dados de seed estão em `data/topicos_gran.json`.

## Observação

Se alguma disciplina veio com menos aulas no HTML (ex.: Português parcialmente expandido no paste), dá para completar depois pelo admin (`/admin/`) ou reenviando o HTML expandido.
