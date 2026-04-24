# Conventional Commits

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification for all commit messages.

## Format

```
<type>(<optional scope>): <imperative description>
```

## Types

| Type | When to use |
|------|-------------|
| `feat` | A new feature or capability |
| `fix` | A bug fix |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `chore` | Maintenance (merge, config, gitignore, etc.) |
| `build` | Dependency bumps and build system changes |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `ci` | CI/CD pipeline changes |
| `perf` | Performance improvement |

## Rules

- Subject line must be lowercase, imperative, and not end with a period.
- Use scope when the change is confined to a specific area. For Jarvis, the natural scope is usually a plugin name: `feat(github): add stale-PR detection`, `fix(stocks): handle yfinance timeout`.
- One logical change per commit. Do not bundle unrelated changes.
- `feat` means a wholly new capability. `fix` means a bug fix. `refactor` means restructuring without behavior change. Do not conflate these.
