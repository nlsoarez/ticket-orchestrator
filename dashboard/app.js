'use strict';
const $ = id => document.getElementById(id);
const state = { people: [], groups: [], matches: [], intents: [], summary: null, personEditing: null, groupEditing: null, matchEditing: null, working: false };
const sectionLabels = {overview:'Visão geral',people:'Torcedores',groups:'Grupos de compra',matches:'Partidas',intents:'Planejamentos',monitor:'Monitoramento'};
const subtitulos = {overview:'Organize pessoas, grupos e jogos antes da abertura de vendas.',people:'Cadastre pessoas e vínculos com clubes sem armazenar documentos sensíveis.',groups:'Monte grupos de compra com vários portadores de ingressos.',matches:'Registre partidas e condições informadas manualmente.',intents:'Crie intenções com orçamento definido e identifique pendências.',monitor:'Consulte manualmente notícias públicas de ingressos nos sites oficiais.'};
const saleLabels = {unknown:'Não confirmada',closed:'Fechada',members:'Sócios',general:'Público geral'};
const issuesLabels = {
  integracao_nao_habilitada:'Integração comercial não habilitada',
  pagamento_sem_integracao:'Pagamento automático indisponível',
  onda_de_venda_nao_confirmada:'Onda de vendas não confirmada',
  venda_fechada:'Venda fechada (informação manual)',
  limite_de_ingressos_excedido:'Quantidade acima do limite informado',
  consentimento_pendente:'Autorização de um portador pendente',
  identidade_nao_verificada_externamente:'Identificação não confirmada externamente',
  biometria_nao_verificada_externamente:'Biometria não confirmada externamente',
  regras_convidados_nao_confirmadas:'Regras de convidados não confirmadas',
  compra_em_grupo_nao_permitida:'Compra em grupo não permitida (informação manual)',
  comprador_sem_prioridade_socio:'Comprador sem prioridade de sócio informada'
};
const simulated = {idle:'Ocioso',running:'Executando',finished:'Concluído',stopped:'Interrompido',error:'Erro'};
const brl = cents => (cents / 100).toLocaleString('pt-BR', {style:'currency',currency:'BRL'});
const dateTime = value => value ? new Date(value).toLocaleString('pt-BR', {dateStyle:'short', timeStyle:'short'}) : '—';
const getName = id => state.people.find(p => p.id === id)?.name || 'Torcedor indisponível';
function node(tag, cls, text) { const x = document.createElement(tag); if (cls) x.className = cls; if (text !== undefined) x.textContent = String(text); return x; }
function empty(container, description) { container.replaceChildren(node('div','empty',description)); }
function badge(text, tone='neutral') { return node('span','tag '+tone,text); }
function button(text, action, secondary=false) { const b = node('button','btn '+(secondary?'secondary ':'')+'small',text); b.type='button'; b.addEventListener('click',action); return b; }
function headline(title, subtitle) { const wrap=node('div','entry-text'); wrap.append(node('strong','entry-title',title), node('div','entry-subtitle',subtitle)); return wrap; }
function entry(title, subtitle, children=[]) { const wrap=node('div','list-entry'); const head=node('div','list-entry-head'); head.append(headline(title,subtitle)); const actions=node('div','entry-actions'); children.forEach(child => actions.append(child)); head.append(actions); wrap.append(head); return wrap; }
function showFeedback(message, error=false) { const box=$('feedback'); box.textContent=message; box.className='feedback '+(error?'feedback-error':'feedback-success'); clearTimeout(showFeedback.timer); showFeedback.timer=setTimeout(()=>box.classList.add('hidden'),7000); }
async function api(path, options={}) {
  const response=await fetch(path,{...options,cache:'no-store',headers:{'Accept':'application/json',...(options.body?{'Content-Type':'application/json'}:{})}});
  let payload=null;
  try { payload=await response.json(); } catch { /* HTTP error without JSON */ }
  if (!response.ok) {
    const reason = Array.isArray(payload?.detail) ? payload.detail.map(item=>item.msg).join('; ') : payload?.detail;
    throw new Error(reason || `Servidor respondeu ${response.status}`);
  }
  return payload;
}
async function post(path,data) {return api(path,{method:'POST',body:JSON.stringify(data)});}
async function patch(path,data) {return api(path,{method:'PATCH',body:JSON.stringify(data)});}
async function runTask(callback) {if(state.working)return;state.working=true;try{await callback();await refreshData();}catch(e){showFeedback(e.message,true);}finally{state.working=false;}}
function showView(view) {
  if(!sectionLabels[view])return;
  document.querySelectorAll('.nav-button').forEach(x=>{const active=x.dataset.view===view;x.classList.toggle('active',active);x.setAttribute('aria-current',active?'page':'false');});
  document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id==='view-'+view));
  $('currentSection').textContent=sectionLabels[view]; $('pageTitle').textContent=sectionLabels[view]; $('pageSubtitle').textContent=subtitulos[view];
  if(view==='monitor')loadMonitor();
  if(innerWidth < 800)window.scrollTo({top:0,behavior:'smooth'});
}
document.querySelectorAll('[data-view], [data-open]').forEach(x=>x.addEventListener('click',()=>showView(x.dataset.view||x.dataset.open)));

