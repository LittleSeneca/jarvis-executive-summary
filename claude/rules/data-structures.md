---
paths:
  - "**/*.py"
---

# Data Structures

## Choosing a Structure

Prefer the best option for the use case. In Jarvis, the most common shape is a plugin-defined payload (an opaque JSON-serializable blob) plus a small number of internal coordination types on the core.

- **Pydantic `BaseModel`** — Use when validation matters: loading and validating `.env` config, enforcing the shape of an LLM's structured output, or defining a plugin's own internal request/response types against an external API. Prefer Pydantic v2 (`from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator`).
- **`dataclass`** — The right choice for internal data containers with minimal ceremony: `FetchResult`, `InferenceJob`, `RunReport`. Use `@dataclass(slots=True)` when the type is hot on the run path.
- **`TypedDict`** — Use for JSON payload shapes you want the type checker to understand, when you don't want the runtime overhead of instantiating a model for every item. Good for plugin payload schemas documented in their README.
- **`SimpleNamespace`** — Ad-hoc attribute bags. Use for one-off config objects or quick test doubles. Not a substitute for a real type.

## Pydantic v2 Reference

New code uses Pydantic v2. Core imports and patterns:

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Example(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    count: int = 0

    @field_validator("name", mode="before")
    def normalize_name(cls, v: str) -> str:
        return v.strip() if v else ""

    @model_validator(mode="before")
    def set_defaults(cls, values: dict) -> dict:
        if "count" not in values:
            values["count"] = 0
        return values
```

Set `extra="forbid"` on any model that parses external or user-supplied data — unknown fields should be a loud failure, not silently dropped.

## Payload Shapes Are Plugin-Defined

The spec (see `docs/specs/initial-spec.md`, §5) is deliberate: the core never inspects a plugin's `raw_payload`. Plugins may return a Pydantic model, a plain dict, a list, or a TypedDict — whatever best fits the source. Document the payload shape in the plugin's `README.md` rather than encoding it as a shared schema in the core.
