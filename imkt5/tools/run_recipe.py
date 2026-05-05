"""Tool `run_recipe` — o LLM do Gateway chama pra disparar uma receita."""

from __future__ import annotations

from typing import Any, Protocol

from imkt5.recipes.loader import Recipe
from imkt5.recipes.runner import RecipeRun, RecipeRunner
from imkt5.tools.base import BaseTool, ToolContext, ToolResult


class RecipeCatalog(Protocol):
    def get(self, name: str) -> Recipe: ...


class TenantContextProvider(Protocol):
    async def snapshot(self, tenant_id: str) -> dict[str, Any]: ...


class RunRecipeTool(BaseTool):
    name = "run_recipe"
    description = (
        "Dispara uma receita (fluxo composto multi-estágio). "
        "Use para campanhas, pipelines de conteúdo, processos que "
        "envolvem múltiplas etapas com aprovação opcional. "
        "Para pedidos simples, use `dispatch_job`."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Nome da receita registrada (ex.: 'campanha-marketing').",
            },
            "input": {
                "type": "object",
                "description": "Input inicial da receita ($.input em expressões).",
            },
        },
        "required": ["name"],
    }

    def __init__(
        self,
        catalog: RecipeCatalog,
        runner: RecipeRunner,
        tenant_ctx_provider: TenantContextProvider,
    ) -> None:
        self._catalog = catalog
        self._runner = runner
        self._tenant_ctx = tenant_ctx_provider

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        name = kwargs["name"]
        input_data = kwargs.get("input", {})

        try:
            recipe = self._catalog.get(name)
        except KeyError:
            return ToolResult(
                ok=False, error=f"receita desconhecida: {name}"
            )

        tenant_ctx = await self._tenant_ctx.snapshot(ctx.tenant_id)

        run: RecipeRun = await self._runner.start(
            recipe=recipe,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            input=input_data,
            tenant_ctx=tenant_ctx,
            origin_channel=ctx.origin_channel,
            origin_channel_external_id=ctx.origin_channel_external_id,
        )
        return ToolResult(ok=True, output={"run_id": run.run_id})


class StaticRecipeCatalog:
    """Catálogo simples backed por dict — útil em testes e single-node."""

    def __init__(self, recipes: dict[str, Recipe], source_dir: str | None = None) -> None:
        self._recipes = dict(recipes)
        self._source_dir = source_dir

    def register(self, recipe: Recipe) -> None:
        self._recipes[recipe.name] = recipe

    def get(self, name: str) -> Recipe:
        return self._recipes[name]

    def all(self) -> list[Recipe]:
        return list(self._recipes.values())

    def reload(self) -> None:
        """Re-lê `source_dir` — usado pelo admin UI ao editar receitas."""
        if not self._source_dir:
            return
        from imkt5.recipes.loader import load_recipes_from_dir
        self._recipes = dict(load_recipes_from_dir(self._source_dir))
