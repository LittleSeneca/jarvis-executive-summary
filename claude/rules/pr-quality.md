# PR Quality

Before submitting code, verify these patterns match expectations.

## Placement

- Core-vs-plugin placement matters. If a module is useful to more than one plugin, it belongs in `jarvis/core/` (possibly under `jarvis/core/auth/` or `jarvis/core/redaction.py`). If it is specific to one data source, it belongs inside that plugin's folder under `plugins/<name>/`.
- Plugin folders are self-contained. A plugin should not reach into another plugin's folder. Cross-plugin sharing means the shared piece graduates to `jarvis/core/`.
- Never place Jarvis core code under `plugins/`, and never place plugin-specific code under `jarvis/core/`.

## Dependencies

- Keep `pyproject.toml` and any generated lockfile (`uv.lock`, `poetry.lock`, etc.) in sync. Don't hand-edit one without updating the other.
- Don't pin loose dependencies just to stop a build from breaking — investigate the actual break.

## Imports

- Declared dependencies get top-level imports. No `try/except ImportError` guards for packages in `pyproject.toml`.
- No repeated lazy imports of the same module across multiple functions — move to top-level unless there is a proven circular dependency.

## Style

- PEP 257 docstrings: imperative first line, no `Args:` / `Returns:` / `Raises:` blocks — let annotations speak. Multi-line docstrings are fine when additional detail is needed.
- Target Python 3.12 natively. `from __future__ import annotations` is acceptable when needed for forward references but should not be used as a blanket default.
- Module-level functions should not use leading underscores for "privacy" — use `__all__` to define the public API. Functions scoped inside a class or another function may be private.
- Prefer `x = a or b or default` over multi-line ternaries.

## Files to Never Commit

- `.env` files with real credentials (commit `.env.example` with placeholders instead)
- IDE-specific local settings
- Recorded API-response fixtures that contain real customer data — sanitize before committing

## Scope and Intent

- **Stay in scope.** Do what the ticket or prompt asks. If you notice adjacent issues while working — a typo, a stale import, a slightly off comment — flag them in the PR description rather than bundling the fix. Reviewers should not have to untangle two intents in one diff.
- **Chesterton's Fence.** Before removing or radically changing a line whose purpose isn't obvious, investigate why it exists. Check the spec, the plugin README, and git blame. If you still can't tell, ask — don't delete and hope.
- **Small improvements are welcome; crusades are not.** When you touch a file, a small ergonomic improvement inside that file (a clearer name, a deleted dead branch, a better type hint) is fine and often appreciated. A sweeping rename across twelve files in a bug-fix PR is not.
