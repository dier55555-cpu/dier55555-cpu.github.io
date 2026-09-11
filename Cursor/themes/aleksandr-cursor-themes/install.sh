#!/usr/bin/env bash
# Ставит темы в Cursor так, чтобы они появились в Preferences: Color Theme.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
NAME="aleksandr.aleksandr-cursor-themes-1.0.0"

# Cursor (приоритет) и VS Code на всякий случай
CANDIDATES=(
  "${HOME}/.cursor/extensions"
  "${HOME}/.vscode/extensions"
)

installed=0
for EXT_DIR in "${CANDIDATES[@]}"; do
  # Cursor всегда ставим; VS Code — только если каталог уже есть
  if [[ "$EXT_DIR" == *".cursor"* ]] || [[ -d "$EXT_DIR" ]]; then
    mkdir -p "$EXT_DIR"
    DEST="${EXT_DIR}/${NAME}"
    rm -rf "$DEST"
    mkdir -p "$DEST"
    cp -R "${SRC}/package.json" "${SRC}/themes" "$DEST/"
    [[ -f "${SRC}/README.md" ]] && cp "${SRC}/README.md" "$DEST/"
    echo "OK → ${DEST}"
    installed=1
  fi
done

# Если есть CLI Cursor — тоже через него
if command -v cursor >/dev/null 2>&1; then
  VSIX="${SRC}/aleksandr-cursor-themes-1.0.0.vsix"
  if [[ -f "$VSIX" ]]; then
    cursor --install-extension "$VSIX" && echo "OK → cursor --install-extension"
  fi
fi

if [[ "$installed" -eq 0 ]]; then
  echo "Не найден каталог расширений. Создай ~/.cursor/extensions и запусти снова." >&2
  exit 1
fi

echo
echo "Дальше в Cursor:"
echo "  1. Cmd+Shift+P → Developer: Reload Window"
echo "  2. Cmd+Shift+P → Preferences: Color Theme"
echo "  3. Выбери: Aleksandr Dark / Aleksandr Light / Aleksandr Night Gold"
echo
echo "Чтобы сразу включить тему, добавь в User settings:"
echo "  \"workbench.colorTheme\": \"Aleksandr Night Gold\""
