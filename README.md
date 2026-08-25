# dier55555-cpu.github.io

Публичная страница: корневой `index.html`.

Все проекты агента — в одной папке **`Cursor/`**:

```
Cursor/
  noya/                 # платформа Ноя
    _shared/            # методология + cabinets-and-keys.md
    projects/anna/      # кабинет ДендрИИт / Анна
    projects/<slug>/    # другой кабинет Нои
  другие/
    юристы/             # вне Нои
```

Несколько кабинетов Нои подключаются через **глобальные Secrets Cursor** (`NOYA_KEY_<SLUG>`) и project-level MCP — не через один ключ в `~/.cursor/mcp.json`.

Правила: `Cursor/AGENTS.md`, `.cursor/rules/workspace-layout.mdc`, `Cursor/noya/_shared/cabinets-and-keys.md`.
