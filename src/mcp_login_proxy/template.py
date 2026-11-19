"""`{name}` placeholders in the config file's requests and headers, filled per login or per request.

`{{` and `}}` are literal braces. In a JSON body, a string that renders empty drops its key, so an optional
form field left blank is not sent at all.
"""

import base64
import string
from collections.abc import Mapping
from typing import Any

_FORMATTER = string.Formatter()

# The functions a `vars:` entry may use: {"name": {"<function>": "<template>"}}.
VAR_FUNCTIONS = {"base64": lambda s: base64.b64encode(s.encode()).decode()}


def placeholders(value: Any) -> set[str]:
    """Every placeholder name in a string, or in the strings of a mapping or list, recursively."""
    if isinstance(value, str):
        return {name for _, name, _, _ in _FORMATTER.parse(value) if name is not None}
    if isinstance(value, Mapping):
        return set().union(*(placeholders(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(placeholders(v) for v in value)) if value else set()
    return set()


def render(value: str, variables: Mapping[str, str]) -> str:
    """Fill the placeholders. A missing name raises KeyError; no format specs or attribute access."""
    out = []
    for literal, name, spec, conversion in _FORMATTER.parse(value):
        out.append(literal)
        if name is None:
            continue
        if spec or conversion or not name.isidentifier():
            raise ValueError(f"only plain {{name}} placeholders are allowed, got {{{name}}}")
        out.append(str(variables[name]))
    return "".join(out)


def render_json(value: Any, variables: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return render(value, variables)
    if isinstance(value, Mapping):
        rendered = {k: render_json(v, variables) for k, v in value.items()}
        return {k: v for k, v in rendered.items() if v != ""}
    if isinstance(value, list):
        return [render_json(v, variables) for v in value]
    return value


def compute_vars(defs: Mapping[str, Mapping[str, str]], variables: Mapping[str, str]) -> dict[str, str]:
    """The derived variables, e.g. {"basic": {"base64": "{user}:{token}"}}, added to `variables`."""
    out = dict(variables)
    for name, definition in defs.items():
        ((function, template),) = definition.items()
        out[name] = VAR_FUNCTIONS[function](render(template, out))
    return out
