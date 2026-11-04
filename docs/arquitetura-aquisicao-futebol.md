# Ticket Orchestrator — arquitetura de aquisição de ingressos de futebol

**Estado atual:** especificação de produto + validação local de regras. A aplicação já instalada na VPS continua com painel e simulação. **Não há compra real nem acesso comercial autorizado ativado.**

## Objetivo

Preparar aquisições de ingressos para jogos do Vasco, Flamengo e outros clubes, contemplando:
- titulares sócios, sócios estatutários e público geral;
- vários portadores de ingresso por intenção de compra, inclusive convidados, sempre nos limites do plano e da partida;
- compra e pagamento sem presença do usuário **apenas quando o fornecedor permitir integração comercial e o pagamento puder ser concluído sem autenticação adicional**;
- alertas e retomada assistida quando houver biometria, autenticação bancária, CAPTCHA ou fila que exija ação humana.

## Dados e entidades

1. Pessoa: ID interno, identificação nominal, autorização individual; referências a registros externos de documento e biometria. Não armazenar templates faciais.
2. Conta de bilheteria: pessoa titular, plataforma, escopos, estado da sessão autorizada. Nunca armazenar credenciais em texto simples.
3. Vínculo de sócio: clube, plano, validade, elegibilidade na partida; independente por clube.
4. Convidado: relação pessoa/titular, cadastro prévio no fornecedor e limite associado ao plano.
5. Partida: mandante, visitante, estádio, setores de cada torcida, operador de bilheteria por lote e regras daquele jogo.
6. Onda de vendas: fase, horário, classes de elegibilidade, limite de ingressos por titular.
7. Intenção de compra: grupo de pessoas, setores aceitáveis, orçamento unitário e total, autorização prévia com prazo, status e chave de idempotência.
8. Método de pagamento: somente token/referência gerada por operador compatível; **nunca guardar PAN, CVV, PIN ou dados de autenticação do banco**.
9. Tentativa: referência de reserva e pedido, valor, estado, erros e auditoria mínima sem dados pessoais desnecessários.

## Pré-validações obrigatórias

- Confirmar início da onda correta (sócio ou público geral); plano de prioridade deve valer para a partida.
- Verificar cada portador, biometria obrigatória, consentimento e cadastro de convidado previamente aprovado.
- Não duplicar portador, exceder número de ingressos, superar limite financeiro nem usar setor de torcida incompatível.
- Só enviar reserva/compra por API oficial com permissão expressa e limites de chamada respeitados.
- Registrar idempotência persistente e consultar pedido existente após erro ou timeout, antes de nova cobrança.
- Quando autenticação forte de cartão ou identidade for exigida, marcar como aguardando ação humana, sem contornar o mecanismo.
- Dados públicos de calendário e ingressos não provam acesso a uma API comercial nem disponibilidade em tempo real.

## Arquitetura dos módulos

Painel web → API FastAPI → PostgreSQL (estado e auditoria) → Worker de filas controladas → Adaptadores por plataforma → Reservas e pagamentos autorizados.

Módulos planejados: Cadastro de Pessoas, Filiações/Planos, Calendário de Jogos, Regras das Ondas, Intenções e Orçamentos, Monitoramento, Integrações, Pedidos, Alertas e Auditoria.

Contratos de adaptador: discover_event, sales_windows, rules, check_availability, reserve, checkout, reconcile, cancel. Não assumir que os canais oferecem todos os métodos.

## Etapas

- **V2A — iniciada:** regras puras em bot/purchase_planning.py e 14 testes em tests/test_purchase_planning.py. Não faz rede, nem altera o serviço atual.
- **V2B:** persistência, API autenticada para pessoas, grupos e intenções; painel e logs.
- **V2C:** monitoramento de informações oficiais e alertas; aquisição assistida.
- **V2D:** integrações comerciais **somente mediante autorização** do fornecedor, tokenização de pagamento e homologação end-to-end, com prevenção de duplicidade.

## Referências verificadas em 04/11/2026

- Vasco, sócios, geral, visitantes e convidados: https://vasco.com.br/vasco/informacoes-sobre-ingressos-vasco-x-palmeiras-campeonato-brasileiro-2026/
- Flamengo, cadastro por portador e biometria: https://www.flamengo.com.br/noticias/ingressos/flamengo-x-santos--informacoes-sobre-venda-de-ingressos-para-o-duelo-valido-pelo-brasileiro
- Clássico Vasco x Flamengo (mandante Vasco, operação ElevenTickets): https://wap.flamengo.com.br/noticias/ingressos/vasco-x-flamengo-informacoes-sobre-ingressos-para-o-classico-pelo-brasileirao
- PCI Security Standards Council, proteção de CVV: https://www.pcisecuritystandards.org/faqs/1280/
