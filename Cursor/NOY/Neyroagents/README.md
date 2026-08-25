# Подключение MCP: кабинет Neyroagents

Отдельный MCP от ДендрИИт. Ключ ДендрИИт сюда **не** копировать.

## На Mac

```text
/Users/user/Projects/NOY/Neyroagents/noya-ai-mcp/   ← MCP этого кабинета
```

В `~/.cursor/mcp.json` второй сервер, например `noya-neyroagents`, с `envFile` на эту папку.

## Правило

| Работаешь с | Включи MCP | Выключи |
|-------------|------------|---------|
| ДендрИИт (`anna`, `легион`) | `noya` | `noya-neyroagents` |
| Neyroagents | `noya-neyroagents` | `noya` |

Оба сразу — риск перепутать кабинет (`whoami`).

Секрет: только локальный файл / Cursor Secrets `NOYA_KEY_NEYROAGENTS`. Не в git.
