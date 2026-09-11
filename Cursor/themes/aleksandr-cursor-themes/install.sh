#!/usr/bin/env bash
# Собирает VSIX и ставит в Cursor / VS Code (Extensions: Install from VSIX).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

chmod +x ./pack.sh
./pack.sh

VERSION="$(python3 -c "import json; print(json.load(open('package.json'))['version'])")"
NAME="$(python3 -c "import json; print(json.load(open('package.json'))['name'])")"
VSIX="${ROOT}/${NAME}-${VERSION}.vsix"

install_cli() {
  local bin="$1"
  if command -v "$bin" >/dev/null 2>&1; then
    "$bin" --install-extension "$VSIX" --force
    echo "Installed via: $bin"
    return 0
  fi
  return 1
}

if install_cli cursor || install_cli code; then
  echo
  echo "Дальше в Cursor:"
  echo "  Cmd+Shift+P → Developer: Reload Window"
  echo "  Cmd+Shift+P → Preferences: Color Theme → Aleksandr Beige"
  exit 0
fi

echo "CLI cursor/code не найден. Установи вручную:"
echo "  1. Cmd+Shift+P → Extensions: Install from VSIX…"
echo "  2. Выбери файл:"
echo "     $VSIX"
echo "  3. Cmd+Shift+P → Developer: Reload Window"
echo "  4. Preferences: Color Theme → Aleksandr Beige"
exit 0
