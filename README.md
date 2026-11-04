# Ticket Orchestrator — pacote para GitHub + VPS Hostinger

> **Estado:** versão de **homologação**. O painel, a API, a autenticação, o controle de início/parada e o empacotamento estão implementados. **Não há automação real de compras ou chamadas de checkout a terceiros.** A integração só deve ser habilitada depois de validar a API de destino e a autorização de acesso. Este pacote não inclui disparos massivos, proxies rotativos ou medidas para contornar detecção de robôs.

## Por que a versão enviada não foi colocada diretamente em produção?

A origem era um texto Markdown com trechos de código, não arquivos organizados. O componente `dashboard/app/page.tsx` está truncado, e há problemas de segurança e de consistência funcional (chave em `NEXT_PUBLIC_`, TLS desabilitado no cliente, CORS irrestrito e botão parar que não cancela a tarefa). A versão original indicava rotas `api.exemplo.com/cart` e `/checkout`, sem API real comprovada. Também usava uma versão antiga do Next.js. Por isso, esta entrega prioriza **deploy verificável** e converte o dashboard em arquivos estáticos (sem Node.js e sem Vercel), mantendo FastAPI no servidor.

## Estrutura

```text
.
├── .github/workflows/ci.yml        # testes no GitHub
├── bot/                            # FastAPI + execução de homologação
│   ├── __init__.py
│   ├── runtime.py
│   ├── server.py
│   ├── requirements.txt
│   └── Dockerfile
├── dashboard/                      # painel HTML/CSS/JS, sem compilação
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── tests/                          # testes de API
├── docker-compose.yml              # padrão, não ocupa portas públicas da VPS
├── docker-compose.public.yml       # opcional, VPS dedicada com HTTPS
├── Caddyfile                       # login protegido por hash de senha
├── .env.example
└── README.md
```

## 1. GitHub — repositório existente

O projeto está publicado em **https://github.com/nlsoarez/ticket-orchestrator**. Este repositório já contém a API de homologação, dashboard, arquivos de Docker, testes e integração contínua. Não é necessário enviar o ZIP novamente.

**Importante:** o repositório está configurado como **público**. Se a intenção for manter código e informações de infraestrutura privados, altere em **Settings → General → Danger Zone → Change repository visibility → Private**. A mudança de visibilidade não revoga cópias já obtidas. Nunca envie segredos de API, senhas reais nem o arquivo `.env`.

O fluxo `.github/workflows/ci.yml` executa **somente os testes automatizados** a cada push na branch `main`. Não faz deploy automático e não altera a VPS.

## 2. VPS Hostinger com Docker

**Se já há sites/portais na VPS, use o `docker-compose.yml` padrão.** Ele usa apenas `127.0.0.1:8182` e não altera as portas públicas `80/443` nem reinicia outros contêineres. A Hostinger disponibiliza template de Ubuntu com Docker/Compose pré-instalados.

Acesse por SSH:

```bash
ssh root@IP_DA_VPS
# confira ferramentas antes de prosseguir:
docker --version
docker compose version
```

Para um repositório privado, configure uma *deploy key* somente leitura conforme o guia da Hostinger: https://www.hostinger.com/support/how-to-deploy-from-private-github-repository-on-hostinger-docker-manager/ . Depois faça o clone do repositório na VPS (com sua chave SSH autorizada) e entre na pasta. Alternativamente, envie o ZIP por `scp` para validar localmente antes da integração com GitHub.

```bash
cd /opt
# Substitua pela URL SSH privada que sua VPS tem autorização para ler.
git clone git@github.com:nlsoarez/ticket-orchestrator.git
cd ticket-orchestrator
cp .env.example .env
```

Gere um segredo de API:

```bash
openssl rand -hex 32
```

Gere o hash bcrypt da senha de acesso ao painel (o comando pergunta a senha de forma interativa):

```bash
docker run --rm -it caddy:2.11.7 caddy hash-password
```

