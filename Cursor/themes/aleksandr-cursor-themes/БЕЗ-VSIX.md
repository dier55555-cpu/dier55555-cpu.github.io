# Бежевый вид БЕЗ VSIX (то, что реально работает на Mac)

Меню **Settings → Appearance → Theme** показывает только:
System / Cursor Light / Cursor Dark / …
Туда **никогда** не попадут кастомные темы. Ты смотрел не тот список.

## Сделай так (2 минуты)

1. На Mac в Cursor: `Cmd+Shift+P`
2. Набери: **Preferences: Open User Settings (JSON)**
3. Вставь содержимое файла `PASTE-INTO-CURSOR-SETTINGS.json`  
   (если в файле уже есть `{ ... }` — скопируй ключи внутрь, через запятую)
4. Сохрани (`Cmd+S`)

Сразу станет бежево / светло-коричнево, с тонкими рамками.

Скачать готовый JSON:
https://raw.githubusercontent.com/dier55555-cpu/dier55555-cpu.github.io/cursor/aleksandr-themes-6562/Cursor/themes/aleksandr-cursor-themes/PASTE-INTO-CURSOR-SETTINGS.json

Или в Appearance сначала выбери **Cursor Light**, потом вставь JSON — так спокойнее для глаз.
