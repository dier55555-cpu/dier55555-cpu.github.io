const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const os = require("os");

function userDataDir() {
  const home = os.homedir();
  switch (process.platform) {
    case "darwin":
      return path.join(home, "Library", "Application Support", "Cursor");
    case "win32":
      return path.join(process.env.APPDATA || path.join(home, "AppData", "Roaming"), "Cursor");
    default:
      return path.join(home, ".config", "Cursor");
  }
}

function localeJsonPath() {
  return path.join(userDataDir(), "User", "locale.json");
}

function writeLocaleRu() {
  const file = localeJsonPath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ locale: "ru" }, null, 2) + "\n", "utf8");
  return file;
}

function readLocale() {
  const file = localeJsonPath();
  if (!fs.existsSync(file)) return null;
  try {
    return JSON.parse(fs.readFileSync(file, "utf8")).locale || null;
  } catch {
    return null;
  }
}

function hasRussianPack() {
  const ext = vscode.extensions.getExtension("MS-CEINTL.vscode-language-pack-ru");
  return Boolean(ext);
}

async function enableRussian() {
  const file = writeLocaleRu();
  const packOk = hasRussianPack();
  const parts = [
    `Записан locale: ru → ${file}`,
    packOk
      ? "Russian Language Pack найден."
      : "Russian Language Pack НЕ найден. Установите расширение «Russian Language Pack for Visual Studio Code» (MS-CEINTL.vscode-language-pack-ru), затем повторите.",
    "Полностью закройте Cursor (Cmd+Q / Exit) и откройте снова — язык применится после рестарта."
  ];
  const pick = await vscode.window.showInformationMessage(
    parts.join(" "),
    "Перезагрузить окно"
  );
  if (pick === "Перезагрузить окно") {
    await vscode.commands.executeCommand("workbench.action.reloadWindow");
  }
}

async function showStatus() {
  const locale = readLocale();
  const packOk = hasRussianPack();
  vscode.window.showInformationMessage(
    `locale.json: ${locale || "нет"}; Language Pack RU: ${packOk ? "да" : "нет"}; appLanguage: ${vscode.env.language}`
  );
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("aleksandrCursorRu.enableRussian", enableRussian),
    vscode.commands.registerCommand("aleksandrCursorRu.showStatus", showStatus)
  );

  // При первом запуске — тихо прописать locale, если ещё не ru
  const locale = readLocale();
  if (locale !== "ru") {
    writeLocaleRu();
  }
}

function deactivate() {}

module.exports = { activate, deactivate };
