"""Loader YAML → Recipe.

Formato de receita:

```yaml
name: campanha-marketing
version: 2
stages:
  - id: research
    requires: research.market
    when: $.input.with_research == true
    payload_from: {brief: $.input.brief}
    approval: {mode: none}
  - id: copy
    requires: copy.narrative
    needs: [research]
    approval: {mode: user, timeout: 1800}
  - id: images
    requires: image.generation
    needs: [copy]
    parallel: 6
    payload_from: {prompts: $.stages.copy.output.prompts}
  - id: publish
    fanout_over: $.tenant.publish_bindings
    requires: platform.publish
    needs: [images]
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from imkt5.types.approvals import Approval, ApprovalMode, EscalationPolicy


@dataclass(frozen=True, slots=True)
class RecipeStage:
    id: str
    # Um dos dois: `worker` (endereça um worker_type específico) OU `requires`
    # (endereça via capability). `requires` é o caminho idiomático.
    requires: str | None = None
    worker: str | None = None

    needs: tuple[str, ...] = ()
    when: str | None = None        # expressão booleana (ex.: "$.input.with_research == true")
    payload_from: dict[str, Any] = field(default_factory=dict)

    # Concorrência
    parallel: int = 1              # roda N cópias (payload idêntico)
    fanout_over: str | None = None # expressão que resolve pra lista; um job por item
    fanout_over_capabilities: tuple[str, ...] = ()  # alternativa: um job por capability

    approval: Approval = field(default_factory=Approval)

    def __post_init__(self) -> None:
        if (
            not self.requires
            and not self.worker
            and not self.fanout_over_capabilities
        ):
            raise ValueError(
                f"stage '{self.id}' precisa de 'requires', 'worker' "
                f"ou 'fanout_over_capabilities'"
            )


@dataclass(frozen=True, slots=True)
class Recipe:
    name: str
    version: int
    stages: tuple[RecipeStage, ...]

    def stage(self, stage_id: str) -> RecipeStage:
        for s in self.stages:
            if s.id == stage_id:
                return s
        raise KeyError(f"stage desconhecido: {stage_id}")


def _parse_approval(d: dict[str, Any] | None) -> Approval:
    if not d:
        return Approval()
    # Item 7 — aliases amigáveis nas recipes:
    #   human → user (pergunta no canal de origem)
    #   auto → auto_reviewer (LLM genérico)
    #   agent → auto_reviewer com reviewer_worker específico (mais contexto)
    raw_mode = d.get("mode", "none")
    alias_map = {
        "human": "user",
        "auto": "auto_reviewer",
        "agent": "auto_reviewer",
    }
    mode_str = alias_map.get(raw_mode, raw_mode)
    mode = ApprovalMode(mode_str)
    esc = d.get("escalation", "on_uncertain")
    # Se era 'agent', força reviewer_worker específico do stage (ou default)
    reviewer_worker = d.get("reviewer_worker")
    if raw_mode == "agent" and not reviewer_worker:
        reviewer_worker = d.get("agent_worker", "auto-reviewer")
    reviewer_worker = reviewer_worker or "auto-reviewer"
    return Approval(
        mode=mode,
        timeout_seconds=int(d.get("timeout", 1800)),
        reviewer_role=d.get("reviewer_role"),
        reviewer_worker=reviewer_worker,
        criteria=tuple(d.get("criteria", [])),
        escalation=EscalationPolicy(esc),
    )


def _parse_stage(d: dict[str, Any]) -> RecipeStage:
    return RecipeStage(
        id=d["id"],
        requires=d.get("requires"),
        worker=d.get("worker"),
        needs=tuple(d.get("needs", [])),
        when=d.get("when"),
        payload_from=d.get("payload_from", {}) or {},
        parallel=int(d.get("parallel", 1)),
        fanout_over=d.get("fanout_over"),
        fanout_over_capabilities=tuple(d.get("fanout_over_capabilities", [])),
        approval=_parse_approval(d.get("approval")),
    )


def load_recipe(path: str | Path) -> Recipe:
    data = yaml.safe_load(Path(path).read_text())
    return Recipe(
        name=data["name"],
        version=int(data.get("version", 1)),
        stages=tuple(_parse_stage(s) for s in data["stages"]),
    )


def load_recipes_from_dir(dir_path: str | Path) -> dict[str, Recipe]:
    out: dict[str, Recipe] = {}
    for p in Path(dir_path).glob("*.yaml"):
        r = load_recipe(p)
        out[r.name] = r
    return out
