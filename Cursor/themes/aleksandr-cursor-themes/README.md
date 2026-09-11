# Aleksandr Cursor Themes

Три темы в **стандартном** списке Cursor: **Aleksandr Dark**, **Aleksandr Light**, **Aleksandr Night Gold**.

Они появятся в `Preferences: Color Theme` только после установки как расширения (один раз).

---

## Способ 1 — скрипт (Mac, из зеркала Projects)

В терминале:

```bash
cd /Users/user/Projects/themes/aleksandr-cursor-themes
chmod +x install.sh
./install.sh
```

Потом в Cursor:

1. `Cmd+Shift+P` → **Developer: Reload Window**
2. `Cmd+Shift+P` → **Preferences: Color Theme**
3. Выбери **Aleksandr Dark** / **Light** / **Night Gold**

Скрипт копирует расширение в `~/.cursor/extensions/aleksandr.aleksandr-cursor-themes-1.0.0/`.

---

## Способ 2 — из Cursor (без терминала)

1. `Cmd+Shift+P` → **Open IDE** (если ты в Agents Window)
2. `Cmd+Shift+P` → **Developer: Install Extension from Location**
3. Укажи папку:

```text
/Users/user/Projects/themes/aleksandr-cursor-themes
```

4. `Cmd+Shift+P` → **Preferences: Color Theme** → выбери тему

---

## Способ 3 — VSIX

Если есть файл `aleksandr-cursor-themes-1.0.0.vsix` рядом:

1. `Cmd+Shift+P` → **Extensions: Install from VSIX…**
2. Выбери `.vsix`
3. Reload → **Preferences: Color Theme**

---

## Закрепить тему в настройках программы

`Cmd+,` → открой **User** settings JSON (`Open User Settings (JSON)`) и добавь:

```json
{
  "workbench.colorTheme": "Aleksandr Night Gold",
  "workbench.preferredDarkColorTheme": "Aleksandr Night Gold",
  "workbench.preferredLightColorTheme": "Aleksandr Light"
}
```

Готовый сниппет: `cursor-user-settings.snippet.json`.

Путь к User settings на Mac:

```text
~/Library/Application Support/Cursor/User/settings.json
```

---

## Подкрутить цвета

Правь `themes/*-color-theme.json`, затем снова `./install.sh` и **Reload Window**.

Или без переустановки — в User settings:

```json
{
  "workbench.colorCustomizations": {
    "[Aleksandr Night Gold]": {
      "editor.background": "#0a0a0a"
    }
  }
}
```
