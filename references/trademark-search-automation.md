# Trademark Search Automation — техническая спецификация автоматического поиска

> **Этот файл — специализация над общим слоем веб-инструментов** `references/web-research-tools.md`. Базовые принципы выбора инструмента (agent-browser / Tavily / WebFetch / WebSearch / MCP), типовые сценарии и правила конфиденциальности — там. Здесь — детальные протоколы для **трёх конкретных баз ТЗ-поиска**: linkmark.ru, WIPO GBD Similar Name, WIPO Madrid Monitor.

Технический документ, описывающий **автоматизированный** слой поиска товарных знаков, на котором работает skill `trademark-search`. Дополняет методический `references/trademark-similarity-search.md`: тот отвечает на вопрос **«что и по каким критериям искать»**, этот — **«какими инструментами и в какой последовательности это сделать»**.

**Поиск — автоматический.** Ручной workflow остаётся только как fallback (если инструменты недоступны или агент не справился).

Данные в файле основаны на **реальной разведке** 2026-06-02 с тестовым обозначением «Aspirin».

> **Tavily подключён к локальному Legal Overlay (namespace обновлён 2026-09-16).** `/search`, `/extract` и асинхронный `/research` доступны через `mcp__legal-overlay__tavily_*`. Direct adapter читает `TAVILY_API_KEY` из общего local secret store; отдельная настройка Tavily в Codex/Claude и серверный proxy не используются. `agent-browser` (linkmark.ru/WIPO GBD) также остаётся локальным.

## 1. Стек

