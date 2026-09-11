# Русский интерфейс Cursor

Плагин + установщик: русский язык панелей, меню и настроек (через официальный Russian Language Pack).

## Важно

- Переводится UI, унаследованный от VS Code (меню, Explorer, Terminal, многие Settings).
- Экраны самого Cursor (Agent, Chat, часть Appearance) могут остаться на английском — так сейчас у продукта.
- Этот Cloud Agent **не может** нажать установку на твоём Mac из облачного чата. Нужна одна команда в Terminal на Mac (ниже) или новый агент на машине BOOMERANG.

## Установка на Mac (одна команда)

В **Terminal.app** на Mac:

```bash
curl -fsSL -o /tmp/install-cursor-ru.sh \
  "https://raw.githubusercontent.com/dier55555-cpu/dier55555-cpu.github.io/cursor/aleksandr-themes-6562/Cursor/themes/aleksandr-cursor-ru/install-on-mac.sh"
bash /tmp/install-cursor-ru.sh
```

Потом: **Cmd+Q** (полный выход) → открыть Cursor снова.

## Что делает установщик

1. Ставит `MS-CEINTL.vscode-language-pack-ru`
2. Ставит helper `aleksandr-cursor-ru`
3. Пишет `~/Library/Application Support/Cursor/User/locale.json` → `{"locale":"ru"}`

## Вручную

1. Extensions → найти **Russian Language Pack for Visual Studio Code** → Install  
2. `Cmd+Shift+P` → **Configure Display Language** → **ru**  
3. Или создай `locale.json` как выше и перезапусти Cursor.
