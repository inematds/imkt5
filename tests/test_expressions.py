"""Resolver de expressões."""

import pytest

from imkt5.recipes.expressions import evaluate_when, resolve


@pytest.fixture
def ctx():
    return {
        "input": {"brief": "campanha Y", "with_research": True},
        "tenant": {
            "profile": {"visual_style": "minimalist"},
            "publish_bindings": [
                {"dest_channel": "CH1", "kind": "youtube"},
                {"dest_channel": "CH2", "kind": "youtube"},
            ],
        },
        "stages": {
            "copy": {
                "output": {
                    "narrative": "texto...",
                    "prompts": ["p1", "p2", "p3"],
                },
                "status": "success",
            },
            "images": {
                "output": {
                    "outputs": [
                        {"image_url": "a.png"},
                        {"image_url": "b.png"},
                    ]
                }
            },
        },
    }


def test_resolve_scalar(ctx):
    assert resolve("$.input.brief", ctx) == "campanha Y"


def test_resolve_nested(ctx):
    assert resolve("$.tenant.profile.visual_style", ctx) == "minimalist"


def test_resolve_list(ctx):
    assert resolve("$.tenant.publish_bindings", ctx) == ctx["tenant"]["publish_bindings"]


def test_resolve_wildcard_extract(ctx):
    # images.output.outputs[*].image_url → ["a.png", "b.png"]
    result = resolve("$.stages.images.output.outputs[*].image_url", ctx)
    assert result == ["a.png", "b.png"]


def test_resolve_literal(ctx):
    assert resolve("valor fixo", ctx) == "valor fixo"
    assert resolve(42, ctx) == 42


def test_resolve_dict_recursive(ctx):
    d = {"x": "$.input.brief", "y": 10}
    assert resolve(d, ctx) == {"x": "campanha Y", "y": 10}


def test_when_true(ctx):
    assert evaluate_when("$.input.with_research == true", ctx) is True


def test_when_false(ctx):
    assert evaluate_when("$.input.with_research == false", ctx) is False


def test_when_none_is_true(ctx):
    assert evaluate_when(None, ctx) is True
    assert evaluate_when("", ctx) is True


def test_when_comparison(ctx):
    ctx["input"]["n"] = 5
    assert evaluate_when("$.input.n > 3", ctx) is True
    assert evaluate_when("$.input.n < 3", ctx) is False
