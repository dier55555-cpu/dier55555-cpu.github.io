# Aleksandr Cursor Themes

| Тема | Стиль |
|------|--------|
| **Aleksandr Beige** | бежевый + светло-коричневый, тонкие рамки панелей и кнопок |
| **Aleksandr Dark** | угольный фон, синий акцент |
| **Aleksandr Light** | светло-серый, спокойный синий |
| **Aleksandr Night Gold** | чёрный + золото `#d4af37` |

---

## Установка (чтобы темы были в обычном списке)

Путь `/Users/user/Projects/themes/...` **не существует** — файл в этом репозитории / PR.

### Скачать VSIX (проще всего)

1. Скачай:
   https://github.com/dier55555-cpu/dier55555-cpu.github.io/raw/cursor/aleksandr-themes-6562/Cursor/themes/aleksandr-cursor-themes/aleksandr-cursor-themes-1.1.0.vsix
2. `Cmd+Shift+P` → **Extensions: Install from VSIX…** → выбери скачанный файл
3. **Developer: Reload Window**
4. **Preferences: Color Theme** → **Aleksandr Beige**

Подробно: [КАК-ВЫБРАТЬ.md](./КАК-ВЫБРАТЬ.md)

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
