# Кабинет: Neyroagents

Локально: `/Users/user/Projects/NOY/Neyroagents/`  
В репо: `Cursor/NOY/Neyroagents/`

Отдельный аккаунт Нои (~11 воркфлоу). Ключ кабинета `NOY/dendriit/` сюда **не** копировать.

| Поле | Значение |
|------|----------|
| Секрет | `NOYA_KEY_NEYROAGENTS` |
| API | `https://noya-ai.ru` (`Authorization: Bearer nk_live_…`) |
| Пространства | `GET /api/workflows` + заголовок `X-Workflow-Id` |

## Содержимое

| Папка | Что |
|-------|-----|
| [ДендрИИт/](./ДендрИИт/) | воркфлоу **Студия ДендрИИт - АГЕНТ** |
| `noya-ai-mcp/` | MCP этого кабинета (пакет с `/api/mcp-info`; ключ не в git) |

Открывать в Cursor папку кабинета `Neyroagents/`. Сначала `whoami`. Чужой воркфлоу без `X-Workflow-Id` не править.
