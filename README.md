# Chat (novo projeto)

Este é o projeto reescrito dentro da pasta `Chat/`.

## Variáveis de ambiente
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG` (true/false)
- `DJANGO_ALLOWED_HOSTS` (ex: `seu-dominio.com,127.0.0.1`)
- `HF_API_TOKEN`
- `TURNSTILE_SITE_KEY`
- `TURNSTILE_SECRET_KEY`

## Assets estáticos
O `index.html` permanece igual ao original e referencia `bootstrap/` e `staticfiles/`.
Para manter o mesmo visual, copie estas pastas para dentro de `Chat/` ou mantenha-as na raiz do projeto.

## Execução
1. `python manage.py migrate`
2. `python manage.py runserver`

## Limpeza automática
Agende o comando a cada 24h:
`python manage.py limpar_projetos`
