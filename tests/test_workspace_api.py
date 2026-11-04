"""Contrato de API para planejamento de ingressos, sem compras externas."""
import os
import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault('API_KEY', 'this_is_only_a_test_secret_32_chars_long')
from bot.server import app

KEY = {'X-API-Key': os.environ['API_KEY']}


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'tickets.sqlite3'))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as http:
        yield http


@pytest.mark.anyio
async def test_access_control(client):
    assert (await client.get('/api/people')).status_code == 403
    assert (await client.post('/api/people', json={'name': 'Maria'})).status_code == 403


@pytest.mark.anyio
async def test_person_with_two_clubs_and_persistence(client):
    payload = {'name': 'Maria S.', 'consent_confirmed': True, 'identity_confirmed': False, 'biometric_confirmed': False,
               'memberships': [{'club':'Vasco', 'kind':'socio', 'plan':'Gigante'},
                               {'club':'Flamengo', 'kind':'geral', 'plan':None}]}
    res = await client.post('/api/people', json=payload, headers=KEY)
    assert res.status_code == 201, res.text
    person = res.json()
    assert person['id']
    assert len(person['memberships']) == 2
    listed = await client.get('/api/people', headers=KEY)
    assert [x['id'] for x in listed.json()] == [person['id']]
    assert 'cpf' not in str(listed.json()).lower()
    updated = await client.patch(f"/api/people/{person['id']}", json={'identity_confirmed': True}, headers=KEY)
    assert updated.status_code == 200
    assert updated.json()['identity_confirmed'] is True


@pytest.mark.anyio
async def test_reject_sensitive_payment_fields_and_invalid_socio(client):
    assert (await client.post('/api/people', json={
        'name':'Carlos', 'memberships':[{'club':'Vasco','kind':'socio'}]
    }, headers=KEY)).status_code == 422
    assert (await client.post('/api/people', json={'name':'Ana', 'cpf':'12345678900'}, headers=KEY)).status_code == 422
    assert (await client.post('/api/intents', json={'credit_card_number':'4111111111111111'}, headers=KEY)).status_code == 422


@pytest.mark.anyio
async def test_group_match_and_intent_flow(client):
    async def add_person(name, kind='geral', consent=True):
        result = await client.post('/api/people', json={
            'name':name, 'consent_confirmed':consent,
            'memberships':[{'club':'Vasco', 'kind':kind, 'plan':'Estatutário' if kind=='socio' else None}]
        }, headers=KEY)
        assert result.status_code == 201, result.text
        return result.json()['id']
    a = await add_person('Pessoa A', 'socio')
    b = await add_person('Pessoa B', 'geral', False)
    group = await client.post('/api/groups', json={'name':'Família', 'member_ids':[a,b]}, headers=KEY)
    assert group.status_code == 201, group.text
    gid = group.json()['id']
    game = await client.post('/api/matches', json={
        'home_team':'Vasco', 'away_team':'Flamengo', 'kickoff':'2026-11-20T19:00:00-03:00',
        'platform':'A confirmar', 'sale_phase':'members', 'max_tickets_per_order':4,
        'requires_biometric':True, 'guest_policy':'unknown'
    }, headers=KEY)
    assert game.status_code == 201, game.text
    mid = game.json()['id']
    bad_buyer = await client.post('/api/intents', json={
        'match_id':mid,'group_id':gid,'buyer_id':'inexistente','section':'Arquibancada',
        'max_unit_cents':15000,'max_total_cents':30000
    }, headers=KEY)
    assert bad_buyer.status_code == 422
    purchase = await client.post('/api/intents', json={
        'match_id':mid,'group_id':gid,'buyer_id':a,'section':'Arquibancada',
        'max_unit_cents':15000,'max_total_cents':30000
    }, headers=KEY)
    assert purchase.status_code == 201, purchase.text
    intent = purchase.json()
    assert intent['status'] == 'draft'
    assert intent['attendee_ids'] == [a,b]
    review = await client.get(f"/api/intents/{intent['id']}/review", headers=KEY)
    assert review.status_code == 200
    assert review.json()['can_auto_purchase'] is False
    assert 'consentimento_pendente' in review.json()['issues']
    assert 'integracao_nao_habilitada' in review.json()['issues']
    assert 'biometria_nao_verificada_externamente' in review.json()['issues']
    assert len((await client.get('/api/intents', headers=KEY)).json()) == 1
    assert len((await client.get('/api/groups', headers=KEY)).json()) == 1
    assert len((await client.get('/api/matches', headers=KEY)).json()) == 1
    summary = (await client.get('/api/summary', headers=KEY)).json()
    assert summary['people'] == 2 and summary['groups'] == 1 and summary['matches'] == 1 and summary['intents'] == 1
    assert len(summary['recent_activity']) >= 4


