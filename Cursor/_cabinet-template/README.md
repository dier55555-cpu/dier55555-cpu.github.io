# Шаблон кабинета Нои

Скопировать в `/Users/user/Projects/<cabinet-slug>/` (в репо — `Cursor/<cabinet-slug>/`).

```text
<cabinet-slug>/
  README.md
  .cursor/
    mcp.json.example → mcp.json   # ${env:NOYA_KEY_<CABINET>}
    rules/noya-cabinets.mdc       # id кабинета + список проектов
  <project-a>/
  <project-b>/
```

1. Секрет `NOYA_KEY_<CABINET>` в Cursor Secrets.
2. Заполнить `noya-cabinets.mdc` и README.
3. Создать папки проектов (из `project-template/` при необходимости).
4. `whoami` перед работой.

См. `Cursor/_shared/cabinets-and-keys.md`.
