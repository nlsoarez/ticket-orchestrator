"""Monitoramento agendado opt-in. Worker único e sem integrações comerciais.

A API de configurações NÃO consulta os sites. O laço dispara scan() apenas
quando o usuário habilitou explicitamente e chegou o prazo persistido.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from . import monitor
from .workspace import database

router = APIRouter(prefix='/api/monitor', tags=['monitoramento-publico'])
log = logging.getLogger(__name__)


class MonitorScheduleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool
    interval_minutes: int = Field(ge=15, le=1440, strict=True)


def _init(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS monitor_schedule (
        id INTEGER PRIMARY KEY CHECK(id=1),
        enabled INTEGER NOT NULL DEFAULT 0,
        interval_minutes INTEGER NOT NULL DEFAULT 30,
        next_run_at TEXT, last_run_at TEXT, last_outcome TEXT
    )''')
    conn.execute('''INSERT OR IGNORE INTO monitor_schedule
        (id, enabled, interval_minutes) VALUES (1,0,30)''')


def _read(conn):
    row = dict(conn.execute('SELECT enabled,interval_minutes,next_run_at,last_run_at,last_outcome '
                            'FROM monitor_schedule WHERE id=1').fetchone())
    row['enabled'] = bool(row['enabled'])
    return row


def _utc_now():
    return datetime.now(timezone.utc)


@router.get('/schedule')
def get_schedule():
    with database() as conn:
        _init(conn)
        return _read(conn)


@router.put('/schedule')
def put_schedule(body: MonitorScheduleInput):
    """Habilita/desabilita e atualiza intervalo. Não executa scan nesta rota."""
    with database() as conn:
        _init(conn)
        before = _read(conn)
        if before['enabled'] != body.enabled or before['interval_minutes'] != body.interval_minutes:
            due = (_utc_now() + timedelta(minutes=body.interval_minutes)).isoformat() if body.enabled else None
            conn.execute('''UPDATE monitor_schedule SET enabled=?, interval_minutes=?, next_run_at=? WHERE id=1''',
                         (int(body.enabled), body.interval_minutes, due))
        return _read(conn)


def scheduler_tick():
    """Um único ciclo. True se scan() foi efetivamente iniciado.

    Se uma consulta manual estiver em andamento, mantém prazo vencido para
    tentar de novo no ciclo seguinte; não faz consultas paralelas.
    """
    now = _utc_now()
    with database() as conn:
        _init(conn)
        state = _read(conn)
        if not state['enabled'] or state['next_run_at'] is None:
            return False
        if datetime.fromisoformat(state['next_run_at']) > now:
            return False
        if monitor._scan_lock.locked():
            return False
        next_due = (now + timedelta(minutes=state['interval_minutes'])).isoformat()
        conn.execute('UPDATE monitor_schedule SET next_run_at=? WHERE id=1', (next_due,))
    outcome = 'failed'
    try:
        outcome = monitor.scan().get('outcome', 'failed')
    except Exception:
        # Não imprimir segredos e nem encerrar o laço de background.
        log.exception('Falha inesperada no monitoramento agendado')
    finally:
        with database() as conn:
            _init(conn)
            conn.execute('UPDATE monitor_schedule SET last_run_at=?, last_outcome=? WHERE id=1',
                         (_utc_now().isoformat(), outcome))
    return True


async def scheduler_loop():
    """Laço da aplicação: sem execução na inicialização e sem requisição externa no status."""
    while True:
        await asyncio.sleep(30)
        try:
            await asyncio.to_thread(scheduler_tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Erro na verificação do agendamento')