async function refreshData() {
  const [people,groups,matches,intents,summary]=await Promise.all(['/api/people','/api/groups','/api/matches','/api/intents','/api/summary'].map(p=>api(p)));
  Object.assign(state,{people,groups,matches,intents,summary});
  $('connection').className='connection connected'; $('connection').replaceChildren(node('i'),document.createTextNode('Servidor online'));
  renderOverview(); renderPeople(); renderGroups(); renderMatches(); renderIntents(); renderGroupSelectors(); renderIntentSelectors();
}
function renderOverview() {
  const summary=state.summary||{};
  for(const field of ['People','Groups','Matches','Intents'])$('metric'+field).textContent=summary[field.toLowerCase()]??0;
  const box=$('activityList');box.replaceChildren();
  const activity=summary.recent_activity||[];
  if(!activity.length){empty(box,'Nenhuma atividade registrada.');return;}
  const labels={person:'Torcedor',group:'Grupo',match:'Partida',intent:'Planejamento',created:'criado',updated:'atualizado'};
  for(const item of activity){const row=node('div','activity-row');row.append(node('span','activity-icon','•'),headline((labels[item.category]||item.category)+' '+(labels[item.action]||item.action),dateTime(item.created_at)));box.append(row);}
}
function renderPeople() {
  const box=$('peopleList');box.replaceChildren();$('peopleCount').textContent=state.people.length;
  if(!state.people.length){empty(box,'Nenhum torcedor cadastrado.');return;}
  for(const p of state.people){
    const el=entry(p.name,p.memberships.length ? p.memberships.map(m=>m.club+' · '+(m.kind==='socio'?'Sócio'+(m.plan?' ('+m.plan+')':''):'Geral')).join('  |  ') : 'Sem vínculo com clubes',[
      button('Editar',()=>editPerson(p),true)
    ]);
    const tags=node('div','tags');tags.append(badge(p.consent_confirmed?'Autorização declarada':'Autorização pendente',p.consent_confirmed?'good':'warn'));
    tags.append(badge(p.biometric_confirmed?'Biometria declarada':'Biometria pendente',p.biometric_confirmed?'neutral':'warn'));
    el.append(tags);box.append(el);
  }
}
function addMembershipRow(data={club:'Vasco',kind:'geral',plan:null}) {
  const row=node('div','membership-row');
  const club=node('select');club.setAttribute('aria-label','Clube');
  for(const s of ['Vasco','Flamengo','Outro']){const option=node('option','',s);option.value=s;club.append(option);}club.value=['Vasco','Flamengo'].includes(data.club)?data.club:'Outro';
  const kind=node('select');kind.setAttribute('aria-label','Vínculo');
  [['geral','Não sócio'],['socio','Sócio']].forEach(([value,text])=>{const o=node('option','',text);o.value=value;kind.append(o);});kind.value=data.kind;
  const plan=node('input');plan.placeholder='Nome do plano';plan.maxLength=100;plan.value=data.plan||'';plan.setAttribute('aria-label','Plano de sócio');
  const remove=button('×',()=>row.remove(),true);remove.setAttribute('aria-label','Remover vínculo');
  const sync=()=>{plan.disabled=kind.value!=='socio';if(plan.disabled)plan.value='';};kind.addEventListener('change',sync);sync();
  row.append(club,kind,plan,remove);$('membershipRows').append(row);
}
function getMemberships() {
  return [...$('membershipRows').children].map(row=>{
    const [club,kind,plan]=row.children; return {club:club.value,kind:kind.value,plan:kind.value==='socio'?plan.value.trim():null};
  });
}
function clearPersonEdit() {
  state.personEditing=null;$('personForm').reset();$('personFormTitle').textContent='Novo torcedor';$('personSubmit').textContent='Cadastrar torcedor';$('personCancel').classList.add('hidden');$('membershipRows').replaceChildren();addMembershipRow();
}
function editPerson(p) {
  showView('people');state.personEditing=p.id;$('personFormTitle').textContent='Editar torcedor';$('personSubmit').textContent='Salvar alterações';$('personCancel').classList.remove('hidden');
  $('personName').value=p.name;$('personConsent').checked=p.consent_confirmed;$('personIdentity').checked=p.identity_confirmed;$('personBiometric').checked=p.biometric_confirmed;
  $('membershipRows').replaceChildren();for(const m of p.memberships)addMembershipRow(m);if(!p.memberships.length)addMembershipRow();
  $('personName').focus();
}
$('addMembership').addEventListener('click',()=>addMembershipRow());$('personCancel').addEventListener('click',clearPersonEdit);
$('personForm').addEventListener('submit',e=>{e.preventDefault();runTask(async()=>{
  const payload={name:$('personName').value.trim(),consent_confirmed:$('personConsent').checked,
    identity_confirmed:$('personIdentity').checked,biometric_confirmed:$('personBiometric').checked,memberships:getMemberships()};
  if(state.personEditing)await patch('/api/people/'+encodeURIComponent(state.personEditing),payload);
  else await post('/api/people',payload);
  clearPersonEdit();showFeedback('Torcedor salvo com sucesso.');
});});

