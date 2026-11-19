import pytest

from mcp_login_proxy.template import compute_vars, placeholders, render, render_json


def test_render_fills_placeholders():
    assert render("Basic {user}:{token}", {"user": "a", "token": "t"}) == "Basic a:t"


def test_render_missing_name_raises():
    with pytest.raises(KeyError):
        render("{nope}", {})


def test_literal_braces():
    assert render("{{x}} {y}", {"y": "1"}) == "{x} 1"
    assert placeholders("{{x}} {y}") == {"y"}


def test_render_refuses_format_specs_and_attributes():
    with pytest.raises(ValueError):
        render("{token:>10}", {"token": "t"})
    with pytest.raises(ValueError):
        render("{token.__class__}", {"token": "t"})


def test_placeholders_recurse():
    assert placeholders({"a": "{x}", "b": ["{y}", {"c": "{z}"}], "d": 1}) == {"x", "y", "z"}


def test_render_json_drops_empty_values():
    body = {"password": "{password}", "totpToken": "{totp}"}
    assert render_json(body, {"password": "pw", "totp": ""}) == {"password": "pw"}


def test_base64_var():
    out = compute_vars({"basic": {"base64": "{user}:{token}"}}, {"user": "alice", "token": "t0k"})
    assert out["basic"] == "YWxpY2U6dDBr"


def test_unknown_var_function_raises():
    with pytest.raises(KeyError):
        compute_vars({"x": {"rot13": "{user}"}}, {"user": "a"})