| Инструмент | Тип | Роль |
|---|---|---|
| **agent-browser** (Vercel Labs, [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser)) | CLI на Rust + npm-обёртка | Браузерная автоматизация: поиск на платформе Роспатента, linkmark.ru и WIPO GBD, навигация по SPA-сайтам с формами и CAPTCHA |
| **Tavily** ([tavily.com](https://www.tavily.com/)) | REST API | Точечный extract по URL (Madrid Monitor карточки) + общий /search для фона |
| **PowerShell** / **Bash** | host shell | Запуск обоих инструментов из skill |

### Установка agent-browser

**Требования**: Node.js (v18+).

**На Windows через winget user-scope**:
```powershell
winget install OpenJS.NodeJS.LTS --source winget --scope user --accept-source-agreements --accept-package-agreements --silent
# После установки PATH обновляется только в новой сессии.
# Для текущей сессии — добавить вручную:
$nodeDir = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.16.0-win-x64"
$env:PATH = "$nodeDir;$env:PATH"

npm install -g agent-browser
agent-browser install  # Загружает Chrome for Testing в ~/.agent-browser/browsers/
```

**Проверка**: `agent-browser --version` → должно вернуть `agent-browser X.Y.Z`.

**Альтернатива**: Cargo (Rust) — `cargo install agent-browser`. Не требует Node.js.

### Tavily API

1. Регистрация на [tavily.com](https://www.tavily.com/) → бесплатный тариф **1000 credits/месяц**.
2. Получить API key вида `tvly-...` или `tvly-dev-...`.
3. Сохранить в `.env` в корне проекта:
   ```
   TAVILY_API_KEY=tvly-...
   ```
4. **Обязательно**: `.env` должен быть в `.gitignore` (уже добавлен).

## 2. Глобальные принципы автоматизации

1. **Skill не выдумывает результатов**. Если инструмент не вернул данные или вернул ошибку — это фиксируется в отчёте. Никаких подставленных номеров регистраций.
2. **Ref-ы НЕ стабильны между страницами**. Обязательная процедура: каждый раз `snapshot` → найти элемент **по подписи** (`textbox "Brand name"`, `button "Найти"`) → использовать соответствующий `@eN`. **Хардкодить ref-ы запрещено.**
3. **CAPTCHA — точка передачи управления юристу.** Если детектирован `reCAPTCHA "I'm not a robot"` или подобный — skill останавливается, просит юриста решить в открытом окне Chrome, продолжает в той же сессии.
4. **Все запросы фиксируются** в финальном отчёте: какая база, какой запрос, дата/время, число найденных, persistent URL результата.
5. **Каждый источник имеет fallback-цепочку.** Если primary недоступен — секондари; если и тот недоступен — ручной режим с явной пометкой `[ПРОВЕРИТЬ ИСТОЧНИК]`.
6. **Никакой массовой выгрузки.** Tavily документация и Madrid Monitor ToS не одобряют массовый scraping. Skill работает «как человек смотрит конкретный знак»: точечно, по IR-номерам, найденным на предыдущем шаге.
7. **Конфиденциальность**: предполагаемые наименования товарных знаков **не считаем существенными данными** (юридическое решение проекта). Поиск в публичных API/сайтах допустим.

## 3. Технические правила agent-browser

### 3.1 Запуск с видимым окном

По умолчанию `agent-browser` работает в **headless**-режиме. Для разведки и для случаев, где может потребоваться ручное вмешательство (CAPTCHA), запускать с **`--headed`**:

```powershell
agent-browser --headed --session <session_name> open <url>
```

Без `--headed` reCAPTCHA блокирует доступ — нет видимого окна, юрист не может нажать на чекбокс.

### 3.2 Сессии

Каждой базе — своя сессия с **persistent cookies / localStorage**:
- `--session rospatent` — для поисковой платформы Роспатента;
- `--session linkmark` — для linkmark.ru;
- `--session wipo-gbd` — для WIPO GBD;
- `--session madrid` — для Madrid Monitor (когда нужен поиск IR-номеров).

Сессии хранятся в `~/.agent-browser/sessions/<name>/`. CAPTCHA, решённая один раз в сессии, переживает рестарты сессии — Cloudflare cookies сохраняются.

### 3.3 Запреты PowerShell-пайпинга

**Нельзя** пайпить вывод команд через `Select-Object -Last N` — daemon не закрывает stdout, pipe ждёт EOF и виснет:

```powershell
# НЕ ДЕЛАТЬ:
agent-browser ... open ... | Select-Object -Last 5

# ДЕЛАТЬ:
agent-browser ... open ... --json
# (потом отдельной командой `agent-browser ... snapshot`)
```

### 3.4 Формат вывода

Всегда `--json` для машинного парсинга:
```json
{"success":true,"data":{"title":"...","url":"..."},"error":null}
```
Для snapshot — без `--json`, выводится в виде accessibility tree с `[ref=eN]` метками.

### 3.5 Cleanup

После каждого цикла skill вызывает:
```powershell
agent-browser --session <name> close
# Или для аварийной очистки всех:
agent-browser close --all
```

### 3.6 Главное правило поиска ref-ов

```
1. snapshot → получить accessibility tree
2. Найти строку с нужной подписью:
   - "Поиск товарных знаков, НМПТ и заявок" → linkmark поле поиска
   - "Brand name" → WIPO GBD поле
   - "Search" → кнопка submit (любая база)
3. Извлечь @eN из той же строки
4. Использовать @eN в команде fill/click
```

## 4a. Поисковая платформа Роспатента — первичная база РФ (официальная)

**Назначение**: официальный поиск Роспатента `searchplatform.rospatent.gov.ru/trademarks` — первоисточник (Приоритет 1). Покрывает **ТЗ РФ**, **общеизвестные ТЗ РФ** (ст. 1508 ГК РФ) и **международные ТЗ**, со встроенными **фонетическим / семантическим / нечётким** поиском — то, чего нет в linkmark.ru. Логин для базового поиска не требуется (проверено 2026-09-02). SPA — только `agent-browser` (тип рендера как у WIPO GBD; Tavily не подходит).

### 4a.1 Подтверждённые возможности (2026-09-02, разведка через браузер)

- Вкладки объектов: **Товарные знаки** → **ТЗ РФ / Общеизвестные ТЗ РФ / Международные ТЗ** (+ Промышленные образцы);
- Тип знака: **Словесный / Изобразительный / Атрибутный**;
- Режим поиска: **По написанию / Семантический / Фонетический**;
- Точность: **Строгое совпадение (чёткий) / Частичное сходство (нечёткий)**;
- Опции: игнорировать пробелы, разбить слова на части, совпадение начала / конца слова, двубуквенные основы; фильтры.

### 4a.2 Протокол (уровень действий; селекторы — live-recon)

1. `agent-browser --headed --session rospatent open https://searchplatform.rospatent.gov.ru/trademarks`;
2. `wait 6000` (SPA грузится долго) → `snapshot -i -c`;
3. Выбрать вкладку **ТЗ РФ**, тип **Словесный**, режим **Фонетический** (или **Семантический**) + **Частичное сходство**;
4. Найти поле ввода по подписи → `fill "@eXX" "{вариант обозначения}"`;
5. `click` кнопку **Поиск** → `wait` → `eval "window.location.href"` (сохранить persistent URL выдачи);
6. `snapshot -i -c` → распарсить результаты (номер свидетельства, класс МКТУ, правообладатель, дата приоритета / регистрации, статус);
7. Повторить на вкладке **Общеизвестные ТЗ РФ**; при необходимости — **Международные ТЗ**;
8. Топ близких — открыть карточку, снять реквизиты; `agent-browser --session rospatent close`.

> ✅ **Live-recon выполнен 2026-09-03** (боевой прогон по «Полиэффект»). Форма и подписи подтверждены на реальном сайте: вкладки `LabelText "ТЗ РФ" / "Общеизвестные ТЗ РФ" / "Международные ТЗ"`; тип `listitem "Словесный" / "Изобразительный" / "Атрибутный"`; поле `textbox "Введите текст для поиска"`; кнопка `button "Поиск"`; режимы `listitem "По написанию" / "Семантический" / "Фонетический"`; точность `radio "Строгое совпадение (четкий поиск)" / "Частичное сходство (нечеткий поиск)"` (по умолчанию — нечёткий); опции `checkbox "Игнорировать пробелы"` (вкл. по умолчанию) `/ "Разбить слова на части" / "Совпадение начала слова" / "Совпадение конца слова"`. Хардкод `@ref` по-прежнему запрещён (§2, §3.6) — каждый раз `snapshot` → поиск по подписи; при изменении вёрстки — процедура §15.
>
> **Два подтверждённых на прогоне урока:**
> 1. **URL выдачи не меняется** — результаты рендерятся в той же странице (`window.location.href` остаётся `…/trademarks`). Persistent-URL выдачи у Роспатента нет; в отчёте цитировать по свидетельству/дате + persistent-URL linkmark как кросс-ссылку.
> 2. **Ссылка «Открыть карточку» — JS-`onclick` с пустым `href`**: открывает карточку в новой вкладке, которую текущий `agent-browser` (нет команды `tabs`) не читает. Реквизиты знака (обозначение, классы МКТУ, статус) брать из **linkmark.ru** (показывает их прямо в выдаче) или ФИПС по номеру. Результаты Роспатента дают номера/правообладателей/даты; текст обозначения и классы — кросс-проверкой в linkmark.

## 4. linkmark.ru — поиск ТЗ в РФ (кросс-проверка)

**Назначение**: агрегатор ТЗ РФ, кросс-проверка к платформе Роспатента. Бесплатный поиск по названию / номеру / правообладателю. Изображения и заявки — платно.

### 4.1 URL-схема

| Страница | URL |
|---|---|
| Главная | `https://linkmark.ru/` |
| Результаты поиска | `https://linkmark.ru/request/{base64hash}?new=1` — **persistent**, можно сохранять в отчёте |
| Карточка ТЗ | Открывается как **оверлей** на странице результатов. URL не меняется. |
| Источник (на ФИПС) | Берётся из `link "Источник"` рядом с каждым результатом |

### 4.2 Структура одного результата

Идёт повторяющийся блок (разделитель — `rowheader "Свидетельство:"`):
```
- rowheader "Свидетельство:" + cell "{№}" (с link на оверлей)
- rowheader "Приоритет:" + cell "{дата}" (опционально)
- rowheader "Дата регистрации:" + cell "{дата}"
- rowheader "МКТУ:" + cell "{классы через запятую}"
- rowheader "Правообладатель:" + cell "{ФИО/наименование + адрес + страна}"
- rowheader "Неохраняемые элементы товарного знака:" + cell "{текст}" (опционально)
- link "Источник" → ссылка на ФИПС
- generic "{текстовое представление обозначения}" clickable
```

### 4.3 Фильтры (изначально все активны)

- ТЗ РФ / МР (Мадридские);
- Действует / Не действует / Не продлен;
- Сортировка по номеру (по умолчанию — по релевантности).

### 4.4 Счётчики

На странице результатов наверху:
- `link "{N} товарных знаков"`;
- `link "{N} заявок ₽"` — иконка ₽ → **платно**, в MVP не используем;
- `link "{N} МНН"` — международные непатентованные наименования ЛС (для фармы — релевантно).

### 4.5 Пагинация

- `button "Показать еще 100 результатов из {total}"`;
- `button "Показать все"` — может быть много (1419 для «Аспирин»), осторожно с памятью браузера.

В MVP — top-30 (по умолчанию загружается достаточно для скрининга); расширяем по запросу юриста.

### 4.6 Протокол поиска

```powershell
# 1. Открыть главную
agent-browser --headed --session linkmark open https://linkmark.ru/ --json

# 2. Snapshot → найти @ref поля поиска по подписи "Поиск товарных знаков, НМПТ и заявок"
agent-browser --session linkmark snapshot -i -c
# (в выводе: textbox "Поиск товарных знаков..." [ref=eXX])

# 3. Заполнить
agent-browser --session linkmark fill "@eXX" "{вариант обозначения}" --json

# 4. Snapshot → найти @ref кнопки "Найти"
agent-browser --session linkmark snapshot -i -c

# 5. Кликнуть Найти
agent-browser --session linkmark click "@eYY" --json

# 6. Подождать загрузки результатов
agent-browser --session linkmark wait 3000

# 7. Сохранить persistent URL результата
agent-browser --session linkmark eval "window.location.href" --json
# (использовать в отчёте)

# 8. Snapshot результатов и парсинг по разделителю rowheader "Свидетельство:"
agent-browser --session linkmark snapshot -i -c

# 9. По необходимости открыть карточки топ-3 близких:
# найти link [ref=eN] для номера ТЗ и кликнуть
agent-browser --session linkmark click "@eN" --json
agent-browser --session linkmark wait 2000
agent-browser --session linkmark snapshot -i -c
# Закрыть оверлей:
agent-browser --session linkmark click "@e10"  # обычно "Закрыть" — найти по подписи

# 10. Повторить шаги 2-9 для каждого варианта обозначения

# 11. Cleanup
agent-browser --session linkmark close
```

### 4.7 Парсинг результатов в record

```
record = {
  source: "linkmark.ru",
  certificate_number: "{из cell после Свидетельство:}",
  registration_date: "{из cell после Дата регистрации:}",
  priority_date: "{из cell после Приоритет:, если есть}",
  nice_classes: ["5", "35"],  // split по ", "
  holder: "{из cell после Правообладатель:}",
  unprotected_elements: "{из cell после Неохраняемые элементы..., если есть}",
  representation_text: "{из generic clickable справа}",
  source_link: "{href из link Источник}",
  jurisdiction: "RU" | "MR" (Madrid через linkmark)
}
```

### 4.8 Ограничения

- Изображения и расширенный поиск по Венской классификации — платно (500–1000 ₽);
- Заявки (₽ иконка) — платно;
- Fuzzy search **отсутствует** — нужны вариации обозначения (5–10 формулировок).

## 5. WIPO Global Brand Database — Similar Name Search

**Назначение**: международный fuzzy-поиск по агрегатору 75+ национальных баз + Мадридский реестр.

### 5.1 URL-схема

| Страница | URL |
|---|---|
| Главная Similar Name | `https://branddb.wipo.int/branddb/en/similarname` |
| Результаты | `https://branddb.wipo.int/en/similarname/results?sort=score%20desc&start=0&rows=30&asStructure={URL_ENCODED_JSON}` |
| Карточка brand | `https://branddb.wipo.int/en/similarname/brand/{BRAND_ID}?asStructure={...}` |

**JSON-параметр `asStructure`** содержит весь поисковый запрос:
```json
{
  "boolean": "AND",
  "bricks": [
    {
      "key": "brandName",
      "value": "Aspirin",
      "strategy": "Fuzzy"
    }
  ]
}
```

URL-encoded и подставленный в query-string — позволяет конструировать запрос программно без клика по форме.

### 5.2 Стратегии поиска (combobox)

| Strategy | Назначение |
|---|---|
| **Embedded** (default) | Результаты содержат введённый термин |
| **Match exact expression** | Точное совпадение |
| **Fuzzy** | Близкое написание — **главное для similar name** |
| **Phonetic** | Звуковое сходство |
| **Stemming** | Общий корень |

В MVP при отсутствии указаний юриста — **Fuzzy** (наиболее релевантно для pre-filing screening).

### 5.3 CAPTCHA

**В тесте 2026-06-02** reCAPTCHA `"I'm not a robot"` появилась в **headless**-режиме и НЕ появилась в **--headed**. Тем не менее — протокол должен закладываться на CAPTCHA:

1. После `open` — `snapshot` для проверки;
2. Если в выводе `checkbox "I'm not a robot"` — пауза, сообщение юристу: «Решите CAPTCHA в открытом окне Chrome»;
3. Юрист → клик в окне, после успеха — нажимает Enter в консоли (или текстом в чат «готово»);
4. Skill продолжает с `snapshot`.

Сессия с решённой CAPTCHA сохраняется через `--session wipo-gbd` (Cloudflare cookies).

### 5.4 Структура результатов

На странице результатов:
- `Results view` / `Statistics view`;
- `Change layout`: List / Grid / Gallery;
- `Sort`: Most relevant / Least / Recent / Oldest / ST13 asc/desc;
- `Results per page`: 30 / 60 / 120;
- **`Download results`**: PDF / Excel / Word — **первые 180 записей**.

Каждый результат:
```
- checkbox (для bulk-операций)
- generic "{обозначение в нескольких вариантах ; ; }" clickable → открывает карточку brand
- image (если есть логотип)
```

### 5.5 Карточка brand

URL: `/en/similarname/brand/{BRAND_ID}`, где `BRAND_ID` — например `NZ502018001110272` (национальный код + номер).

Структура:
- `heading "{обозначение в нескольких языках}"`;
- `button "Download PDF"`, `"Open in a new tab"`, `"← →"` (навигация);
- `heading "REGISTERED TRADEMARK - {IP_OFFICE} ({Country})"`;
- `link "Find similar logos"`;
- Секции: **NAMES AND ADDRESSES** (поля 730/740/750), **CLASSIFICATION** (Nice 511 / Vienna 531), **IP OFFICE**, **FURTHER INFORMATION**.

### 5.6 Tavily не работает

`Tavily /extract` на URL `branddb.wipo.int` возвращает `"Failed to fetch url"` (Cloudflare блокирует серверный запрос). **Только agent-browser**.

### 5.7 Протокол поиска

```powershell
# 1. Открыть с --headed
agent-browser --headed --session wipo-gbd open https://branddb.wipo.int/branddb/en/similarname --json
agent-browser --session wipo-gbd wait 6000

# 2. Snapshot — проверить CAPTCHA
agent-browser --session wipo-gbd snapshot -i -c
# Если есть "I'm not a robot" — пауза, ждать решения юристом

# 3. Найти @ref поля "Brand name" по LabelText "Brand name"
# 4. Заполнить
agent-browser --session wipo-gbd fill "@eXX" "{обозначение}" --json

# 5. Найти @ref combobox для strategy и выбрать Fuzzy
agent-browser --session wipo-gbd select "@eYY" "Fuzzy (results are spelled similarly to entered term)" --json

# 6. Найти @ref button "Search" — теперь он активен
agent-browser --session wipo-gbd snapshot -i -c
agent-browser --session wipo-gbd click "@eZZ" --json
agent-browser --session wipo-gbd wait 8000

# 7. Сохранить persistent URL
agent-browser --session wipo-gbd eval "window.location.href" --json

# 8. Snapshot результатов
agent-browser --session wipo-gbd snapshot -i -c

# 9. По топ-3 близким — кликнуть generic с обозначением, получить URL карточки brand
# Каждая карточка → /en/similarname/brand/{ID}, сохранить ID для возможной Madrid Monitor сверки

# 10. Cleanup
agent-browser --session wipo-gbd close
```

### 5.8 Альтернатива: конструирование URL результата

Минуя форму:
```powershell
$structure = @{
  boolean = "AND"
  bricks = @(@{
    key = "brandName"
    value = "Aspirin"
    strategy = "Fuzzy"
  })
} | ConvertTo-Json -Compress
$encoded = [System.Uri]::EscapeDataString($structure)
$url = "https://branddb.wipo.int/en/similarname/results?sort=score%20desc&start=0&rows=30&asStructure=$encoded"
agent-browser --headed --session wipo-gbd open $url --json
```

Сокращает один шаг (не нужно заполнять форму).

## 6. WIPO Madrid Monitor — детальные карточки IR

**Назначение**: авторитетная проверка конкретных Мадридских регистраций по IR-номерам (`ROM.{N}`), найденным на linkmark или WIPO GBD.

### 6.1 URL-схема

| Страница | URL |
|---|---|
| Главная Madrid Monitor | `https://www3.wipo.int/madrid/monitor/en/` |
| **Прямая карточка по IR** | `https://www3.wipo.int/madrid/monitor/en/showData.jsp?ID=ROM.{IR_NUMBER}` |
| XML экспорт | `…showData.jsp?ID=ROM.{N}#` (кнопка XML на карточке) |
| PDF экспорт | `…showData.jsp?ID=ROM.{N}#` (кнопка PDF) |

### 6.2 Tavily /extract работает

**Самый дешёвый путь**: `Tavily /extract` напрямую возвращает чистый markdown ≈ 9000 символов с:
- Holder, Registration Date, Expiration Date, Nice classes;
- URL изображения знака;
- Direct link;
- Designation list (страны распространения);
- Transaction History.

**Стоимость**: 1 credit за 5 успешных extract = **0.2 credit за карточку** на basic. На advanced — 0.4 credit.

При **20 IR-номерах** в одной проверке (типичный объём из WIPO GBD) — расход ≈ **4 кредита**.

### 6.3 Протокол Tavily

**Через сервер (основной путь, подтверждено рабочим 2026-07-29) — без локального ключа:**
```
mcp__legal-overlay__tavily_extract(
  urls=["https://www3.wipo.int/madrid/monitor/en/showData.jsp?ID=ROM.{irNumber}"],
  extract_depth="advanced",
  format="markdown"
)
```
Ответ — `{"results": [{"url": ..., "raw_content": "..."}], ...}`, брать `results[0].raw_content`.

**Fallback напрямую (если сервер недоступен):**
```powershell
$envFile = "C:\...\legal-copilot\.env"
$key = (Get-Content $envFile | Where-Object { $_ -match "^TAVILY_API_KEY=" } | ForEach-Object { $_.Split("=",2)[1] }).Trim()
$headers = @{ "Authorization" = "Bearer $key"; "Content-Type" = "application/json" }
$irNumber = "1273817"
$body = @{
  urls = @("https://www3.wipo.int/madrid/monitor/en/showData.jsp?ID=ROM.$irNumber")
  extract_depth = "advanced"
  format = "markdown"
} | ConvertTo-Json
$resp = Invoke-RestMethod -Uri "https://api.tavily.com/extract" -Method Post -Body $body -Headers $headers -TimeoutSec 60
$resp.results[0].raw_content  # ← готовый markdown
```

### 6.4 Парсинг markdown в record

```
record = {
  source: "wipo-madrid-monitor",
  ir_number: "ROM.{N}",
  trademark_text: "{из heading '## {N}- {TEXT}'}",
  status: "Active" | "Inactive" | "Pending" | …,
  holder: "{из таблицы под Holder}",
  registration_date: "DD.MM.YYYY",
  expiration_date: "DD.MM.YYYY",
  nice_classes: ["05"],
  designated_countries: ["CH", "NO", "TR", …],  // из Designation list
  image_url: "{из markdown ![Image N: {TEXT}](URL)}",
  direct_link: "https://www3.wipo.int/madrid/monitor/en/showData.jsp?ID=ROM.{N}"
}
```

### 6.5 Когда не Tavily — fallback на agent-browser

Если Tavily вернул `Failed to fetch` (бывает при перегрузке) или контент пустой — agent-browser:

```powershell
agent-browser --headed --session madrid open "https://www3.wipo.int/madrid/monitor/en/showData.jsp?ID=ROM.1273817" --json
agent-browser --session madrid wait 5000
agent-browser --session madrid snapshot -i -c
```

### 6.6 Поиск IR-номеров (когда не известны заранее)

Если WIPO GBD не сработал и нужен независимый поиск на Madrid Monitor:

```powershell
agent-browser --headed --session madrid open "https://www3.wipo.int/madrid/monitor/en/" --json
agent-browser --session madrid wait 6000

# Найти поле "Search for" textbox и кнопку 🔎 через snapshot
agent-browser --session madrid snapshot -i -c
agent-browser --session madrid fill "@eXX" "{обозначение}" --json
agent-browser --session madrid click "@eYY" --json  # лупа
agent-browser --session madrid wait 6000

# В результатах: rowheader "Reg. No" — это IR-номера (формат ROM.{N})
# Извлечь топ-N и далее по 6.3 через Tavily
```

### 6.7 Что НЕ делать (граница ToS)

- Не делать массовых программных запросов типа «дай всё, что начинается на X»;
- Не сохранять локальные копии больших объёмов реестра;
- Не использовать неофициальные SOAP/REST endpoints.

**Skill использует Madrid Monitor строго в режиме «человек смотрит конкретный знак»** — точечные карточки по известным IR-номерам.

## 7. ФИПС / Реестр Роспатента — точечная сверка

**Назначение**: подтверждение конкретного РФ-номера, найденного через linkmark.

### 7.1 URL и инструмент

| Шаг | URL | Инструмент |
|---|---|---|
| Карточка ТЗ по номеру | Получается из `link "Источник"` рядом с результатом в linkmark — это уже прямая ссылка на ФИПС |
| Открытие | `WebFetch` (если страница рендерится без JS) или `agent-browser` |

В MVP мы **берём ссылку «Источник» из linkmark** и считаем её достаточной для подтверждения — отдельный запрос на ФИПС обычно не нужен.

## 8. WebSearch и Tavily /search — дополнительный контекст

**Назначение**:
- Общеизвестные ТЗ (ст. 1508 ГК РФ) — могут не быть в основных базах;
- Отраслевые упоминания обозначения (есть ли уже бренды с таким названием в фарме);
- Домены (косвенный признак занятости ниши);
- Свежие новости / споры по обозначению.

### 8.1 Протокол Tavily /search

**С доменным фильтром — через локальный Overlay:**
```
mcp__legal-overlay__tavily_search(
  query="{обозначение} товарный знак общеизвестный",
  max_results=5,
  include_domains=["vsrf.ru", "pravo.gov.ru", "rospatent.gov.ru", "consultant.ru"]
)
```

**Без доменного фильтра** — так же через Overlay:
```
mcp__legal-overlay__tavily_search(query="{обозначение} товарный знак общеизвестный", max_results=5)
```

Низкоуровневый REST-вызов ниже сохранён только для диагностики adapter-а; рабочий
skill не обходит Overlay:
```powershell
$body = @{
  query = "{обозначение} товарный знак общеизвестный"
  search_depth = "basic"
  max_results = 5
  include_domains = @("vsrf.ru", "pravo.gov.ru", "rospatent.gov.ru", "consultant.ru")
} | ConvertTo-Json
$resp = Invoke-RestMethod -Uri "https://api.tavily.com/search" -Method Post -Body $body -Headers $headers -TimeoutSec 30
$resp.results  # ← массив { title, url, score, content }
```

### 8.2 Когда использовать advanced

Для качественного синтеза по бренду (нужно ли вообще подавать заявку):

Текущий API асинхронный. Создать задачу через
`mcp__legal-overlay__tavily_research(query=..., model="mini")`, сохранить
`request_id`, затем опрашивать `mcp__legal-overlay__tavily_get_research(request_id=...)`
до `completed` или `failed`. Не создавать повторную research-задачу при статусе
`pending`: каждый запуск расходует credits.

В MVP — оставляем `/research` как опцию по запросу юриста.

## 9. CAPTCHA workflow

### 9.1 Детект

После каждого `open` на WIPO GBD / Madrid Monitor:
```powershell
$snap = agent-browser --session <s> snapshot -i -c
if ($snap -match "I'm not a robot|recaptcha|Cloudflare|captcha") {
  # CAPTCHA detected
}
```

### 9.2 Передача управления

```
Skill → юристу:
"⚠ Детектирована CAPTCHA на {URL}.
   Окно Chrome открыто (заголовок: '{title}').
   1) Перейди в окно;
   2) Реши CAPTCHA;
   3) Дождись, пока сайт пустит на основную страницу;
   4) Напиши 'готово' — продолжу."
```

### 9.3 Возобновление

После подтверждения юриста:
```powershell
agent-browser --session <s> snapshot -i -c
# Если CAPTCHA больше нет — продолжать алгоритм
# Если есть — снова попросить (макс. 3 попытки → fallback на ручной режим)
```

### 9.4 Persistence

Cookies Cloudflare сохраняются в `--session <name>` → следующие открытия в той же сессии CAPTCHA не покажут (или покажут реже).

## 10. Архитектура итогового потока

> РФ-фронт с 2026-09: первичная база — официальная платформа Роспатента (§4a, фонетика / семантика / нечёткий, включая общеизвестные ТЗ РФ), linkmark.ru (§4) — кросс-проверка. В схеме ниже «ШАГ 3» обобщает РФ-поиск (Роспатент + linkmark).

```
┌──────────────────────────────────────────────────────────┐
│ ВВОДНЫЕ (от юриста):                                     │
│ - обозначение(я)                                         │
│ - классы МКТУ                                            │
│ - юрисдикции                                             │
│ - контекст продукта                                      │
└─────────────────────┬────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────────┐
│ ШАГ 1 — Подготовка вариантов (LLM)                       │
│ 5-10 формулировок: фонетика/морфология/транслитерация/   │
│ разбивка для основного обозначения                       │
└─────────────────────┬────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────────┐
│ ШАГ 2 — Проверка инструментов                            │
│ agent-browser --version; Tavily ping; список сессий      │
│ Если что-то недоступно — fallback или предупреждение     │
└─────────────────────┬────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────────┐
│ ШАГ 3 — linkmark.ru (agent-browser)                      │
│ Для каждого варианта: поиск → парсинг → top-30 →         │
│ карточки для близких → запись records[]                  │
└─────────────────────┬────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────────┐
│ ШАГ 4 — WIPO GBD Similar Name (agent-browser, headed)    │
│ Fuzzy по основному варианту → парсинг → carточки brand → │
│ фиксация IR-номеров Мадридских записей                   │
└─────────────────────┬────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────────┐
│ ШАГ 5 — Madrid Monitor (Tavily /extract)                 │
│ Для каждого IR из шага 4: /extract карточки → парсинг    │
│ markdown → запись records[]                              │
└─────────────────────┬────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────────┐
│ ШАГ 6 — Контекст (Tavily /search)                        │
│ Общеизвестные ТЗ, отраслевой фон, домены                 │
└─────────────────────┬────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────────┐
│ ШАГ 7 — Анализ (LLM)                                     │
│ Сравнение по 4 критериям + однородность товаров +        │
│ совокупный риск — по trademark-similarity-search.md      │
└─────────────────────┬────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────────┐
│ ШАГ 8 — Отчёт (.md + опционально .docx)                  │
│ Включая раздел "Журнал автоматизации"                    │
└──────────────────────────────────────────────────────────┘
```

## 11. Журнал автоматизации в отчёте

В отчёт включается раздел, фиксирующий:

```markdown
## Журнал автоматизации

### Использованные инструменты
- agent-browser X.Y.Z
- Tavily API (basic / advanced)

### Запросы

| Этап | База | Запрос | Persistent URL | Найдено | Ошибки |
|---|---|---|---|---|---|
| 3 | linkmark.ru | "[БРЕНД]" | https://linkmark.ru/request/{hash}?new=1 | 12 ТЗ + 3 заявки | — |
| 3 | linkmark.ru | "[BRAND]" | https://linkmark.ru/request/{hash}?new=1 | 2 ТЗ | — |
| 4 | WIPO GBD Fuzzy | "[BRAND]l" | https://branddb.wipo.int/en/similarname/results?... | 7 | CAPTCHA (решена руками) |
| 5 | Madrid Monitor | ROM.1234567 | https://www3.wipo.int/madrid/monitor/en/showData.jsp?ID=ROM.1234567 | OK | — |
| 6 | Tavily /search | "[БРЕНД] общеизвестный" | — | 3 | — |

### Tavily credits израсходовано
- /search basic: 2 × 1 = 2 credits
- /extract advanced: 7 × 0.4 = 2.8 credits
- Итого: ~5 credits
```

## 12. Fallback-цепочки

| Этап | Primary | Secondary | Hard fallback |
|---|---|---|---|
| РФ-поиск (первичный) | agent-browser --session rospatent (платформа Роспатента) | agent-browser --session linkmark (агрегатор) | Ручной поиск на fips.ru / rospatent.gov.ru |
| linkmark поиск | agent-browser --session linkmark | — | Ручной поиск юристом, передача markdown-таблицы |
| WIPO GBD поиск | agent-browser --headed --session wipo-gbd | — | Ручной поиск; либо переход в TMview (если ЕС важен) |
| WIPO GBD CAPTCHA | Ручное решение в открытом окне | Cookie из предыдущей сессии | Cloud Browserbase (платно, на будущее) |
| Madrid Monitor карточка | Tavily /extract | agent-browser /showData.jsp | Ручной просмотр |
| Контекст | Tavily /search | WebSearch (встроенный) | Ручной поиск |
| Все вообще не работает | Skill сообщает юристу о невозможности; **никаких выдуманных данных** | | |

## 13. Конфиденциальность и комплаенс

| Аспект | Решение |
|---|---|
| Утечка обозначения в публичные базы | **Допустимо**: предполагаемые наименования товарных знаков НЕ считаются существенными данными (юридическое решение проекта) |
| Tavily logs | Запросы попадают в их логи. Учитываем при отправке через `/search` и `/extract` |
| Madrid Monitor ToS | Только точечные карточки по IR-номерам, никаких массовых запросов |
| WIPO GBD CAPTCHA-bypass | Не используем платные сервисы обхода в MVP. Только ручное решение |
| linkmark.ru ToS | Чтение через браузер агента — серая зона, трактуем как «помощь юристу в обычном просмотре» |
| Хранение результатов | Локально в логе сессии (см. §14) — в проектной директории, в git не пушим |

## 14. Локальное логирование

**Deliverable-отчёт — `.docx` в `workflow/`** (человеку / бизнесу), сборка по `references/docx-generation.md`; в worktree-сессии — в основную `workflow/` по абсолютному пути. В `logs/` кладётся только технический материал для агента и проверяемости.

Каждый запуск skill пишет лог в `logs/trademark-search/{YYYY-MM-DD-HH-MM}-{обозначение}/`:
- `automation-journal.json` — структурированный журнал запросов;
- `screenshots/` — скриншоты ключевых страниц (для проверяемости);
- `raw-responses/` — сырые ответы Tavily и snapshot-ы agent-browser;
- `report.md` — техническая .md-копия отчёта (рядом с .docx, для следующих сессий агента; не заменяет .docx-deliverable).

Папку `logs/trademark-search/` добавить в `.gitignore` — содержит обозначения, которые могут быть чувствительны при работе с реальным клиентом.

## 15. Версионирование протоколов

Протоколы § 4-6 могут устареть при изменении вёрстки сайтов. Признаки:
- `snapshot` не возвращает ожидаемые подписи (`textbox "Brand name"`, `rowheader "Свидетельство:"`);
- Skill сообщает «не нашёл поле поиска».

**Процедура актуализации**:
1. Юрист запускает `agent-browser --headed open {URL}` руками;
2. Делает `snapshot` и фиксирует новые ref-ы и подписи;
3. Обновляет соответствующий раздел этого файла;
4. Коммит с пометкой «vN.Z — verified against site as of {DATE}».

## 16. Связанные файлы

- `references/web-research-tools.md` — **родительский слой** (общие принципы веб-инструментов, дерево выбора, типовые сценарии для всех задач, не только ТЗ);
- `references/trademark-similarity-search.md` — методология (юридическая база, 4 критерия сходства; структуру отчёта не дублирует — ссылается на SKILL.md);
- `references/agent-browser-cheatsheet.md` — локальная справка agent-browser CLI (команды, опции, выгрузка `--help`);
- `references/confidentiality-rules.md` — обращение с обозначением;
- `references/risk-scale.md` — шкала риска;
- `skills/trademark-search/SKILL.md` — навык, использующий эту автоматизацию;
