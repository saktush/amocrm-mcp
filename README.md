# amoCRM MCP Server

🌐 **Русский** | [English](README.en.md)

MCP-сервер для API v4 [amoCRM](https://www.amocrm.ru/) (Kommo). Предоставляет 36 инструментов для работы со сделками, контактами, компаниями, задачами, примечаниями, воронками, связями, аналитикой и не только.

Построен на [FastMCP](https://github.com/jlowin/fastmcp). Работает с Claude Desktop, Cursor и любым MCP-совместимым клиентом.

## Возможности

- **36 MCP-инструментов** в 11 областях (сделки, контакты, компании, задачи, примечания, воронки, связи, аккаунт, пакетные операции, неразобранное, аналитика)
- **OAuth 2.0**: обновление токенов с сохранением на диск
- **Ограничение частоты запросов**: 7 запросов/с, автоматическая пауза при 429 с экспоненциальной задержкой и джиттером
- **Нормализация HAL+JSON**: удаляет `_links`, разворачивает `_embedded`
- **Единый формат ответов**: `{data, pagination}` или `{error, status_code, detail}`
- Транспорты **stdio, Streamable HTTP и SSE**

## Быстрый старт

### 1. Установка

```bash
pip install -e .
```

### 2. Настройка

Скопируйте `.env.example` в `.env` и заполните данные вашего аккаунта amoCRM:

```bash
cp .env.example .env
```

Минимум нужен `AMO_SUBDOMAIN` и один из способов авторизации:
- **OAuth (рекомендуется, с автообновлением):** `AMO_CLIENT_ID`, `AMO_CLIENT_SECRET`, `AMO_REDIRECT_URI`, затем один раз запустите `amocrm-mcp-auth`, чтобы получить токены (см. [Получение первой пары токенов](#получение-первой-пары-токенов-oauth)).
- **Долгоживущий токен (без обновления):** только `AMO_ACCESS_TOKEN`. Без refresh-токена сервер не пытается обновлять токен; отклонённый токен приводит к понятной ошибке 401.

Эти режимы взаимозаменяемы. Если существует файл токенов (`AMO_TOKEN_FILE`), он приоритетнее `AMO_ACCESS_TOKEN`, о чём при запуске выводится предупреждение; в стартовом логе также указано, какой источник и режим используются.

Дополнительные параметры платформы (используются для запросов к API и обновления токена):
- `AMO_BASE_DOMAIN` — `amocrm.ru` (по умолчанию), `amocrm.com` или `kommo.com`
- `AMO_REDIRECT_URI` — redirect URI для OAuth, по умолчанию `https://localhost`; должен точно совпадать с настройками интеграции

### Получение первой пары токенов (OAuth)

Refresh-токен выдаётся только при обмене кода авторизации (у долгоживущих токенов его нет). Задайте `AMO_SUBDOMAIN`, `AMO_CLIENT_ID`, `AMO_CLIENT_SECRET` (ID интеграции и секретный ключ: **Настройки → Интеграции → ваша интеграция → Ключи и доступы**) и `AMO_REDIRECT_URI` (ровно так, как он указан в интеграции), затем выполните одну из команд:

```bash
amocrm-mcp-auth --code <код авторизации>   # код со вкладки «Ключи и доступы», действует 20 минут, одноразовый
amocrm-mcp-auth                            # открывает страницу согласия и принимает редирект на локальный redirect URI http://localhost:<порт>/
```

Чтобы использовать другой env-файл, добавьте `--env-file dev.env`. Токены записываются в `AMO_TOKEN_FILE` и никогда не выводятся на экран; дальше сервер обновляет их автоматически.

### 3. Запуск

**На локальной машине**, из корня репозитория с активированным venv:

```bash
# stdio (по умолчанию — используется десктопными и CLI-клиентами ниже)
python -m amocrm_mcp
```

**На сервере** (без интерфейса, доступ удалённый) вместо stdio используйте транспорт Streamable HTTP:

```bash
AMO_TRANSPORT=http AMO_PORT=8000 python -m amocrm_mcp
```

Затем укажите любому MCP-клиенту с поддержкой Streamable HTTP адрес `http://<хост-сервера>:8000/mcp`. Запускайте сервер под менеджером процессов (systemd, `tmux`, `supervisord` и т. п.), чтобы он не завершался при отключении. Режим `AMO_TRANSPORT=sse` (`http://<хост-сервера>:8000/sse`) оставлен для старых клиентов, но Streamable HTTP — современный стандарт и единственный транспорт, который OpenAI Codex поддерживает для удалённых серверов, поэтому, если нет особой причины, выбирайте `http`.

Развёртывание в Docker, доступное по сети (любой Linux-сервер или Docker Desktop), включая пошаговое подключение Claude, Codex и Cursor к удалённому серверу, описано в [README-deploy.md](README-deploy.md).

> **Важно:** каждый клиент ниже запускает сервер как подпроцесс с собственным урезанным `PATH` и **не найдёт** «голый» `python`, как это делает ваша оболочка. Всегда указывайте клиентам **абсолютный путь** к интерпретатору из venv проекта, например `/absolute/path/to/amocrm-mcp/.venv/bin/python`. Использование просто `"python"` — самая частая причина ошибки клиента `Failed to spawn process: No such file or directory`.

## Подключение к клиентам

Во всех примерах предполагается, что шаги 1–2 выше выполнены. Замените `/absolute/path/to/amocrm-mcp` на реальный путь к репозиторию и подставьте свои `AMO_SUBDOMAIN`/`AMO_ACCESS_TOKEN` (либо положитесь на файл `.env` и файл токенов, созданный `amocrm-mcp-auth`, — сервер читает их сам, и тогда блоки `env` ниже для локального использования можно опустить).

### Claude Desktop

Отредактируйте `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "amocrm": {
      "command": "/absolute/path/to/amocrm-mcp/.venv/bin/python",
      "args": ["-m", "amocrm_mcp"],
      "env": {
        "AMO_SUBDOMAIN": "your-subdomain",
        "AMO_ACCESS_TOKEN": "your-token"
      }
    }
  }
}
```

После этого перезапустите Claude Desktop: файл читается только при запуске.

### Claude Code (CLI)

```bash
claude mcp add --transport stdio amocrm \
  -e AMO_SUBDOMAIN=your-subdomain \
  -e AMO_ACCESS_TOKEN=your-token \
  -- /absolute/path/to/amocrm-mcp/.venv/bin/python -m amocrm_mcp
```

Добавьте `-s user`, чтобы сервер был доступен во всех проектах, а не только в текущем.

### Codex (CLI / Desktop)

Оба читают `~/.codex/config.toml`. Добавьте:

```toml
[mcp_servers.amocrm]
command = "/absolute/path/to/amocrm-mcp/.venv/bin/python"
args = ["-m", "amocrm_mcp"]

[mcp_servers.amocrm.env]
AMO_SUBDOMAIN = "your-subdomain"
AMO_ACCESS_TOKEN = "your-token"
```

### Cursor

Добавьте в `~/.cursor/mcp.json` (глобально) или `.cursor/mcp.json` в проекте (для одного проекта) — формат такой же, как у Claude Desktop:

```json
{
  "mcpServers": {
    "amocrm": {
      "command": "/absolute/path/to/amocrm-mcp/.venv/bin/python",
      "args": ["-m", "amocrm_mcp"],
      "env": {
        "AMO_SUBDOMAIN": "your-subdomain",
        "AMO_ACCESS_TOKEN": "your-token"
      }
    }
  }
}
```

То же можно сделать из интерфейса: **Settings → MCP → Add new global MCP server** — это правит тот же файл.

## Инструменты

| Область | Инструменты | Описание |
|---------|-------------|----------|
| **Сделки** | `leads_list`, `leads_get`, `leads_search`, `leads_create`, `leads_create_complex`, `leads_update` | Весь жизненный цикл сделки |
| **Контакты** | `contacts_get`, `contacts_search`, `contacts_create`, `contacts_update` | Управление контактами |
| **Компании** | `companies_get`, `companies_search`, `companies_create`, `companies_update` | Управление компаниями |
| **Задачи** | `tasks_list`, `tasks_get`, `tasks_create`, `tasks_update` | Задачи CRM |
| **Примечания** | `notes_list`, `notes_create` | Примечания к сущностям |
| **Воронки** | `pipelines_list`, `pipelines_get`, `pipelines_list_statuses` | Воронки и статусы |
| **Связи** | `associations_get_linked`, `associations_link_entities` | Связи между сущностями |
| **Аккаунт** | `account_get`, `account_list_users`, `account_list_custom_fields` | Данные аккаунта |
| **Пакетные операции** | `batch_create_leads`, `batch_create_contacts`, `batch_update_leads` | Массовые операции |
| **Аналитика** | `analytics_get_events`, `analytics_get_pipeline_analytics`, +1 | Аналитика CRM |
| **Неразобранное** | `unsorted_list`, `unsorted_accept`, `unsorted_reject` | Входящие неразобранные заявки |

## Получение данных для доступа к amoCRM

1. Откройте ваш аккаунт amoCRM → **Настройки** → **Интеграции**
2. Создайте новую интеграцию (или используйте существующую)
3. На вкладке **Ключи и доступы** скопируйте **ID интеграции** (`AMO_CLIENT_ID`) и **секретный ключ** (`AMO_CLIENT_SECRET`; показывается один раз, при перегенерации существующие авторизации аннулируются), а redirect URI, который вы будете использовать, укажите в `AMO_REDIRECT_URI`
4. Получите токены через `amocrm-mcp-auth` (см. выше). Refresh-токен нельзя скопировать из интерфейса: он выдаётся только при обмене кода авторизации. Долгоживущий токен с той же вкладки тоже подойдёт, но не обновляется
5. Ваш поддомен — часть адреса аккаунта до `.amocrm.ru`

Refresh-токены одноразовые и истекают через 3 месяца без использования. Сервер ротирует и сохраняет их в `AMO_TOKEN_FILE` при каждом обновлении, поэтому используйте отдельный файл токенов для каждого экземпляра сервера и каждого аккаунта и не делите файл токенов между окружениями.

## Лицензия

MIT