@pytest.mark.anyio
async def test_snapshot_of_group_does_not_change_on_group_edit(client):
    ids = []
    for name in ('Um','Dois'):
        r = await client.post('/api/people', json={'name':name}, headers=KEY)
        ids.append(r.json()['id'])
    g = (await client.post('/api/groups', json={'name':'Grupo A', 'member_ids':ids}, headers=KEY)).json()
    m = (await client.post('/api/matches', json={
        'home_team':'Vasco', 'away_team':'Botafogo', 'kickoff':'2026-11-20T19:00:00-03:00',
        'platform':'Não informado', 'sale_phase':'unknown', 'max_tickets_per_order':4,
        'requires_biometric':False, 'guest_policy':'unknown'
    }, headers=KEY)).json()
    i = (await client.post('/api/intents', json={'match_id':m['id'], 'group_id':g['id'], 'buyer_id':ids[0],
         'section':'Arquibancada','max_unit_cents':10000,'max_total_cents':20000}, headers=KEY)).json()
    patch = await client.patch(f"/api/groups/{g['id']}", json={'member_ids':[ids[0]]}, headers=KEY)
    assert patch.status_code == 200, patch.text
    listed = (await client.get('/api/intents', headers=KEY)).json()
    assert listed[0]['attendee_ids'] == ids
    assert i['attendee_ids'] == ids


@pytest.mark.anyio
async def test_missing_reference_and_duplicates_blocked(client):
    bad = await client.post('/api/groups', json={'name':'Inválido', 'member_ids':['does-not-exist']}, headers=KEY)
    assert bad.status_code == 422
    r = (await client.post('/api/people', json={'name':'José'}, headers=KEY)).json()
    dupe = await client.post('/api/groups', json={'name':'Duplicados','member_ids':[r['id'],r['id']]}, headers=KEY)
    assert dupe.status_code == 422


@pytest.mark.anyio
async def test_no_external_purchase_endpoint(client):
    res = await client.post('/api/checkout', json={}, headers=KEY)
    assert res.status_code in (404, 405)

@pytest.mark.anyio
async def test_invalid_game_and_excessive_budget_rejected(client):
    base={'home_team':'Vasco','away_team':'Flamengo','kickoff':'2026-11-20T19:00:00-03:00',
          'platform':'Não informado','sale_phase':'closed','max_tickets_per_order':1}
    no_timezone=await client.post('/api/matches',json={**base,'kickoff':'2026-11-20T19:00:00'},headers=KEY)
    assert no_timezone.status_code == 422
    same_club=await client.post('/api/matches',json={**base,'away_team':'Vasco'},headers=KEY)
    assert same_club.status_code == 422
    bad_link=await client.post('/api/matches',json={**base,'ticket_url':'javascript:alert(1)'},headers=KEY)
    assert bad_link.status_code == 422


@pytest.mark.anyio
async def test_cancelled_sale_and_membership_priority_not_ready(client):
    person=(await client.post('/api/people',json={'name':'Visitante', 'consent_confirmed':True,
                'identity_confirmed':True, 'biometric_confirmed':True,
                'memberships':[{'club':'Flamengo','kind':'socio','plan':'Nação'}]},headers=KEY)).json()
    group=(await client.post('/api/groups',json={'name':'Um', 'member_ids':[person['id']]},headers=KEY)).json()
    game=(await client.post('/api/matches',json={'home_team':'Vasco','away_team':'Flamengo',
           'kickoff':'2026-11-20T19:00:00-03:00','platform':'Não informado',
           'sale_phase':'members','requires_biometric':True,'guest_policy':'unknown'},headers=KEY)).json()
    intent=(await client.post('/api/intents',json={'match_id':game['id'],'group_id':group['id'],
            'buyer_id':person['id'],'section':'Visitante','max_unit_cents':12000,
            'max_total_cents':12000},headers=KEY)).json()
    flagged=(await client.get(f"/api/intents/{intent['id']}/review",headers=KEY)).json()
    assert 'comprador_sem_prioridade_socio' in flagged['issues']
    updated=await client.patch(f"/api/matches/{game['id']}",json={'sale_phase':'closed'},headers=KEY)
    assert updated.status_code == 200
    closed=(await client.get(f"/api/intents/{intent['id']}/review",headers=KEY)).json()
    assert 'venda_fechada' in closed['issues']
    assert closed['can_auto_purchase'] is False


@pytest.mark.anyio
async def test_reject_group_over_game_limit_and_invalid_buyer(client):
    a=(await client.post('/api/people',json={'name':'Alice'},headers=KEY)).json()['id']
    b=(await client.post('/api/people',json={'name':'Bruno'},headers=KEY)).json()['id']
    group=(await client.post('/api/groups',json={'name':'Dois','member_ids':[a,b]},headers=KEY)).json()
    game=(await client.post('/api/matches',json={'home_team':'Vasco','away_team':'Flamengo',
            'kickoff':'2026-11-20T19:00:00-03:00','platform':'Não informado',
            'max_tickets_per_order':1},headers=KEY)).json()
    payload={'match_id':game['id'],'group_id':group['id'],'buyer_id':a,'section':'Arquibancada',
             'max_unit_cents':10000,'max_total_cents':20000}
    exceeds=await client.post('/api/intents',json=payload,headers=KEY)
    assert exceeds.status_code==422
    assert len((await client.get('/api/intents',headers=KEY)).json())==0