Edite `.env`: substitua `API_KEY` pelo segredo gerado, `ADMIN_PASSWORD_HASH` pelo hash gerado (mantenha as **aspas simples** por causa do `$`) e, opcionalmente, `ADMIN_USERNAME`. Depois:

```bash
chmod 600 .env
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl -I http://127.0.0.1:8182/
```

**Resultado esperado:** `401 Unauthorized` sem usuário/senha. A API deve ficar protegida, não pública.

Para usar o painel com segurança antes de configurar um domínio, abra **no seu PC** um túnel SSH:

```bash
ssh -N -L 8182:127.0.0.1:8182 root@IP_DA_VPS
```

No navegador do PC, acesse `http://localhost:8182` e autentique com o usuário/senha de `ADMIN_USERNAME`/senha escolhida. O túnel SSH protege o tráfego, apesar do endereço local ser HTTP.

## 3. Publicar em domínio próprio

### VPS compartilhada com outros serviços (recomendado neste cenário)

Aponte um subdomínio (por exemplo, `orchestrator.seudominio.com.br`) para o IP público da VPS. No **proxy reverso já existente** (Nginx, Traefik, Caddy), crie uma rota HTTPS que direcione o subdomínio para `http://127.0.0.1:8182`. Mantenha a autenticação do Caddy interno. Não edite configurações de sites existentes sem primeiro conferir como as portas e os certificados são gerenciados.

### VPS dedicada ou portas públicas livres

Configure `APP_DOMAIN` no `.env`, crie registro DNS A para a VPS e execute **em vez** do Compose padrão:

```bash
docker compose -f docker-compose.public.yml up -d --build
```

Esse modo usa **80/443**, com certificado HTTPS automático via Caddy. Só deve ser utilizado se essas portas estiverem livres; em VPS compartilhada, causaria conflito ou indisponibilidade.

## 4. Atualizações

Na VPS, dentro da pasta do projeto:

```bash
git pull --ff-only
docker compose up -d --build
docker compose ps
```

No modo de VPS dedicada, inclua `-f docker-compose.public.yml` nos comandos.

Para automação futura via GitHub Actions, a Hostinger publica o fluxo oficial: https://github.com/hostinger/deploy-on-vps . Requer `HOSTINGER_API_KEY` em *Secrets*, `HOSTINGER_VM_ID` em *Variables* e autorização de leitura para repositório privado. **Não ative deploy automático antes de confirmar proxy, segredos e testes.**

## 5. Verificação e segurança

- A API exige `X-API-Key` em todas as rotas `/api/*`. O navegador nunca recebe esse segredo: o proxy adiciona o cabeçalho apenas na comunicação interna.
- O painel exige HTTP Basic Auth, com hash bcrypt. Não é adequado expor esse login por HTTP público; use HTTPS ou túnel SSH.
- No modo padrão, a VPS não abre portas públicas novas: apenas a porta local `8182` é usada.
- `POST /api/stop` cancela de fato a execução demonstrativa.
- O estado é guardado em memória e será reiniciado se o contêiner reiniciar. Essa versão serve para homologação, não para orquestração distribuída.
- Os testes cobrem autenticação, status, start duplicado, término e cancelamento.
- Nada nesta versão contata uma API de ingresso nem executa compras.

Para testar localmente:

```bash
python -m pip install -r bot/requirements.txt pytest httpx
PYTHONPATH=. python -m pytest -q tests
```

Para logs:

```bash
docker compose logs --tail=100 app gateway
```

## Pendências para uma eventual integração real

1. Documentação oficial da API-alvo e autorização explícita para automatizar operações.
2. Contrato de autenticação, respostas de carrinho e compra, limites permitidos, idempotência e tratamento de erros.
3. Critérios de negócio para não duplicar cobranças/pedidos e implementação de auditoria persistente.

Não use uma carga concorrente de checkout ou rotação de proxies para contornar os limites de terceiros.