function renderGroupSelectors() {
  const box=$('groupMembers');const previous=[...box.querySelectorAll('input:checked')].map(x=>x.value);box.replaceChildren();
  if(!state.people.length){empty(box,'Cadastre um torcedor para criar grupos.');return;}
  for(const p of state.people){const label=node('label','check selectable');const c=node('input');c.type='checkbox';c.value=p.id;c.checked=previous.includes(p.id);label.append(c,node('span','',p.name));box.append(label);}
}
function renderGroups() {
  const box=$('groupsList');box.replaceChildren();$('groupsCount').textContent=state.groups.length;
  if(!state.groups.length){empty(box,'Nenhum grupo cadastrado.');return;}
  for(const g of state.groups){
    const el=entry(g.name,`${g.member_ids.length} portador(es)`,[button('Editar membros',()=>editGroup(g),true)]);
    const names=node('div','member-list',g.member_ids.map(getName).join(' · '));el.append(names);box.append(el);
  }
}
function clearGroupEdit() {state.groupEditing=null;$('groupForm').reset();$('groupFormTitle').textContent='Novo grupo';$('groupSubmit').textContent='Salvar grupo';$('groupCancel').classList.add('hidden');renderGroupSelectors();}
function editGroup(g){showView('groups');state.groupEditing=g.id;$('groupFormTitle').textContent='Editar grupo';$('groupSubmit').textContent='Atualizar grupo';$('groupCancel').classList.remove('hidden');$('groupName').value=g.name;for(const c of $('groupMembers').querySelectorAll('input'))c.checked=g.member_ids.includes(c.value);$('groupName').focus();}
$('groupCancel').addEventListener('click',clearGroupEdit);
$('groupForm').addEventListener('submit',e=>{e.preventDefault();runTask(async()=>{
  const member_ids=[...$('groupMembers').querySelectorAll('input:checked')].map(x=>x.value);
  if(!member_ids.length)throw Error('Selecione pelo menos um torcedor.');
  const payload={name:$('groupName').value.trim(),member_ids};
  if(state.groupEditing)await patch('/api/groups/'+encodeURIComponent(state.groupEditing),payload);
  else await post('/api/groups',payload);
  clearGroupEdit();showFeedback('Grupo salvo com sucesso.');
});});

