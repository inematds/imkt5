"""Resolver de expressões em receitas.

Sintaxe suportada (sub-conjunto de JSONPath, suficiente pras receitas):

    $.input.brief
    $.stages.copy.output
    $.stages.copy.output.prompts
    $.stages.images.outputs[*].image_url     → lista
    $.tenant.publish_bindings                → lista
    $.tenant.profile.visual_style
    $.fanout_item                            → item atual quando fanout
    $.fanout_item.dest_channel

E expressões booleanas simples em `when`:
    $.input.with_research == true
    $.input.stage_count > 3

Zero dependência externa — deliberadamente minimalista; se precisar mais
depois, troca por jsonpath-ng.
"""

from __future__ import annotations

import re
from typing import Any


class ExpressionError(ValueError):
    pass


def _resolve_path(root: dict[str, Any], expr: str) -> Any:
    """Resolve `$.a.b[*].c` contra `root`. Retorna o valor (pode ser lista)."""
    if not expr.startswith("$."):
        raise ExpressionError(f"expressão deve começar com '$.': {expr!r}")
    tokens = _tokenize(expr[2:])
    cur: Any = root
    for tok in tokens:
        if tok == "[*]":
            if not isinstance(cur, list):
                raise ExpressionError(
                    f"[*] requer lista, obtido {type(cur).__name__} em {expr!r}"
                )
            # Continua aplicando o resto em cada item; acumula em lista.
            rest = tokens[tokens.index(tok) + 1:]
            return [_resolve_path_from(item, rest) for item in cur]
        if isinstance(cur, dict):
            if tok not in cur:
                return None
            cur = cur[tok]
        elif isinstance(cur, list):
            try:
                idx = int(tok)
            except ValueError as exc:
                raise ExpressionError(
                    f"índice inválido {tok!r} em {expr!r}"
                ) from exc
            cur = cur[idx]
        else:
            return None
    return cur


def _resolve_path_from(root: Any, tokens: list[str]) -> Any:
    cur: Any = root
    for tok in tokens:
        if isinstance(cur, dict) and tok in cur:
            cur = cur[tok]
        else:
            return None
    return cur


_TOKEN_RE = re.compile(r"\[\*\]|\.([a-zA-Z_][a-zA-Z0-9_]*)|\[(\d+)\]")


def _tokenize(body: str) -> list[str]:
    """Quebra `a.b[*].c[0]` em ['a', 'b', '[*]', 'c', '0']."""
    tokens: list[str] = []
    if body.startswith("[*]"):
        tokens.append("[*]")
        body = body[3:]
    elif not body.startswith("."):
        # primeiro segmento sem ponto inicial
        m = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)", body)
        if m:
            tokens.append(m.group(1))
            body = body[len(m.group(1)):]
    for match in _TOKEN_RE.finditer("." + body if body and not body.startswith(".") else body):
        if match.group(0) == "[*]":
            tokens.append("[*]")
        elif match.group(1):
            tokens.append(match.group(1))
        elif match.group(2):
            tokens.append(match.group(2))
    return tokens


def resolve(expr: Any, context: dict[str, Any]) -> Any:
    """Resolve um valor. Se `expr` é string começando com '$.', resolve
    contra o contexto; se é dict/list, resolve recursivamente; caso
    contrário, devolve literal."""
    if isinstance(expr, str) and expr.startswith("$."):
        return _resolve_path(context, expr)
    if isinstance(expr, dict):
        return {k: resolve(v, context) for k, v in expr.items()}
    if isinstance(expr, list):
        return [resolve(v, context) for v in expr]
    return expr


# ── expressões booleanas em `when` ────────────────────────────────────
_BOOL_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">":  lambda a, b: a > b,
    "<":  lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}


def evaluate_when(expr: str | None, context: dict[str, Any]) -> bool:
    """True se a condição `when` é verdadeira. None ou string vazia = True."""
    if not expr:
        return True
    # muito simples: LHS OP RHS, todos literais ou $-path
    for op_str in sorted(_BOOL_OPS, key=len, reverse=True):
        if f" {op_str} " in expr:
            lhs_raw, rhs_raw = expr.split(f" {op_str} ", 1)
            lhs = _coerce(resolve(lhs_raw.strip(), context), lhs_raw.strip())
            rhs = _coerce(resolve(rhs_raw.strip(), context), rhs_raw.strip())
            return _BOOL_OPS[op_str](lhs, rhs)
    raise ExpressionError(f"when sem operador reconhecido: {expr!r}")


def _coerce(value: Any, raw: str) -> Any:
    """Se `resolve` devolveu literal (não-path), coerce tipos simples."""
    if raw.startswith("$."):
        return value
    s = raw.strip()
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "null" or s == "None":
        return None
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s
