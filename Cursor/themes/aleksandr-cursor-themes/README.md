# Aleksandr Cursor Themes

Три кастомные темы вместо стандартных:

| Тема | Стиль |
|------|--------|
| **Aleksandr Dark** | угольный фон, синий акцент |
| **Aleksandr Light** | светло-серый, спокойный синий |
| **Aleksandr Night Gold** | чёрный + золото `#d4af37` (как на privacy-странице) |

## Установка в Cursor (Mac)

1. Открой **IDE** (не Agents Window): `Cmd+Shift+P` → **Open IDE**.
2. `Cmd+Shift+P` → **Developer: Install Extension from Location**.
3. Выбери папку:

```text
/Users/user/Projects/themes/aleksandr-cursor-themes
```

(в этом репо путь: `Cursor/themes/aleksandr-cursor-themes`)

4. `Cmd+Shift+P` → **Preferences: Color Theme** → выбери одну из трёх **Aleksandr …**.

## Подкрутить под себя

Правь JSON в `themes/*-color-theme.json`:

- `colors` — UI (sidebar, status bar, selection)
- `tokenColors` — подсветка кода

После правок: перезагрузи окно (`Developer: Reload Window`) или переустанови расширение из той же папки.

Быстрый тюнинг без правки темы — в User Settings:

```json
{
  "workbench.colorCustomizations": {
    "[Aleksandr Night Gold]": {
      "editor.background": "#0a0a0a",
      "statusBar.background": "#111111"
    }
  },
  "editor.tokenColorCustomizations": {
    "[Aleksandr Night Gold]": {
      "comments": "#777777",
      "strings": "#7fd992"
    }
  }
}
```

## Шрифт (по желанию)

```json
{
  "editor.fontFamily": "JetBrains Mono, Menlo, monospace",
  "editor.fontLigatures": true,
  "editor.fontSize": 14
}
```