function renderMatches() {
  const box=$('matchesList');box.replaceChildren();$('matchesCount').textContent=state.matches.length;
  if(!state.matches.length){empty(box,'Nenhuma partida cadastrada.');return;}
  for(const m of state.matches){const el=entry(`${m.home_team} × ${m.away_team}`,dateTime(m.kickoff),[button('Editar regras',()=>editMatch(m),true)]);
    const tags=node('div','tags');tags.append(badge(saleLabels[m.sale_phase]||m.sale_phase, m.sale_phase==='general'?'good':'neutral'),badge(m.platform));el.append(tags);
    if(m.ticket_url){const link=node('a','external-link','Abrir página de venda ↗');link.href=m.ticket_url;link.target='_blank';link.rel='noopener noreferrer';el.append(link);}
    box.append(el);
  }
}
function clearMatchEdit(){state.matchEditing=null;$('matchForm').reset();$('matchFormTitle').textContent='Nova partida';$('matchSubmit').textContent='Cadastrar partida';$('matchCancel').classList.add('hidden');for(const id of ['matchHome','matchAway','matchKickoff'])$(id).disabled=false;}
function editMatch(m){
  showView('matches');state.matchEditing=m.id;$('matchFormTitle').textContent='Editar regras';$('matchSubmit').textContent='Atualizar regras';$('matchCancel').classList.remove('hidden');
  $('matchHome').value=m.home_team;$('matchAway').value=m.away_team;
  const date=new Date(m.kickoff);$('matchKickoff').value=[date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-')+'T'+String(date.getHours()).padStart(2,'0')+':'+String(date.getMinutes()).padStart(2,'0');
  for(const id of ['matchHome','matchAway','matchKickoff'])$(id).disabled=true;
  $('matchPlatform').value=m.platform;$('matchLink').value=m.ticket_url||'';$('matchPhase').value=m.sale_phase;$('matchMax').value=m.max_tickets_per_order;$('matchBio').checked=m.requires_biometric;$('matchGuest').value=m.guest_policy;
  $('matchPlatform').focus();
}
$('matchCancel').addEventListener('click',clearMatchEdit);
$('matchForm').addEventListener('submit',e=>{e.preventDefault();runTask(async()=>{
  const common={platform:$('matchPlatform').value.trim(), ticket_url:$('matchLink').value.trim()||null,
    sale_phase:$('matchPhase').value, max_tickets_per_order:Number($('matchMax').value),
    requires_biometric:$('matchBio').checked,guest_policy:$('matchGuest').value};
  if(state.matchEditing)await patch('/api/matches/'+encodeURIComponent(state.matchEditing),common);
  else {const date=new Date($('matchKickoff').value);if(Number.isNaN(date.getTime()))throw Error('Informe uma data válida.');
    await post('/api/matches',{...common,home_team:$('matchHome').value.trim(),away_team:$('matchAway').value.trim(),kickoff:date.toISOString()});}
  clearMatchEdit();showFeedback('Partida salva. Regras dependem de validação no operador oficial.');
});});

function refillSelect(id,records,label,selected=''){
  const field=$(id);field.replaceChildren();const first=node('option','',`Selecione ${label}`);first.value='';field.append(first);
  for(const record of records){const option=node('option','',record.name);option.value=record.id;field.append(option);}
  if(selected)field.value=selected;
}
function renderIntentSelectors(){
  const currentMatch=$('intentMatch').value,currentGroup=$('intentGroup').value;
  refillSelect('intentMatch',state.matches.map(m=>({id:m.id,name:`${m.home_team} × ${m.away_team} — ${dateTime(m.kickoff)}`})),'a partida',currentMatch);
  refillSelect('intentGroup',state.groups.map(g=>({id:g.id,name:g.name+' ('+g.member_ids.length+' pessoas)'})),'o grupo',currentGroup);
  refreshBuyers();
}
function refreshBuyers(){
  const group=state.groups.find(x=>x.id===$('intentGroup').value);const current=$('intentBuyer').value;
  refillSelect('intentBuyer',(group?.member_ids||[]).map(id=>({id,name:getName(id)})),'o comprador',current);
}
$('intentGroup').addEventListener('change',refreshBuyers);
function cents(value){const str=String(value).trim();if(!/^\d+(?:[,.]\d{1,2})?$/.test(str))throw Error('Use valores em reais, como 150,00.');const [reais,dec='']=str.replace(',','.').split('.');const amount=Number(reais)*100+Number(dec.padEnd(2,'0'));if(!Number.isSafeInteger(amount)||amount<=0)throw Error('O orçamento precisa ser maior que zero.');return amount;}
function renderIntents(){
  const box=$('intentsList');box.replaceChildren();$('intentsCount').textContent=state.intents.length;
  if(!state.intents.length){empty(box,'Nenhum planejamento criado.');return;}
  for(const i of state.intents){const m=state.matches.find(x=>x.id===i.match_id),g=state.groups.find(x=>x.id===i.group_id);
    const el=entry(m?`${m.home_team} × ${m.away_team}`:'Partida não encontrada',`${g?.name||'Grupo'} · ${i.attendee_ids.length} portador(es)`,[button('Ver pendências',()=>openReview(i.id),true)]);
    const tags=node('div','tags');tags.append(badge('Rascunho'),badge(i.section),badge('Teto '+brl(i.max_total_cents)));
    el.append(tags);box.append(el);
  }
}
async function openReview(id){try{const r=await api('/api/intents/'+encodeURIComponent(id)+'/review');const box=$('reviewPanel');box.classList.remove('hidden');box.replaceChildren();
  box.append(node('h3','', 'Verificação de pendências'),node('p','muted',r.note));
  const list=node('ul');for(const issue of r.issues)list.append(node('li','',issuesLabels[issue]||issue));box.append(list);
  showView('intents');
}catch(e){showFeedback(e.message,true);}}
$('intentForm').addEventListener('submit',e=>{e.preventDefault();runTask(async()=>{
  const group=state.groups.find(g=>g.id===$('intentGroup').value);
  if(!group)throw Error('Selecione um grupo.');
  const unit=cents($('intentUnit').value),total=cents($('intentTotal').value);
  if(total<unit*group.member_ids.length)throw Error('O teto total precisa cobrir o teto por ingresso de todos os portadores.');
  await post('/api/intents',{match_id:$('intentMatch').value,group_id:group.id,buyer_id:$('intentBuyer').value,
    section:$('intentSection').value.trim(),max_unit_cents:unit,max_total_cents:total});
  $('intentForm').reset();$('reviewPanel').classList.add('hidden');showFeedback('Planejamento salvo. Nenhuma compra foi iniciada.');
});});

async function refreshSimulation(){
  try{const data=await api('/api/status');const st=data.status;
    $('simulationStatus').textContent=simulated[st]||st;$('simulationMessage').textContent=data.message||'';
    $('simulationPill').textContent=simulated[st]||st;
    $('simulationPill').className='tag '+(st==='running'?'warn':st==='finished'?'good':'neutral');
    const p=Math.max(0,Math.min(100,Number(data.progress)||0));$('progressBar').style.width=p+'%';$('progressText').textContent=p+'% concluído';
    $('simStart').disabled=state.working||st==='running';$('simStop').disabled=state.working||st!=='running';
  }catch(e){$('simulationStatus').textContent='Serviço indisponível';$('simStart').disabled=true;$('simStop').disabled=true;}
}
async function simulationCommand(path){await runTask(async()=>{await api(path,{method:'POST'});showFeedback('Comando de simulação executado.');});await refreshSimulation();}
$('simStart').addEventListener('click',()=>simulationCommand('/api/start'));
$('simStop').addEventListener('click',()=>simulationCommand('/api/stop'));


// V3: status é leitura local de SQLite; a rede externa só é consultada após clique explícito.
let monitorBusy=false;
function renderMonitor(data){
  $('monitorNewCount').textContent=`${data.new_count||0} novos`;
  const sources=$('monitorSources'); sources.replaceChildren();
  for(const item of (data.sources||[])){
    const status=item.error ? 'Falha na consulta' : item.last_success ? `${item.found_count} notícia(s) encontradas` : 'Ainda não consultado';
    const box=entry(item.club,status+' · '+(item.last_attempt?dateTime(item.last_attempt):'—'));
    const link=node('a','external-link','Abrir notícias oficiais ↗');
    link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';box.append(link);
    if(item.error){box.append(node('p','monitor-error',item.error));}
    sources.append(box);
  }
  const list=$('monitorArticles');list.replaceChildren();
  if(!(data.announcements||[]).length){empty(list,'Nenhum comunicado registrado. A primeira consulta cria a base histórica.');return;}
  for(const article of data.announcements){
    const box=entry(article.title,article.club+' · Detectado '+dateTime(article.discovered_at));
    const tags=node('div','tags');tags.append(badge(article.is_new?'Novo comunicado':'Histórico',article.is_new?'good':'neutral'));
    box.append(tags);
    const href=node('a','external-link','Ler comunicado no site oficial ↗');href.href=article.url;
    href.target='_blank';href.rel='noopener noreferrer';box.append(href);list.append(box);
  }
}
async function loadMonitor(){
  try{const data=await api('/api/monitor/status');renderMonitor(data);}
  catch(e){showFeedback('Não foi possível consultar o monitoramento: '+e.message,true);}
}
$('monitorScan').addEventListener('click',async()=>{
  if(monitorBusy)return;monitorBusy=true;
  $('monitorScan').disabled=true;$('monitorScan').textContent='Consultando sites oficiais...';
  try{
    const data=await api('/api/monitor/scan',{method:'POST'});renderMonitor(data);
    const message=data.outcome==='ok'?'Consulta concluída.':data.outcome==='partial_failure'?'Consulta parcial: confira os avisos de cada fonte.':'As fontes não puderam ser consultadas; confira os avisos.';
    showFeedback(message,data.outcome==='failed');
  }catch(e){showFeedback('Consulta não concluída: '+e.message,true);await loadMonitor();}
  finally{monitorBusy=false;$('monitorScan').disabled=false;$('monitorScan').textContent='Verificar comunicados agora';}
});
$('monitorAck').addEventListener('click',async()=>{
  try{renderMonitor(await api('/api/monitor/ack',{method:'POST'}));showFeedback('Comunicados marcados como lidos.');}
  catch(e){showFeedback('Falha ao marcar como lidos: '+e.message,true);}
});

clearPersonEdit();
refreshData().catch(e=>{$('connection').className='connection offline';$('connection').textContent='Servidor indisponível';showFeedback('Não foi possível carregar os dados: '+e.message,true);});
refreshSimulation();
setInterval(refreshSimulation,4000);
