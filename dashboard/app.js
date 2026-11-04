const $ = id => document.getElementById(id);
const labels = { idle:'Ocioso', running:'Em execução', finished:'Concluído', stopped:'Interrompido', error:'Erro', offline:'Sem conexão' };
let pending = false;
async function api(path, method='GET') {
  const response = await fetch(path, { method, cache:'no-store', headers:{ 'Accept':'application/json' } });
  if (!response.ok) throw new Error(`Resposta HTTP ${response.status}`);
  return response.json();
}
async function refresh() {
  try {
    const data = await api('/api/status');
    const state = data.status || 'offline';
    $('connection').textContent = 'Servidor conectado';
    $('connection').className = 'pill';
    $('status').textContent = labels[state] || state;
    $('message').textContent = data.message || '';
    const p = Math.max(0, Math.min(100, Number(data.progress) || 0));
    $('progress-bar').style.width = `${p}%`;
    $('progress-text').textContent = `${p}% concluído`;
    $('last-run').textContent = data.last_run_time ? new Date(data.last_run_time * 1000).toLocaleString('pt-BR') : '—';
    $('start').disabled = pending || state === 'running';
    $('stop').disabled = pending || state !== 'running';
  } catch (error) {
    $('connection').textContent = 'Sem conexão';
    $('connection').className = 'pill error';
    $('status').textContent = 'Indisponível';
    $('message').textContent = 'Verifique o servidor ou a autenticação.';
    $('start').disabled = true;
    $('stop').disabled = true;
  }
}
async function command(path) {
  pending = true;
  $('start').disabled = true;
  $('stop').disabled = true;
  try {
    await api(path, 'POST');
    await refresh();
  } catch (error) {
    $('message').textContent = `Não foi possível executar o comando: ${error.message}`;
  } finally {
    pending = false;
    await refresh();
  }
}
$('start').addEventListener('click', () => command('/api/start'));
$('stop').addEventListener('click', () => command('/api/stop'));
refresh();
setInterval(refresh, 3000);
