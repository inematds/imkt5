"""Recipe Runner — state machine que executa uma receita.

Contratos:

- O runner NÃO executa o trabalho. Ele resolve estágios prontos (cujos
  `needs` já completaram), constrói jobs e entrega a um `JobDispatcher`.
- O runner NÃO sabe sobre fila. Isso fica com o `JobDispatcher`.
- O runner RECEBE eventos de término de job (`on_job_finished`) e avança
  a máquina.
- Aprovações pausam o runner; retomadas vêm de `on_approval_decided`.

Essa separação permite testar o runner com um dispatcher mock.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> datetime:
    """UTC aware — evita timestamps mistos (com/sem tzinfo) no DB."""
    return datetime.now(timezone.utc)
from enum import Enum
from typing import Any, Protocol

from imkt4.recipes.expressions import evaluate_when, resolve
from imkt4.recipes.loader import Recipe, RecipeStage
from imkt4.types.approvals import (
    Approval,
    ApprovalDecision,
    ApprovalMode,
)
from imkt4.types.jobs import Job, JobPriority


def _apply_global_approval_override(
    approval: Approval, run_input: dict[str, Any]
) -> Approval:
    """Item 7 — se run_input tem `approval_mode`, sobrescreve o mode
    declarado na receita. Permite promover todos stages pra human
    (casos premium) sem editar a receita.

    Aceita aliases: `human`, `auto`, `agent`. `none` desliga todo gate.
    """
    override = run_input.get("approval_mode")
    if not override:
        return approval
    alias_map = {
        "human": ApprovalMode.USER,
        "auto": ApprovalMode.AUTO_REVIEWER,
        "agent": ApprovalMode.AUTO_REVIEWER,
        "none": ApprovalMode.NONE,
        "user": ApprovalMode.USER,
        "auto_reviewer": ApprovalMode.AUTO_REVIEWER,
        "human_reviewer": ApprovalMode.HUMAN_REVIEWER,
    }
    new_mode = alias_map.get(str(override).lower())
    if new_mode is None:
        return approval
    # Recria Approval (frozen) com novo mode
    return Approval(
        mode=new_mode,
        timeout_seconds=approval.timeout_seconds,
        reviewer_role=approval.reviewer_role,
        reviewer_worker=approval.reviewer_worker,
        criteria=approval.criteria,
        escalation=approval.escalation,
    )


class StageStatus(str, Enum):
    PENDING = "pending"
    SKIPPED = "skipped"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class StageState:
    stage_id: str
    status: StageStatus = StageStatus.PENDING
    # jobs disparados pelo stage (1 se nem parallel nem fanout; N senão)
    job_ids: list[str] = field(default_factory=list)
    # outputs por job (ordem: match com job_ids)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # output consolidado — se 1 job, é o dict; se N, dict com "outputs": [...]
    @property
    def output(self) -> dict[str, Any]:
        if len(self.outputs) == 1:
            return self.outputs[0]
        return {"outputs": self.outputs}


@dataclass
class RecipeRun:
    run_id: str
    tenant_id: str
    user_id: str
    recipe: Recipe
    input: dict[str, Any]
    # snapshot do tenant (perfil, bindings) no momento do run
    tenant_ctx: dict[str, Any]
    origin_channel: str
    origin_channel_external_id: str
    stages: dict[str, StageState] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)

    def is_finished(self) -> bool:
        return all(
            s.status in (StageStatus.SUCCESS, StageStatus.SKIPPED, StageStatus.FAILED)
            for s in self.stages.values()
        )

    def has_failed(self) -> bool:
        return any(s.status == StageStatus.FAILED for s in self.stages.values())

    def context(self) -> dict[str, Any]:
        """Contexto para resolver expressões ($.input, $.stages, $.tenant)."""
        return {
            "input": self.input,
            "tenant": self.tenant_ctx,
            "stages": {
                sid: {"output": s.output, "status": s.status.value}
                for sid, s in self.stages.items()
                if s.status in (StageStatus.SUCCESS, StageStatus.SKIPPED)
            },
        }


class JobDispatcher(Protocol):
    """Interface que o runner usa pra pedir execução de um job."""

    async def dispatch(self, job: Job) -> None: ...


class ApprovalGate(Protocol):
    """Interface que o runner usa pra pedir uma aprovação."""

    async def request(
        self,
        *,
        run: RecipeRun,
        stage: RecipeStage,
        approval: Approval,
        artifacts: dict[str, Any],
    ) -> None: ...


class RecipeRunner:
    """Executor de uma receita. Uma instância gerencia um RecipeRun."""

    def __init__(
        self,
        dispatcher: JobDispatcher,
        approval_gate: ApprovalGate,
        runs_repo: Any | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._approvals = approval_gate
        self._runs: dict[str, RecipeRun] = {}
        # job_id → (run_id, stage_id, slot_index)
        self._job_index: dict[str, tuple[str, str, int]] = {}
        self._lock = asyncio.Lock()
        self._runs_repo = runs_repo

    async def _persist(self, run: RecipeRun) -> None:
        """Grava run no Postgres se repo disponível. Fail-silent."""
        if self._runs_repo is None:
            return
        try:
            await self._runs_repo.upsert(run)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger("imkt4.runner").warning(
                "runs_repo.upsert falhou: %s", exc,
            )

    # ── public API ────────────────────────────────────────────────────
    async def start(
        self,
        *,
        recipe: Recipe,
        tenant_id: str,
        user_id: str,
        input: dict[str, Any],
        tenant_ctx: dict[str, Any],
        origin_channel: str,
        origin_channel_external_id: str,
    ) -> RecipeRun:
        run = RecipeRun(
            run_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            recipe=recipe,
            input=input,
            tenant_ctx=tenant_ctx,
            origin_channel=origin_channel,
            origin_channel_external_id=origin_channel_external_id,
            stages={s.id: StageState(stage_id=s.id) for s in recipe.stages},
        )
        self._runs[run.run_id] = run
        await self._persist(run)
        await self._advance(run)
        await self._persist(run)
        return run

    def get_run(self, run_id: str) -> RecipeRun:
        return self._runs[run_id]

    def list_runs(self, *, limit: int = 50, tenant_id: str | None = None) -> list[RecipeRun]:
        """Runs mais recentes primeiro. Filtra por tenant_id opcional."""
        runs = list(self._runs.values())
        if tenant_id:
            runs = [r for r in runs if r.tenant_id == tenant_id]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    async def on_job_finished(
        self,
        job_id: str,
        *,
        success: bool,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Chamado pela fila quando um job termina. Avança o runner."""
        async with self._lock:
            key = self._job_index.pop(job_id, None)
            if key is None:
                return  # desconhecido (já processado ou de outro runner)
            run_id, stage_id, slot = key
            run = self._runs[run_id]
            stage_state = run.stages[stage_id]
            while len(stage_state.outputs) <= slot:
                stage_state.outputs.append({})
            if success:
                stage_state.outputs[slot] = output or {}
            else:
                stage_state.outputs[slot] = {"_error": error}
                stage_state.error = error

        # Se todos os jobs do stage já voltaram, resolve o stage e avança.
        run = self._runs[run_id]
        stage_state = run.stages[stage_id]
        all_done = (
            len(stage_state.outputs) == len(stage_state.job_ids)
            and all(o for o in stage_state.outputs)
        )
        if not all_done:
            return

        if any(o.get("_error") for o in stage_state.outputs):
            stage_state.status = StageStatus.FAILED
            stage_state.finished_at = _now()
            await self._advance(run)
            await self._persist(run)
            return

        stage = run.recipe.stage(stage_id)
        approval = _apply_global_approval_override(stage.approval, run.input)
        if approval.mode != ApprovalMode.NONE:
            stage_state.status = StageStatus.AWAITING_APPROVAL
            await self._persist(run)
            await self._approvals.request(
                run=run,
                stage=stage,
                approval=approval,
                artifacts={
                    "stage_output": stage_state.output,
                    "outputs": stage_state.outputs,
                },
            )
        else:
            stage_state.status = StageStatus.SUCCESS
            stage_state.finished_at = _now()
            await self._advance(run)
            await self._persist(run)

    async def on_approval_decided(
        self,
        run_id: str,
        stage_id: str,
        decision: ApprovalDecision,
    ) -> None:
        run = self._runs[run_id]
        stage_state = run.stages[stage_id]
        # UNCERTAIN conta como aprovado — o pipeline continua. Escalation
        # (`approval.escalation: on_uncertain` na receita) exigiria gate
        # humano; enquanto não implementado, benefício da dúvida.
        if decision in (ApprovalDecision.APPROVED, ApprovalDecision.UNCERTAIN):
            stage_state.status = StageStatus.SUCCESS
            stage_state.finished_at = _now()
            await self._advance(run)
            await self._persist(run)
        elif decision in (ApprovalDecision.REJECTED, ApprovalDecision.EXPIRED):
            stage_state.status = StageStatus.FAILED
            stage_state.error = f"approval: {decision.value}"
            stage_state.finished_at = _now()
            await self._advance(run)
            await self._persist(run)

    # ── internals ─────────────────────────────────────────────────────
    async def _advance(self, run: RecipeRun) -> None:
        """Dispara todo stage que ficou pronto."""
        progressed = True
        while progressed:
            progressed = False
            for stage in run.recipe.stages:
                state = run.stages[stage.id]
                if state.status != StageStatus.PENDING:
                    continue
                if not self._deps_ready(run, stage):
                    continue
                if self._any_dep_failed(run, stage):
                    # Propaga cascada: marcamos com error="dep_failed" pra
                    # stages descendentes também serem pulados em vez de
                    # rodarem com payload vazio.
                    state.status = StageStatus.SKIPPED
                    state.error = "dep_failed"
                    progressed = True
                    continue
                # avalia `when`
                if not evaluate_when(stage.when, run.context()):
                    state.status = StageStatus.SKIPPED
                    progressed = True
                    continue
                await self._launch_stage(run, stage)
                progressed = True

    def _deps_ready(self, run: RecipeRun, stage: RecipeStage) -> bool:
        terminal = {StageStatus.SUCCESS, StageStatus.SKIPPED, StageStatus.FAILED}
        return all(run.stages[d].status in terminal for d in stage.needs)

    def _any_dep_failed(self, run: RecipeRun, stage: RecipeStage) -> bool:
        # Um dep bloqueia descendentes quando FAILED OU quando foi SKIPPED
        # em cascada (por dep_failed). SKIPPED por `when` não bloqueia —
        # é intencional.
        for d in stage.needs:
            dep_state = run.stages[d]
            if dep_state.status == StageStatus.FAILED:
                return True
            if (
                dep_state.status == StageStatus.SKIPPED
                and dep_state.error == "dep_failed"
            ):
                return True
        return False

    async def _launch_stage(self, run: RecipeRun, stage: RecipeStage) -> None:
        state = run.stages[stage.id]
        state.status = StageStatus.RUNNING
        state.started_at = _now()

        # Semântica: trabalho roda primeiro, aprovação depois (em on_job_finished).
        # Caso especial: stage sem trabalho que existe só pra ser gate
        # de aprovação → entra direto em AWAITING_APPROVAL aqui.
        has_work = (
            stage.requires
            or stage.worker
            or stage.fanout_over_capabilities
        )
        if not has_work and stage.approval.mode != ApprovalMode.NONE:
            state.status = StageStatus.AWAITING_APPROVAL
            await self._approvals.request(
                run=run,
                stage=stage,
                approval=stage.approval,
                artifacts={},
            )
            return

        # Determina quantos jobs disparar (1, parallel N, fanout_over list).
        payloads = self._materialize_payloads(run, stage)
        state.outputs = [{} for _ in payloads]

        for idx, payload in enumerate(payloads):
            job_id = str(uuid.uuid4())
            state.job_ids.append(job_id)
            self._job_index[job_id] = (run.run_id, stage.id, idx)
            # Se o payload carrega _required_capability (vem de
            # fanout_over_capabilities), usa ele; senão, o que veio do stage.
            capability = payload.pop(
                "_required_capability", stage.requires
            )
            job = Job(
                job_id=job_id,
                tenant_id=run.tenant_id,
                user_id=run.user_id,
                worker_type=stage.worker,
                required_capability=capability,
                payload=payload,
                origin_channel=run.origin_channel,
                origin_channel_external_id=run.origin_channel_external_id,
                priority=JobPriority.NORMAL,
                parent_job_id=run.run_id,
                recipe_name=run.recipe.name,
                recipe_stage=stage.id,
                fanout_index=idx if len(payloads) > 1 else None,
            )
            await self._dispatcher.dispatch(job)

    def _materialize_payloads(
        self, run: RecipeRun, stage: RecipeStage
    ) -> list[dict[str, Any]]:
        ctx = run.context()

        if stage.fanout_over:
            items = resolve(stage.fanout_over, ctx) or []
            if not isinstance(items, list):
                raise ValueError(
                    f"fanout_over em '{stage.id}' não resolveu pra lista: {type(items).__name__}"
                )
            # Resolve payload_from UMA VEZ por item, com fanout_item no ctx.
            # Permite referenciar campos do item via $.fanout_item.X dentro
            # do payload_from.
            return [
                (resolve(stage.payload_from, {**ctx, "fanout_item": item}) or {})
                | {"_fanout_item": item}
                for item in items
            ]

        base_payload = resolve(stage.payload_from, ctx) or {}

        if stage.fanout_over_capabilities:
            return [
                {**base_payload, "_required_capability": cap}
                for cap in stage.fanout_over_capabilities
            ]

        if stage.parallel > 1:
            return [dict(base_payload) for _ in range(stage.parallel)]

        return [base_payload]
