"""Cadastro de torcedores, grupos, partidas e intenções de compra.

Sem chamadas de venda, pagamento, scrapers ou armazenamento de biometria/CPF.
SQLite é adequado à VPS única de homologação; para múltiplas réplicas use PostgreSQL.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

router = APIRouter(prefix='/api', tags=['planejamento'])


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Kind(str, Enum):
    socio = 'socio'
    geral = 'geral'


class SalePhase(str, Enum):
    unknown = 'unknown'
    closed = 'closed'
    members = 'members'
    general = 'general'


class GuestPolicy(str, Enum):
    unknown = 'unknown'
    allowed = 'allowed'
    not_allowed = 'not_allowed'


class Membership(InputModel):
    club: str = Field(min_length=2, max_length=70)
    kind: Kind = Kind.geral
    plan: str | None = Field(default=None, max_length=100)

    @model_validator(mode='after')
    def member_has_plan(self):
        if self.kind == Kind.socio and not self.plan:
            raise ValueError('Informe o plano para sócio')
        return self


class PersonIn(InputModel):
    name: str = Field(min_length=2, max_length=120)
    consent_confirmed: bool = False
    identity_confirmed: bool = False
    biometric_confirmed: bool = False
    memberships: list[Membership] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def unique_clubs(self):
        clubs = [m.club.casefold() for m in self.memberships]
        if len(clubs) != len(set(clubs)):
            raise ValueError('Não repita clube na mesma pessoa')
        return self


class PersonPatch(InputModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    consent_confirmed: bool | None = None
    identity_confirmed: bool | None = None
    biometric_confirmed: bool | None = None
    memberships: list[Membership] | None = Field(default=None, max_length=12)


class GroupIn(InputModel):
    name: str = Field(min_length=2, max_length=100)
    member_ids: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def unique_people(self):
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError('Grupo com torcedores duplicados')
        return self


class GroupPatch(InputModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    member_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)


class MatchIn(InputModel):
    home_team: str = Field(min_length=2, max_length=100)
    away_team: str = Field(min_length=2, max_length=100)
    kickoff: datetime
    platform: str = Field(min_length=2, max_length=100)
    ticket_url: HttpUrl | None = None
    sale_phase: SalePhase = SalePhase.unknown
    max_tickets_per_order: int = Field(default=1, ge=1, le=20)
    requires_biometric: bool = False
    guest_policy: GuestPolicy = GuestPolicy.unknown

    @model_validator(mode='after')
    def validate_game(self):
        if self.kickoff.tzinfo is None or self.kickoff.utcoffset() is None:
            raise ValueError('A data do jogo precisa ter fuso horário')
        if self.home_team.casefold() == self.away_team.casefold():
            raise ValueError('Mandante e visitante devem ser diferentes')
        return self


class MatchPatch(InputModel):
    platform: str | None = Field(default=None, min_length=2, max_length=100)
    ticket_url: HttpUrl | None = None
    sale_phase: SalePhase | None = None
    max_tickets_per_order: int | None = Field(default=None, ge=1, le=20)
    requires_biometric: bool | None = None
    guest_policy: GuestPolicy | None = None


class IntentIn(InputModel):
    match_id: str = Field(min_length=1, max_length=80)
    group_id: str = Field(min_length=1, max_length=80)
    buyer_id: str = Field(min_length=1, max_length=80)
    section: str = Field(min_length=2, max_length=120)
    max_unit_cents: int = Field(gt=0, le=100_000_000)
    max_total_cents: int = Field(gt=0, le=100_000_000)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def database():
    file = Path(os.getenv('DATABASE_PATH', '/data/ticket_orchestrator.sqlite3'))
    file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(file, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS people (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, consent_confirmed INTEGER NOT NULL,
            identity_confirmed INTEGER NOT NULL, biometric_confirmed INTEGER NOT NULL,
            memberships_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS groups (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, member_ids_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY, home_team TEXT NOT NULL, away_team TEXT NOT NULL,
            kickoff TEXT NOT NULL, platform TEXT NOT NULL, ticket_url TEXT,
            sale_phase TEXT NOT NULL, max_tickets_per_order INTEGER NOT NULL,
            requires_biometric INTEGER NOT NULL, guest_policy TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS intents (
            id TEXT PRIMARY KEY, match_id TEXT NOT NULL REFERENCES matches(id),
            group_id TEXT NOT NULL REFERENCES groups(id), buyer_id TEXT NOT NULL,
            attendee_ids_json TEXT NOT NULL, section TEXT NOT NULL,
            max_unit_cents INTEGER NOT NULL, max_total_cents INTEGER NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL, object_id TEXT NOT NULL,
            action TEXT NOT NULL, created_at TEXT NOT NULL
        );
        ''')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _id():
    return str(uuid4())


def _row(conn, table, entity_id):
    return conn.execute(f'SELECT * FROM {table} WHERE id = ?', (entity_id,)).fetchone()


def _all(conn, table):
    return conn.execute(f'SELECT * FROM {table} ORDER BY created_at DESC, id DESC').fetchall()


def _activity(conn, category, object_id, action):
    conn.execute('INSERT INTO activity(category, object_id, action, created_at) VALUES(?,?,?,?)',
                 (category, object_id, action, now_iso()))


def _person(row):
    item = dict(row)
    item['memberships'] = json.loads(item.pop('memberships_json'))
    for field in ('consent_confirmed', 'identity_confirmed', 'biometric_confirmed'):
        item[field] = bool(item[field])
    return item


def _group(row):
    item = dict(row)
    item['member_ids'] = json.loads(item.pop('member_ids_json'))
    return item


def _match(row):
    item = dict(row)
    item['requires_biometric'] = bool(item['requires_biometric'])
    return item


def _intent(row):
    item = dict(row)
    item['attendee_ids'] = json.loads(item.pop('attendee_ids_json'))
    return item


def _assert_people(conn, ids):
    if len(set(ids)) != len(ids):
        raise HTTPException(422, 'Torcedores duplicados')
    for pid in ids:
        if not _row(conn, 'people', pid):
            raise HTTPException(422, f'Torcedor inválido: {pid}')


def _write(conn, table, entity_id, changes):
    keys = list(changes)
    sql = f"UPDATE {table} SET " + ', '.join(f'{key}=?' for key in keys) + ' WHERE id=?'
    conn.execute(sql, [changes[k] for k in keys] + [entity_id])


@router.get('/people')
def get_people():
    with database() as conn:
        return [_person(row) for row in _all(conn, 'people')]


@router.post('/people', status_code=201)
def add_person(payload: PersonIn):
    pid = _id()
    with database() as conn:
        conn.execute('''INSERT INTO people VALUES (?,?,?,?,?,?,?)''', (
            pid, payload.name, payload.consent_confirmed, payload.identity_confirmed,
            payload.biometric_confirmed,
            json.dumps([m.model_dump(mode='json') for m in payload.memberships]), now_iso()
        ))
        _activity(conn, 'person', pid, 'created')
        return _person(_row(conn, 'people', pid))


@router.patch('/people/{pid}')
def patch_person(pid: str, payload: PersonPatch):
    changes = payload.model_dump(exclude_unset=True, mode='json')
    if not changes:
        raise HTTPException(422, 'Nenhum campo fornecido')
    if any(value is None for value in changes.values()):
        raise HTTPException(422, 'Campos obrigatórios não podem ser nulos')
    if 'memberships' in changes:
        PersonIn(name='Validação', memberships=payload.memberships)
        changes['memberships_json'] = json.dumps(changes.pop('memberships'))
    with database() as conn:
        if not _row(conn, 'people', pid):
            raise HTTPException(404, 'Torcedor não encontrado')
        _write(conn, 'people', pid, changes)
        _activity(conn, 'person', pid, 'updated')
        return _person(_row(conn, 'people', pid))


@router.get('/groups')
def get_groups():
    with database() as conn:
        return [_group(row) for row in _all(conn, 'groups')]


@router.post('/groups', status_code=201)
def add_group(payload: GroupIn):
    gid = _id()
    with database() as conn:
        _assert_people(conn, payload.member_ids)
        conn.execute('INSERT INTO groups VALUES(?,?,?,?)', (gid, payload.name, json.dumps(payload.member_ids), now_iso()))
        _activity(conn, 'group', gid, 'created')
        return _group(_row(conn, 'groups', gid))


@router.patch('/groups/{gid}')
def patch_group(gid: str, payload: GroupPatch):
    changes = payload.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422, 'Atualização inválida')
    with database() as conn:
        if not _row(conn, 'groups', gid):
            raise HTTPException(404, 'Grupo não encontrado')
        if 'member_ids' in changes:
            GroupIn(name='Validação', member_ids=changes['member_ids'])
            _assert_people(conn, changes['member_ids'])
            changes['member_ids_json'] = json.dumps(changes.pop('member_ids'))
        _write(conn, 'groups', gid, changes)
        _activity(conn, 'group', gid, 'updated')
        return _group(_row(conn, 'groups', gid))


@router.get('/matches')
def get_matches():
    with database() as conn:
        return [_match(row) for row in _all(conn, 'matches')]


@router.post('/matches', status_code=201)
def add_match(payload: MatchIn):
    mid = _id()
    with database() as conn:
        conn.execute('INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?,?)', (
            mid, payload.home_team, payload.away_team, payload.kickoff.isoformat(),
            payload.platform, str(payload.ticket_url) if payload.ticket_url else None,
            payload.sale_phase.value, payload.max_tickets_per_order, payload.requires_biometric,
            payload.guest_policy.value, now_iso()
        ))
        _activity(conn, 'match', mid, 'created')
        return _match(_row(conn, 'matches', mid))


@router.patch('/matches/{mid}')
def patch_match(mid: str, payload: MatchPatch):
    changes = payload.model_dump(mode='json', exclude_unset=True)
    if not changes:
        raise HTTPException(422, 'Nenhum campo fornecido')
    if any(value is None for key, value in changes.items() if key != 'ticket_url'):
        raise HTTPException(422, 'Campos obrigatórios não podem ser nulos')
    with database() as conn:
        if not _row(conn, 'matches', mid):
            raise HTTPException(404, 'Jogo não encontrado')
        _write(conn, 'matches', mid, changes)
        _activity(conn, 'match', mid, 'updated')
        return _match(_row(conn, 'matches', mid))


@router.get('/intents')
def get_intents():
    with database() as conn:
        return [_intent(row) for row in _all(conn, 'intents')]


@router.post('/intents', status_code=201)
def add_intent(payload: IntentIn):
    iid = _id()
    with database() as conn:
        game = _row(conn, 'matches', payload.match_id)
        group = _row(conn, 'groups', payload.group_id)
        if not game or not group:
            raise HTTPException(422, 'Jogo ou grupo inexistente')
        people = json.loads(group['member_ids_json'])
        _assert_people(conn, people)
        if payload.buyer_id not in people:
            raise HTTPException(422, 'Comprador deve pertencer ao grupo')
        if len(people) > game['max_tickets_per_order']:
            raise HTTPException(422, 'Grupo excede o limite informado para a partida')
        if payload.max_total_cents < payload.max_unit_cents * len(people):
            raise HTTPException(422, 'Orçamento total precisa comportar o teto unitário de todos os torcedores')
        conn.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?)', (
            iid, payload.match_id, payload.group_id, payload.buyer_id,
            json.dumps(people), payload.section, payload.max_unit_cents,
            payload.max_total_cents, 'draft', now_iso()
        ))
        _activity(conn, 'intent', iid, 'created')
        return _intent(_row(conn, 'intents', iid))


@router.get('/intents/{iid}/review')
def review_intent(iid: str):
    with database() as conn:
        record = _row(conn, 'intents', iid)
        if not record:
            raise HTTPException(404, 'Intenção não encontrada')
        intent = _intent(record)
        game = _match(_row(conn, 'matches', intent['match_id']))
        people = [_person(_row(conn, 'people', pid)) for pid in intent['attendee_ids']]
    issues = ['integracao_nao_habilitada', 'pagamento_sem_integracao']
    if game['sale_phase'] == 'unknown':
        issues.append('onda_de_venda_nao_confirmada')
    if game['sale_phase'] == 'closed':
        issues.append('venda_fechada')
    if len(people) > game['max_tickets_per_order']:
        issues.append('limite_de_ingressos_excedido')
    if any(not p['consent_confirmed'] for p in people):
        issues.append('consentimento_pendente')
    if any(not p['identity_confirmed'] for p in people):
        issues.append('identidade_nao_verificada_externamente')
    if game['requires_biometric'] and any(not p['biometric_confirmed'] for p in people):
        issues.append('biometria_nao_verificada_externamente')
    if len(people) > 1 and game['guest_policy'] == 'unknown':
        issues.append('regras_convidados_nao_confirmadas')
    if len(people) > 1 and game['guest_policy'] == 'not_allowed':
        issues.append('compra_em_grupo_nao_permitida')
    buyer = next((p for p in people if p['id'] == intent['buyer_id']), None)
    if game['sale_phase'] == 'members' and buyer:
        memberships = buyer['memberships']
        if not any(m['club'].casefold() == game['home_team'].casefold() and m['kind'] == 'socio' for m in memberships):
            issues.append('comprador_sem_prioridade_socio')
    return {
        'intent_id': iid,
        'mode': 'planning_only',
        'can_auto_purchase': False,
        'issues': list(dict.fromkeys(issues)),
        'note': 'Dados de cadastro e disponibilidade não validados junto ao fornecedor. Nenhuma cobrança será iniciada.'
    }


@router.get('/summary')
def summary():
    with database() as conn:
        counts = {name: conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
                  for name in ('people', 'groups', 'matches', 'intents')}
        activities = [dict(row) for row in conn.execute(
            'SELECT category, object_id, action, created_at FROM activity ORDER BY id DESC LIMIT 12'
        ).fetchall()]
        return {**counts, 'recent_activity': activities, 'mode': 'planning_only'}
