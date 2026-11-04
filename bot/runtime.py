"""Execução demonstrativa controlada; não acessa sistemas externos."""
import asyncio
import os
import time


class SimulationRuntime:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._task = None
        self._state = self._default_state()

    @staticmethod
    def _default_state():
        return {
            "status": "idle",
            "mode": "simulation",
            "last_run_time": None,
            "progress": 0,
            "message": "Pronto para homologação, sem requisições externas.",
            "stats": {"successes": 0, "failures": 0, "conflicts": 0},
        }

    def status(self):
        return {**self._state, "stats": dict(self._state["stats"])}

    async def start(self):
        async with self._lock:
            if self._task is not None and not self._task.done():
                return {"status": "already_running"}
            self._state = self._default_state()
            self._state.update(status="running", last_run_time=time.time(), message="Simulação em execução")
            self._task = asyncio.create_task(self._run())
            return {"status": "started"}

    async def stop(self):
        async with self._lock:
            task = self._task
            if task is None or task.done():
                return {"status": self._state["status"]}
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return {"status": self._state["status"]}

    async def _run(self):
        try:
            delay = max(0.01, min(float(os.getenv("JOB_DELAY_SECONDS", "1")), 30.0))
            for i in range(1, 5):
                await asyncio.sleep(delay)
                self._state.update(progress=25 * i, message=f"Verificação local {i} de 4 concluída")
            self._state.update(status="finished", message="Homologação concluída; nenhuma compra realizada")
        except asyncio.CancelledError:
            self._state.update(status="stopped", message="Simulação interrompida")
            raise
        except Exception:
            self._state.update(status="error", message="Erro interno na simulação")
            raise

    def reset_for_tests(self):
        if self._task is not None and not self._task.done():
            raise RuntimeError("Não é possível reiniciar enquanto estiver executando")
        self._task = None
        self._state = self._default_state()
