# Ticket Orchestrator — pacote para GitHub + VPS Hostinger

> **Estado:** versão de **homologação**. O painel, a API, a autenticação, o controle de início/parada e o empacotamento estão implementados. **Não há automação real de compras ou chamadas de checkout a terceiros.** A integração só deve ser habilitada depois de validar a API de destino e a autorização de acesso. Este pacote não inclui disparos massivos, proxies rotativos ou medidas para contornar detecção de robôs.

## Por que a versão enviada não foi colocada diretamente em produção?

A origem era um texto Markdown com trechos de código, não arquivos organizados. O componente `dashboard/app/page.tsx` está truncado, e há problemas de segurança e de consistência funcional (chave em `NEXT_PUBLIC_`, TLS desabilitado no cliente, CORS irrestrito e botão parar que não cancela a tarefa). A versão original indicava rotas `api.exemplo.com/cart` e `/checkout`, sem API real comprovada. Também usava uma versão antiga do Next.js. Por isso, esta entrega prioriza **deploy verificável** e converte o dashboard em arquivos estáticos (sem Node.js e sem Vercel), mantendo FastAPI no servidor.

## Evolução para ingressos de futebol — V2A

O foco do produto foi refinado para **Vasco e Flamengo**, contemplando sócios, público geral, convidados e várias pessoas por intenção de compra. A especificação de domínio, segurança, limites financeiros, integrações e estados está em [docs/arquitetura-aquisicao-futebol.md](docs/arquitetura-aquisicao-futebol.md).

A validação de elegibilidade e orçamento (sem chamadas externas) está em [bot/purchase_planning.py](bot/purchase_planning.py); seus 14 testes de regressão estão em [tests/test_purchase_planning.py](tests/test_purchase_planning.py). Execute localmente com:

```bash
python -m unittest discover -s tests -p 'test_purchase_planning.py' -v
```

**Esta base de planejamento ainda não está conectada ao dashboard/API e não realiza compras ou pagamentos.** O serviço atualmente implantado na Hostinger não foi alterado. Não utilizamos GitHub Actions.

## V2B — Cadastros, partidas e planejamentos persistentes (04/11/2026)

Esta versão acrescenta um **workspace operacional** ao painel de homologação:

- **Torcedores:** nome de identificação, vínculos independentes por clube (sócio ou público geral), plano de sócio, declarações de consentimento, identificação e biometria. Os indicadores são declarações do operador, **não validações junto ao clube**.
- **Grupos:** vários portadores por grupo; ao criar um planejamento, a composição é congelada para preservar auditoria mesmo se o grupo for editado.
- **Partidas:** mandante, visitante, data com fuso, plataforma, URL informada manualmente, fase de venda, limite informado de ingressos, política de convidados e exigência de biometria.
- **Planejamentos:** grupo, comprador integrante do grupo, setor e limites de preço unitário/total em centavos. A pré-verificação informa pendências.
- **Persistência:** banco SQLite em volume Docker nomeado `orchestrator_data`, separado de código, painel e segredos. O volume persiste durante atualizações com `docker compose up`; **nunca use `docker compose down -v`** sem backup.
- **Segurança:** Caddy Basic Auth + API key configurados no servidor; sem CPFs, cartões, CVVs, imagens faciais ou credenciais de clubes armazenadas. A aplicação está acessível apenas no localhost `8182` por padrão.

**Limitação deliberada:** não existe integração comercial, monitoramento de disponibilidade em tempo real, compra automática, reserva nem pagamento. Não marque declarações como verificações oficiais. A API de planejamento não inicia checkout ou cobrança.

### Atualização manual da VPS Hostinger (sem GitHub Actions)

Com o serviço já instalado em `/opt/ticket-orchestrator` e acesso ao **terminal da VPS**:

```bash
cd /opt/ticket-orchestrator
git status --short
git pull --ff-only
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl -I http://127.0.0.1:8182/
```

A última resposta deverá ser **401 Unauthorized** sem credenciais; isso indica que o gateway exige autenticação. Se `git status --short` mostrar alterações locais, investigue antes do `git pull` (não use `git reset --hard`).

**Backup dos cadastros**, sem interromper os outros contêineres:

```bash
cd /opt/ticket-orchestrator
mkdir -p /root/ticket-backups
docker compose exec -T app python -c 'import sqlite3; src=sqlite3.connect("/data/ticket_orchestrator.sqlite3"); dst=sqlite3.connect("/tmp/ticket-backup.sqlite3"); src.backup(dst); dst.close(); src.close()'
```

**Atenção:** o comando acima **não funciona como backup persistente** se usado literalmente, pois `/tmp` é temporário e interno ao contêiner. O procedimento recomendado é fazer backup consistente a partir de uma pasta de backup persistente montada para esse fim ou utilizar `docker run` com os volumes adequados, sem copiar o banco SQLite em uso com `cp`. Não remova volumes de dados. Antes de usar o sistema com cadastros reais, defina retenção e cópias de segurança regulares.

### Testes locais (sem CI automatizado)

```bash
python -m pip install -r bot/requirements.txt pytest httpx
python -m pytest -q tests
node --check dashboard/app.js  # opcional: requer Node.js
```

Os testes de API devem ser executados **localmente ou na VPS**, não pelo GitHub Actions. O motor de simulação anterior continua disponível em Visão geral.


## Estrutura

```text
.
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

O projeto está publicado em **https://github.com/nlsoarez/ticket-orchestrator**. Este repositório já contém a API de homologação, dashboard, arquivos de Docker e testes locais. Não é necessário enviar o ZIP novamente.

**Importante:** o repositório está configurado como **público**. Se a intenção for manter código e informações de infraestrutura privados, altere em **Settings → General → Danger Zone → Change repository visibility → Private**. A mudança de visibilidade não revoga cópias já obtidas. Nunca envie segredos de API, senhas reais nem o arquivo `.env`.

**Não utilizamos GitHub Actions.** O GitHub armazena o código-fonte; testes e implantação são executados manualmente, sem workflows de CI/CD.

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
