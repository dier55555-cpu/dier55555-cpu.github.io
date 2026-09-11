#!/usr/bin/env bash
# Установка Aleksandr Beige в Cursor на Mac.
# Запуск в Terminal:
#   bash "/Users/user/Projects/themes/aleksandr-cursor-themes/install-on-mac.sh"
# или из клона репо:
#   bash Cursor/themes/aleksandr-cursor-themes/install-on-mac.sh
set -euo pipefail

EXT_ID="aleksandr.aleksandr-cursor-themes-1.1.0"
THEME_NAME="Aleksandr Beige"
CURSOR_EXT="${HOME}/.cursor/extensions/${EXT_ID}"
CURSOR_USER="${HOME}/Library/Application Support/Cursor/User"
SETTINGS="${CURSOR_USER}/settings.json"

echo "==> Ищу aleksandr-cursor-themes-*.vsix …"

VSIX=""
SEARCH_DIRS=(
  "${HOME}/Library/Application Support/Cursor"
  "${HOME}/Library/Application Support/Cursor/User"
  "${HOME}/Library/Application Support/Cursor/User/settings"
  "${HOME}/Downloads"
  "${HOME}/Desktop"
  "${HOME}/Documents"
  "/Users/user/Projects"
  "/Users/user/Desktop"
  "/Users/user/Downloads"
)

# Папки с русским названием «Настройки…»
while IFS= read -r d; do
  SEARCH_DIRS+=("$d")
done < <(find "${HOME}" -maxdepth 3 -type d \( -iname '*настрой*cursor*' -o -iname '*настрой*курсор*' -o -iname '*cursor*настрой*' -o -iname '*курсор*настрой*' \) 2>/dev/null | head -20)

for dir in "${SEARCH_DIRS[@]}"; do
  [[ -d "$dir" ]] || continue
  found="$(find "$dir" -maxdepth 3 -type f -name 'aleksandr-cursor-themes-*.vsix' 2>/dev/null | sort | tail -1 || true)"
  if [[ -n "${found}" ]]; then
    VSIX="$found"
    break
  fi
done

# Фоллбек: рядом со скриптом / корень репо
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
for cand in \
  "${SCRIPT_DIR}/aleksandr-cursor-themes-1.1.0.vsix" \
  "${SCRIPT_DIR}/../../../../aleksandr-cursor-themes-1.1.0.vsix" \
  "${PWD}/aleksandr-cursor-themes-1.1.0.vsix"
do
  if [[ -z "$VSIX" && -f "$cand" ]]; then
    VSIX="$cand"
  fi
done

if [[ -z "$VSIX" || ! -f "$VSIX" ]]; then
  echo "VSIX не найден."
  echo "Скачай и положи в Downloads или в папку настроек Cursor:"
  echo "  https://github.com/dier55555-cpu/dier55555-cpu.github.io/raw/cursor/aleksandr-themes-6562/Cursor/themes/aleksandr-cursor-themes/aleksandr-cursor-themes-1.1.0.vsix"
  exit 1
fi

echo "OK, файл: $VSIX"

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

echo "==> Распаковываю в расширения Cursor…"
mkdir -p "${HOME}/.cursor/extensions"
rm -rf "$CURSOR_EXT"
unzip -q "$VSIX" -d "$TMP"
# структура VSIX: extension/package.json + themes/
if [[ -d "${TMP}/extension" ]]; then
  mkdir -p "$CURSOR_EXT"
  cp -R "${TMP}/extension/." "$CURSOR_EXT/"
else
  echo "Неожиданный формат VSIX" >&2
  exit 1
fi

echo "OK → $CURSOR_EXT"

echo "==> Включаю тему в User settings…"
mkdir -p "$CURSOR_USER"
python3 - <<PY
import json
from pathlib import Path
p = Path("""${SETTINGS}""")
data = {}
if p.exists():
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception:
        data = {}
data["workbench.colorTheme"] = """${THEME_NAME}"""
data["workbench.preferredLightColorTheme"] = """${THEME_NAME}"""
data.setdefault("workbench.preferredDarkColorTheme", "Aleksandr Night Gold")
p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("OK →", p)
print("workbench.colorTheme =", data["workbench.colorTheme"])
PY

# CLI, если есть
if command -v cursor >/dev/null 2>&1; then
  echo "==> cursor --install-extension …"
  cursor --install-extension "$VSIX" || true
fi

echo
echo "Готово. Теперь в Cursor:"
echo "  1) Cmd+Shift+P → Developer: Reload Window"
echo "  2) Тема уже должна быть: ${THEME_NAME}"
echo "  3) Или Preferences: Color Theme → ${THEME_NAME}"
