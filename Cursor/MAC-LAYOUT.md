# Выровнять папки на Mac под схему

Уже есть `/Users/user/Projects/NOY` и `/Users/user/Projects/Другие` — проверь и досоздай недостающее.

```bash
# Корень
mkdir -p "/Users/user/Projects/NOY/dendriit/anna"
mkdir -p "/Users/user/Projects/NOY/dendriit/легион"
mkdir -p "/Users/user/Projects/NOY/Neyroagents"
mkdir -p "/Users/user/Projects/Другие/bitrix-yurist"
mkdir -p "/Users/user/Projects/Другие/Саприн и партнеры"

# Зеркало правил из git (этот репо) — по желанию:
cd /Users/user/Projects/dier55555-cpu.github.io
git fetch origin
git checkout cursor/noya-global-keys-profiles-fd07
git pull origin cursor/noya-global-keys-profiles-fd07

# Документация схемы лежит в:
#   Cursor/NOY/...
#   Cursor/Другие/...
# Рабочие файлы Анны/Легиона/Битрикса держи в Projects/NOY и Projects/Другие.
```

Проверка:

```bash
ls -la "/Users/user/Projects/NOY"
ls -la "/Users/user/Projects/NOY/dendriit"
ls -la "/Users/user/Projects/Другие"
```

Ожидаемо: `dendriit/{anna,легион}`, `Neyroagents`, `Другие/{bitrix-yurist,Саприн и партнеры}`.  
MCP для Neyroagents — после ключей от Александра.
