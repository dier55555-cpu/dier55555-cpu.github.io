#!/usr/bin/env bash
# Установка русского интерфейса Cursor на Mac.
# Запуск в Terminal на Mac:
#   bash <(curl -fsSL "https://raw.githubusercontent.com/dier55555-cpu/dier55555-cpu.github.io/cursor/aleksandr-themes-6562/Cursor/themes/aleksandr-cursor-ru/install-on-mac.sh")
set -euo pipefail

echo "==> Русский интерфейс Cursor"

CURSOR_BIN=""
if command -v cursor >/dev/null 2>&1; then
  CURSOR_BIN="cursor"
elif [[ -x "/Applications/Cursor.app/Contents/Resources/app/bin/cursor" ]]; then
  CURSOR_BIN="/Applications/Cursor.app/Contents/Resources/app/bin/cursor"
fi

USER_DIR="${HOME}/Library/Application Support/Cursor/User"
EXT_DIR="${HOME}/.cursor/extensions"
mkdir -p "$USER_DIR" "$EXT_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || pwd)"
# When run via bash <(curl ...), BASH_SOURCE may be /dev/fd — fall back to Downloads/tmp
if [[ ! -d "${SCRIPT_DIR}/." ]] || [[ "${SCRIPT_DIR}" == /dev/* ]]; then
  SCRIPT_DIR="/tmp"
fi

RU_VSIX_LOCAL="${SCRIPT_DIR}/MS-CEINTL.vscode-language-pack-ru.vsix"
HELPER_VSIX_LOCAL="$(ls -1 "${SCRIPT_DIR}"/aleksandr-cursor-ru-*.vsix 2>/dev/null | tail -1 || true)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

download_ru_pack() {
  local out="$1"
  echo "==> Скачиваю Russian Language Pack…"
  curl -fsSL -o "${out}.gz" \
    "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/MS-CEINTL/vsextensions/vscode-language-pack-ru/latest/vspackage"
  # Marketplace отдаёт gzip; распаковываем в .vsix (zip)
  gunzip -c "${out}.gz" > "$out"
  rm -f "${out}.gz"
  file "$out"
}

install_vsix() {
  local vsix="$1"
  if [[ -n "$CURSOR_BIN" ]]; then
    "$CURSOR_BIN" --install-extension "$vsix" && return 0
  fi
  # Manual unpack into ~/.cursor/extensions
  local name
  name="$(unzip -p "$vsix" extension/package.json | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['publisher']+'.'+d['name']+'-'+d['version'])")"
  local dest="${EXT_DIR}/${name}"
  rm -rf "$dest"
  mkdir -p "$dest"
  unzip -q "$vsix" -d "$TMP/unpack-$$"
  cp -R "$TMP/unpack-$$/extension/." "$dest/"
  echo "OK → $dest"
}

echo "==> Ставлю Language Pack…"
if [[ -n "$CURSOR_BIN" ]]; then
  "$CURSOR_BIN" --install-extension MS-CEINTL.vscode-language-pack-ru && echo "OK marketplace" || true
fi

# Ensure pack present
if ! ls -d "${EXT_DIR}"/ms-ceintl.vscode-language-pack-ru-* >/dev/null 2>&1 \
   && ! ls -d "${EXT_DIR}"/MS-CEINTL.vscode-language-pack-ru-* >/dev/null 2>&1; then
  RU_VSIX="$RU_VSIX_LOCAL"
  if [[ ! -f "$RU_VSIX" ]]; then
    RU_VSIX="${TMP}/ru.vsix"
    download_ru_pack "$RU_VSIX"
  fi
  install_vsix "$RU_VSIX"
fi

echo "==> Ставлю helper-плагин aleksandr-cursor-ru…"
HELPER_VSIX="$HELPER_VSIX_LOCAL"
if [[ -z "${HELPER_VSIX}" || ! -f "${HELPER_VSIX}" ]]; then
  # download from github branch
  HELPER_VSIX="${TMP}/aleksandr-cursor-ru.vsix"
  curl -fsSL -o "$HELPER_VSIX" \
    "https://github.com/dier55555-cpu/dier55555-cpu.github.io/raw/cursor/aleksandr-themes-6562/Cursor/themes/aleksandr-cursor-ru/aleksandr-cursor-ru-1.0.0.vsix" \
    || HELPER_VSIX=""
fi
if [[ -n "${HELPER_VSIX}" && -f "${HELPER_VSIX}" ]]; then
  install_vsix "$HELPER_VSIX"
else
  # Install from source folder if present in repo checkout
  SRC=""
  for cand in \
    "${HOME}/Projects/dier55555-cpu.github.io/Cursor/themes/aleksandr-cursor-ru" \
    "${HOME}/Projects/Cursor/themes/aleksandr-cursor-ru" \
    "${SCRIPT_DIR}"
  do
    if [[ -f "${cand}/package.json" && -f "${cand}/extension.js" ]]; then
      SRC="$cand"
      break
    fi
  done
  if [[ -n "$SRC" ]]; then
    DEST="${EXT_DIR}/aleksandr.aleksandr-cursor-ru-1.0.0"
    rm -rf "$DEST"
    mkdir -p "$DEST"
    cp "${SRC}/package.json" "${SRC}/extension.js" "$DEST/"
    [[ -f "${SRC}/README.md" ]] && cp "${SRC}/README.md" "$DEST/"
    echo "OK → $DEST (from source)"
  else
    echo "WARN: helper VSIX не найден — Language Pack + locale всё равно включат русский."
  fi
fi

echo "==> Пишу locale.json…"
cat > "${USER_DIR}/locale.json" <<'EOF'
{
  "locale": "ru"
}
EOF
echo "OK → ${USER_DIR}/locale.json"
cat "${USER_DIR}/locale.json"

echo
echo "ГОТОВО."
echo "1) Полностью закрой Cursor: Cmd+Q"
echo "2) Открой Cursor снова"
echo "3) Меню/панели/настройки (из VS Code) будут на русском"
echo "   Экраны Agent/Chat Cursor могут остаться на английском — ограничение продукта."
