# V3 — Monitoramento manual de comunicados públicos

**Estado:** Implementação local testada com HTML simulado. Consulta real à internet **ainda precisa ser homologada na VPS**. A versão não executa compra, reserva, login, biometria, pagamento ou contorno de filas.

## Fontes iniciais

| Clube | Fonte oficial de notícias | Situação |
| --- | --- | --- |
| Flamengo | `https://www.flamengo.com.br/noticias/ingressos` | Listagem pública verificada via consulta web em 04/11/2026; leitura pela VPS e parser pendentes de homologação. |
| Vasco | `https://vasco.com.br/noticias/` | Consulta a listagem JSON pública observada no Chrome: `https://fancontentapi-vasco.vasco.com.br/api/owner/297/newsArticles?page=1&size=13`. IDs estáveis; `link:null` na resposta de exemplo. |

**Não utilizar sites de terceiros ou domínios parecidos** para pagamentos. Comunicados são informativos: status e horário das vendas devem ser conferidos no canal oficial de cada partida.

## Uso

1. Acesse `Monitoramento` no painel.
2. Clique em `Verificar comunicados agora` para iniciar uma consulta **manual**.
3. A primeira consulta bem-sucedida por clube cria uma base histórica **sem marcar notícias antigas como novas**.
4. Nas consultas subsequentes, URLs novas são marcadas como `Novo comunicado`, sem duplicação no banco.
5. `Marcar lidos` limpa a contagem de novidades sem excluir artigos.

Não existe agendamento automático nesta fase. Abertura do painel, atualização da página e GET `/api/monitor/status` **não fazem acesso externo**. Se um site recusar a consulta, demorar demais, não apresentar links legíveis ou mudar a estrutura, o painel registra o erro e preserva os resultados de outras fontes.

## Contrato de API

Proteção: Caddy Basic Auth no navegador e `X-API-Key` interno para todas as rotas `/api/monitor/*`.

- `GET /api/monitor/status` — 200 com `mode`, `sources` (tentativa, sucesso, erro por clube), `announcements` e `new_count`. Não consulta rede externa.
- `POST /api/monitor/scan` — 200 com status e `outcome` (`ok`, `partial_failure`, `failed`). Faz até uma consulta HTTPS pública por fonte: JSON para Vasco e HTML para Flamengo. 409 se outra consulta estiver em andamento. Respostas de erro por fonte aparecem no campo `error`.
- `POST /api/monitor/ack` — 200, limpa `is_new` de todos os anúncios e retorna o status. Não apaga artigos.
- Sem chave de API válida: 403 (ou 503 para configuração sem chave).

**Limites:** apenas URLs de origem configuradas no código; sem entrada de URLs arbitrárias; HTTPS obrigatório; redirecionamentos para outros hosts recusados; timeout de 8 s por fonte; limite de resposta de 600 KB; links do Flamengo apenas dentro do domínio do clube; a API de notícias do Vasco é fixa e validada, com até 13 itens na página consultada; máximo de 60 artigos no retorno.

## Persistência e deploy

Tabelas criadas **somente no primeiro acesso ao monitor** dentro do SQLite atual: `monitor_sources` e `monitor_announcements`. Não há exclusão de tabelas anteriores, nem migração destrutiva. O volume Docker `ticket-orchestrator_orchestrator_data` permanece.

Na VPS compartilhada, use exclusivamente `docker-compose.yml` padrão:

```bash
cd /opt/ticket-orchestrator
git status --short
git pull --ff-only
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Não executar `docker compose down -v` e não utilizar `docker-compose.public.yml` (portas 80/443 já ocupadas por outros projetos).

## Limitações

- Não extrai datas, ondas ou preços de maneira validada: notícias encontradas não são oferta confirmada.
- Não mostra estoque de bilheteria, nem verifica elegibilidade no fornecedor.
- Não envia alertas externos (WhatsApp, Telegram ou e-mail); novidades são destacadas no painel **após consulta manual**.
- Páginas renderizadas em JavaScript podem gerar falha visível em vez de resultados.
- Não monitora atualizações de uma URL já conhecida, somente novas URLs.
- Não faz compra nem pagamento.

## Correção V3.1 — Fonte de notícias do Vasco

A página do Vasco retorna um HTML mínimo (SPA). A partir de uma inspeção manual no Chrome em 04/11/2026, verificou-se uma requisição **pública** GET `https://fancontentapi-vasco.vasco.com.br/api/owner/297/newsArticles?page=1&size=13`, retornando um JSON com `header.codigo=1` e `data.items` contendo `id`, `title`, `articleBody`, `createdAt` e `link`. O primeiro lote de 13 itens fornecido para homologação tinha notícias de ingressos com IDs `1577773`, `1574745` e `1573504`.

O monitor agora faz uma consulta somente ao endpoint fixo e permitido, sem cookies, sessão, senha ou fluxos de compra. A API pública **não é a API comercial de bilheteria**. Usa ID por artigo como chave estável, filtrando notícias relacionadas a ingressos pelo título. `articleBody` não é armazenado. Os itens observados vieram com `link:null`; portanto, o painel **não inventa URLs individuais**: abre a listagem `https://vasco.com.br/noticias/` com aviso de que não há link direto comprovado.

A resposta vazia (items=[] ou nenhuma notícia de ingresso na página) é uma consulta válida com 0 notícias relevantes, não falha; um envelope JSON malformado ou código de erro é registrado como falha. Uma página de 13 itens pode omitir anúncio antigo ou fora da primeira página. Esta versão ainda não garante cobertura de todas as matérias e exige homologação real na VPS. Nenhuma consulta automática em background é iniciada.

## V3.2 — Agendamento opcional na VPS

Implementação: `bot/monitor_scheduler.py`, FastAPI lifespan e botão na aba Monitoramento.
- O agendamento começa **desativado** e não acessa fontes externas até o usuário ativar.
- Intervalos aceitos pela API: **15 a 1.440 minutos**, no painel 15/30/60/180 minutos.
- O próximo disparo é gravado em `monitor_schedule` no mesmo volume SQLite, com data UTC.
- Um laço assíncrono com um único worker verifica a configuração a cada 30 segundos. A consulta utiliza o mesmo `scan()` protegido por lock, em thread para não bloquear outras rotas.
- Um início/reinício de contêiner preserva configuração e próxima consulta; se a próxima consulta venceu durante a indisponibilidade, um ciclo será executado após até 30 segundos do início.
- A atualização do painel a cada minuto faz **somente GET no banco local**, sem acionar sites.
- A primeira consulta bem-sucedida de cada fonte estabelece histórico mesmo com 0 notícias (corrige caso em que a página contém itens sem ingressos); itens subsequentes serão identificados como novos.
- Erros das fontes aparecem individualmente no painel; `last_outcome` indica o resultado do último ciclo automático.
- A ativação só ocorre por `PUT /api/monitor/schedule` autenticado, com corpo `{"enabled":true,"interval_minutes":30}`. GET nunca inicia consultas. 422 para intervalos fora de 15–1440 ou valores inválidos.
- Sem notificações push externas, compras, checkout, dados sensíveis, GitHub Actions ou exposição de novas portas públicas.
- **Limite:** consulta a primeira página de 13 matérias do Vasco; outras páginas e alterações em matérias existentes ainda não são detectadas. O HTML do Flamengo também pode mudar.
