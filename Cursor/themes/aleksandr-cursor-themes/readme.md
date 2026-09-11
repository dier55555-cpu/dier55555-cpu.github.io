# Aleksandr Cursor Themes

| Тема | Стиль |
|------|--------|
| **Aleksandr Beige** | бежевый + светло-коричневый, тонкие рамки панелей и кнопок |
| **Aleksandr Dark** | угольный фон, синий акцент |
| **Aleksandr Light** | светло-серый, спокойный синий |
| **Aleksandr Night Gold** | чёрный + золото `#d4af37` |

Путь на Mac: `/Users/user/Projects/themes/aleksandr-cursor-themes`  
В репо: `Cursor/themes/aleksandr-cursor-themes/`

---

## Установка (чтобы темы были в обычном списке)

### Скрипт (предпочтительно)

```bash
cd /Users/user/Projects/themes/aleksandr-cursor-themes
chmod +x install.sh pack.sh && ./install.sh
```

Потом в Cursor:

1. `Cmd+Shift+P` → **Developer: Reload Window**
2. `Cmd+Shift+P` → **Preferences: Color Theme** → **Aleksandr Beige**

### VSIX вручную

1. `Cmd+Shift+P` → **Open IDE** (если в Agents Window)
2. `Cmd+Shift+P` → **Extensions: Install from VSIX…**
3. Файл:

```text
/Users/user/Projects/themes/aleksandr-cursor-themes/aleksandr-cursor-themes-1.1.0.vsix
```

4. **Developer: Reload Window**
5. **Preferences: Color Theme** → **Aleksandr Beige**

Скачать готовый VSIX с GitHub Pages:

```text
https://dier55555-cpu.github.io/Cursor/themes/aleksandr-cursor-themes/aleksandr-cursor-themes-1.1.0.vsix
```

### Пересобрать VSIX после правок тем

```bash
./pack.sh
```

---

## Закрепить в настройках

`Preferences: Open User Settings (JSON)`:

```json
{
  "workbench.colorTheme": "Aleksandr Beige",
  "workbench.preferredDarkColorTheme": "Aleksandr Night Gold",
  "workbench.preferredLightColorTheme": "Aleksandr Beige"
}
```

---

## Aleksandr Beige — что внутри

- фон редактора `#f3eadc`, панели `#ebe0ce` / `#e2d3bb`
- рамки `#c4a882`, акцент `#a67c52`
- тонкие `border` у sidebar, panel, tabs, input, button, menu, settings, notifications
