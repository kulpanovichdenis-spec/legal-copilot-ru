"""
Обезличивание текста перед отправкой в LLM и восстановление в ответе.

Локальный движок для pre-LLM конвейера legal-copilot (tools/pre_anonymize/).
Регэксп-детекторы покрывают основные типы юридических/персональных данных:
ФИО (кириллица и латиница, включая инициалы, с фильтром стоп-слов от ложных
срабатываний на юридическом контексте), названия компаний (рус./ин., с ОПФ,
включая запятую перед иностранным ОПФ), ИНН/ОГРН/КПП/СНИЛС/паспорт/счета/
IBAN/SWIFT, суммы, даты, телефоны, email, адреса (рус. и англ. формат),
названия стран.

Особенности реализации:
  - whitelist грузится из tools/pre_anonymize/whitelist.local.txt (gitignored);
  - NER-слой (Natasha) включается переменной окружения PRE_ANON_NER=1
    (по умолчанию выключен; при отсутствии natasha — тихий fallback к regex);
  - Anonymizer(exclude_labels=...) позволяет профили строгости
    (например, не маскировать СУММА/ДАТА для аналитики сроков и расчётов).

Архитектура:
    a = Anonymizer()
    text_for_llm = a.anonymize(raw_text)
    ... работа LLM с text_for_llm ...
    safe_response = a.deanonymize(llm_response)

Плейсхолдеры содержат только тип и количество цифр/слов — данные не раскрываются.
"""

from __future__ import annotations

import re
from typing import Callable, Pattern


# Whitelist отсутствует — все ПДн и реквизиты маскируются без исключений.
_WHITELIST: set[str] = set()
_WHITELIST_SORTED: list[str] = []


# ── ОПФ (организационно-правовые формы) ─────────────────────────────────
_OPF = (
    r"ООО|ОАО|ЗАО|ПАО|АО|НКО|НАО|НПО|ИП|ФГУП|ГУП|МУП|"
    r"Общество\s+с\s+ограниченной\s+ответственностью|"
    r"Публичное\s+акционерное\s+общество|"
    r"Акционерное\s+общество|"
    r"Закрытое\s+акционерное\s+общество|"
    r"Открытое\s+акционерное\s+общество|"
    r"Индивидуальный\s+предприниматель"
)

# ── ОПФ иностранные (суффикс после названия) ────────────────────────────
# Фикс 2026-09-30 (реальный двуязычный договор поставки с китайскими сторонами):
# «Co., Ltd.», «LIMITED» и транслит «Ко., Лтд.» не распознавались — название
# компании уходило в ФИО-паттерн по кускам, «Co., Ltd.» оставался открытым.
# Длинные формы — раньше коротких («Co., Ltd.» до «Ltd.»).
_OPF_FOREIGN = (
    r"Co\.,?\s*Ltd\.?|CO\.,?\s*LTD\.?|Company\s+Limited|Pte\.?\s*Ltd\.?|Limited|LIMITED|"
    r"Ко\.,?\s*Лтд\.?|Лтд\.?|Лимитед|ЛИМИТЕД|ГмбХ|"
    r"GmbH|LLC|Inc\.?|Ltd\.?|LTD\.?|Corp\.?|AG|S\.A\.|B\.V\.|N\.V\.|PLC|SE|S\.r\.l\."
)

# ── Страны (Итерация 4, фикс от 2026-07-30) ──────────────────────────────
# Не гэзетир городов/регионов (это неограниченный список — не покрыть
# регэкспом полностью, честно признаём это ограничением ниже), но страны —
# конечный, редко меняющийся список, поэтому явный список себя оправдывает.
# Длинные/официальные названия — раньше коротких форм-подстрок в алтернации
# (Russian Federation перед Russia, People's Republic of China перед China
# и т. д.) — иначе более короткая форма «съест» совпадение первой.
_COUNTRIES = (
    r"Russian Federation|Russia|"
    r"People['’]s Republic of China|China|Hong Kong|Taiwan|"
    r"United States of America|United States|USA|U\.S\.A\.|U\.S\.|"
    r"United Kingdom|UK|Republic of Korea|South Korea|North Korea|Korea|"
    r"United Arab Emirates|UAE|Saudi Arabia|"
    r"Germany|France|Italy|Spain|Portugal|Netherlands|Belgium|Switzerland|"
    r"Austria|Poland|Ukraine|Belarus|Kazakhstan|Uzbekistan|Kyrgyzstan|"
    r"Tajikistan|Turkmenistan|Georgia|Armenia|Azerbaijan|Moldova|Mongolia|"
    r"Japan|India|Vietnam|Thailand|Malaysia|Indonesia|Philippines|Singapore|"
    r"Pakistan|Bangladesh|Sri Lanka|Nepal|"
    r"Brazil|Mexico|Argentina|Chile|Colombia|Canada|Australia|New Zealand|"
    r"Ireland|Sweden|Norway|Finland|Denmark|Iceland|Greece|Turkey|Israel|"
    r"Egypt|South Africa|Cyprus|Luxembourg|"
    r"Czech Republic|Slovakia|Hungary|Romania|Bulgaria|Croatia|Serbia|"
    r"Slovenia|Estonia|Latvia|Lithuania|Qatar|Kuwait|Bahrain|Oman|Jordan|Lebanon"
)

# ── Адресные маркеры на латинице (Итерация 4, фикс от 2026-07-30) ───────
# ADDRESS_INDEX (ниже, среди _PATTERNS) покрывает только русский формат
# («индекс, ..., ул./дом»). Реальный баг: англоязычные адреса (China/Russia
# контракты) не распознавались вовсе — маскировались только случайно, если
# фрагмент совпадал с общим FIO_LATIN (две заглавных подряд). Ниже —
# отдельные маркеры для типовых англоязычных адресных конструкций.
_ADDR_STREET_EN = r"Street|Road|Avenue|Blvd|Boulevard|Lane|Drive|Way|Highway|Alley"
_ADDR_AREA_EN = r"Village|District|Region|Province|Area|County|Municipality|Territory"

# ── Страны на кириллице (Итерация 5, фикс от 2026-07-31) ────────────────
# Реальный баг: билингвальный контракт маскировал страну/адрес только в
# английской колонке — русская колонка того же документа осталась открытой
# («Россия», «Российской Федерации», «Китай» — ни разу не замаскированы).
# Список зеркалит _COUNTRIES (длинные/официальные формы раньше коротких).
_COUNTRIES_RU = (
    r"Российской Федерации|Российская Федерация|Россия|"
    r"Китайской Народной Республики|Китайская Народная Республика|Китай|"
    r"Гонконг|Тайвань|"
    r"Соединённых Штатов Америки|Соединенных Штатов Америки|"
    r"Соединённые Штаты Америки|Соединенные Штаты Америки|США|"
    r"Соединённого Королевства|Соединенного Королевства|"
    r"Соединённое Королевство|Соединенное Королевство|Великобритания|"
    r"Республики Корея|Республика Корея|Южная Корея|Северная Корея|Корея|"
    r"Объединённых Арабских Эмиратов|Объединенных Арабских Эмиратов|"
    r"Объединённые Арабские Эмираты|Объединенные Арабские Эмираты|ОАЭ|"
    r"Саудовская Аравия|Саудовской Аравии|"
    r"Германия|Германии|Франция|Франции|Италия|Италии|Испания|Испании|"
    r"Португалия|Португалии|Нидерланды|Нидерландов|Бельгия|Бельгии|"
    r"Швейцария|Швейцарии|Австрия|Австрии|Польша|Польши|Украина|Украины|"
    r"Беларусь|Беларуси|Казахстан|Казахстана|Узбекистан|Узбекистана|"
    r"Киргизия|Киргизии|Кыргызстан|Таджикистан|Таджикистана|"
    r"Туркменистан|Туркменистана|Грузия|Грузии|Армения|Армении|"
    r"Азербайджан|Азербайджана|Молдова|Молдовы|Монголия|Монголии|"
    r"Япония|Японии|Индия|Индии|Вьетнам|Вьетнама|Таиланд|Таиланда|"
    r"Малайзия|Малайзии|Индонезия|Индонезии|Филиппины|Филиппин|"
    r"Сингапур|Сингапура|Пакистан|Пакистана|Бангладеш|Шри-Ланка|Непал|Непала|"
    r"Бразилия|Бразилии|Мексика|Мексики|Аргентина|Аргентины|Чили|"
    r"Колумбия|Колумбии|Канада|Канады|Австралия|Австралии|"
    r"Новая Зеландия|Новой Зеландии|"
    r"Ирландия|Ирландии|Швеция|Швеции|Норвегия|Норвегии|Финляндия|Финляндии|"
    r"Дания|Дании|Исландия|Исландии|Греция|Греции|Турция|Турции|"
    r"Израиль|Израиля|Египет|Египта|"
    r"ЮАР|Южно-Африканская Республика|Южно-Африканской Республики|"
    r"Кипр|Кипра|Люксембург|Люксембурга|"
    r"Чехия|Чехии|Словакия|Словакии|Венгрия|Венгрии|Румыния|Румынии|"
    r"Болгария|Болгарии|Хорватия|Хорватии|Сербия|Сербии|"
    r"Словения|Словении|Эстония|Эстонии|Латвия|Латвии|Литва|Литвы|"
    r"Катар|Катара|Кувейт|Кувейта|Бахрейн|Бахрейна|Оман|Омана|"
    r"Иордания|Иордании|Ливан|Ливана"
)

# ── Строительные блоки для ФИО-паттернов (Итерация 3) ───────────────────
# _WL_RU — «длинное» кириллическое слово (3+ символа): Иванов, О'Брайен, Ким
# _WM_RU — «среднее» (2+ символа): покрывает короткие восточные компоненты (Ли, Ын)
# Оба допускают дефис (Салтыков-Щедрин) и апостроф (О'Брайен) внутри слова.
_WL_RU = (r"[А-ЯЁ][а-яё]{2,}"
           r"(?:'[А-ЯЁ][а-яё]+)*"
           r"(?:[-—][А-ЯЁ][а-яё]+)*")
_WM_RU = (r"[А-ЯЁ][а-яё]{1,}"
           r"(?:'[А-ЯЁ][а-яё]+)*"
           r"(?:[-—][А-ЯЁ][а-яё]+)*")
_SUF_RU = r"(?:\s+(?:оглы|кызы|ибн|бин|бен))?"

# ── Стоп-лист для FIO-паттернов (фиксы B1, B2 из AUDIT_anonymizer.md) ──
# Если ХОТЬ одно слово в матче FIO принадлежит этому списку — замена отменяется.
# Это устраняет массовые ложные срабатывания на юридическом контексте:
# «Гражданский Кодекс Российской», «Министерство Внутренних Дел»,
# «Согласно Договору И.О.», «Председатель Г.К.» и т.п.
# Цена: если рядом со стоп-словом стоит настоящее ФИО («Главный Бухгалтер
# Иванова»), захват пропускается — приоритет на сохранение юр. контекста.
# Хранится в нижнем регистре; сравнение тоже в нижнем регистре.
_FIO_STOPWORDS: frozenset[str] = frozenset({
    # Стороны и роли в договорах (B1)
    "договор", "договору", "договором", "договоре", "договора", "договоры",
    "сторона", "стороны", "сторону", "сторон", "стороной",
    "поставщик", "поставщика", "поставщику", "поставщиком",
    "покупатель", "покупателя", "покупателю", "покупателем",
    "заказчик", "заказчика", "заказчику", "заказчиком",
    "подрядчик", "подрядчика", "подрядчику",
    "исполнитель", "исполнителя", "исполнителю",
    "арендатор", "арендатора", "арендодатель", "арендодателя",
    "продавец", "продавца", "получатель", "получателя",
    "плательщик", "плательщика", "клиент", "клиента",
    "уважаемый", "уважаемая", "уважаемые",
    "председатель", "председателя", "директор", "директора",
    "генеральный", "главный", "бухгалтер", "сотрудник", "работник",
    "свидетель", "свидетеля", "истец", "истца",
    "ответчик", "ответчика", "представитель", "представителя",
    "эксперт", "эксперта", "специалист", "специалиста",
    "нотариус", "нотариуса", "судья", "судьи",
    "подрядчик", "подрядчика", "подрядчику",
    "согласно", "настоящий", "настоящая", "настоящего", "настоящему",
    "раздел", "пункт", "глава", "статья", "приложение", "часть",
    "город", "москва", "санкт", "спб",
    # Гос. органы, кодексы и НПА (B2)
    "министерство", "министерства", "общество", "обществом",
    "акционерное", "открытое", "закрытое", "публичное",
    "кодекс", "кодексу", "кодексом", "кодексе", "кодекса",
    "федерация", "федерации", "федеральная", "федеральный", "федеральное",
    "российская", "российской", "российский", "российское", "российскому",
    "поставки", "услуг", "услуги", "аренды", "подряда",
    "внутренних", "дел", "юстиции", "обороны", "финансов",
    "суд", "суда", "арбитражный", "арбитражного", "арбитражному",
    "антимонопольная", "антимонопольной",
    "служба", "службы", "правительство", "правительства",
    "высший", "высшего", "конституционный", "верховный", "верховного",
    "центральный", "банк", "россии",
    "налоговый", "налогового", "налоговая", "налоговой",
    "гражданский", "гражданского", "гражданская",
    "уголовный", "уголовного", "уголовное",
    "трудовой", "трудового", "земельный", "земельного",
    "семейный", "семейного",
    "решение", "решением", "постановление", "постановлением",
    "приказ", "приказом", "распоряжение", "указ", "закон", "законом",
    # Должности и звания (Итерация 3: Старший Юрист Петров → не ФИО)
    "лидер", "лидера", "лидеру",
    "президент", "президента", "президенту",
    "министр", "министра", "министру",
    "депутат", "депутата", "депутату",
    "советник", "советника", "советнику",
    "секретарь", "секретаря",
    "посол", "посла",
    "губернатор", "губернатора",
    "мэр", "мэра",
    "сенатор", "сенатора",
    "гражданин", "гражданина",
    "старший", "старшая", "старшего", "старшей",
    "младший", "младшая", "младшего",
    "ведущий", "ведущая", "ведущего",
    "юрист", "юриста", "юристу", "юристом",
    "менеджер", "менеджера", "менеджеру",
    "аналитик", "аналитика",
    "инспектор", "инспектора",
    "начальник", "начальника", "начальнику",
    "руководитель", "руководителя", "руководителю",
    "заместитель", "заместителя", "заместителю",
    "помощник", "помощника", "помощнику",
    # Типовые заголовки таблиц и финансовые термины
    "активности", "активность", "активностей",
    "стоимость", "стоимости", "стоимостью",
    "бюджет", "бюджета", "бюджету", "бюджетом",
    "наименование", "наименования", "наименованию",
    "количество", "количества", "количеству",
    "единица", "единицы", "единице",
    "итого", "всего", "сумма", "суммы", "сумме",
    "примечание", "примечания",
    # Прилагательные, образующие устойчивые сочетания (Итерация 3: Северный Поток)
    "торговый", "торговая", "торгового",
    "правовой", "правовая", "правового",
    "первый", "первая", "первого", "первом",
    "второй", "вторая", "второго", "втором",
    "третий", "третья", "третьего",
    "северный", "северная", "северного", "северном",
    "южный", "южная", "южного",
    "западный", "западная", "западного",
    "восточный", "восточная", "восточного",
    "рабочий", "рабочая", "рабочего",
    "деловой", "деловая",
    "финансовый", "финансовая", "финансового",
    "коммерческий", "коммерческая", "коммерческого",
    "технический", "техническая", "технического",
    "исполнительный", "исполнительная", "исполнительного",
    "государственный", "государственная", "государственного",
    "муниципальный", "муниципальная", "муниципального",
    "международный", "международная", "международного",
    # Названия международных организаций и государств (фикс 2026-09-30:
    # «Организации Объединённых Наций», «Китайской Народной Республики» → ФИО;
    # страну затем маскирует COUNTRY_RU своим плейсхолдером).
    "объединенных", "объединённых", "наций", "организации", "конвенция", "конвенции",
    "народной", "народная", "республики", "республика", "соединенных", "соединённых",
    "штатов", "европейский", "европейская", "европейской", "фармакопея", "фармакопеи",
    # Органы и акты ЕАЭС/регуляторики (фикс 2026-10-02: «Решение Совета Евразийской
    # экономической комиссии» → ФИО).
    "евразийской", "евразийского", "евразийская", "евразийский", "совета", "совет",
    "комиссии", "комиссия", "коллегии", "коллегия", "решения", "правил", "правила",
})


def _fio_accept(m: re.Match) -> bool:
    """Возвращает False, если матч содержит стоп-слово — отменяет маскировку."""
    text = m.group(0)
    tokens = re.findall(r"[А-ЯЁа-яё]+", text)
    return not any(tok.lower() in _FIO_STOPWORDS for tok in tokens)


# ── Стоп-лист и фильтр для латинских ФИО (Итерация 3) ───────────────────
_FIO_LATIN_STOPWORDS: frozenset[str] = frozenset({
    # Служебные слова
    "the", "of", "and", "in", "for", "from", "with", "by", "to", "or", "at", "on", "as",
    # ОПФ на латинице
    "llc", "inc", "ltd", "gmbh", "ag", "sa", "bv", "nv", "plc", "corp", "co", "lp",
    # Обращения
    "mr", "mrs", "ms", "dr", "prof",
    # Месяцы (чтобы не захватить «January Smith»)
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    # Структурные слова документа (баг найден 2026-07-30: без этого списка
    # средний-инициал паттерн ниже ловил бы «Article A. General», «Exhibit
    # B. Pricing» и т. п. как имена — зеркалит кириллический список выше
    # раздел/пункт/глава/статья/приложение/часть).
    "article", "section", "exhibit", "schedule", "annex", "annexure",
    "attachment", "appendix", "part", "clause", "paragraph", "chapter",
    "table", "figure", "item", "addendum", "letter",
    # Частые заголовки разделов договора (пред-существующий риск 2-словного
    # паттерна ФИО, обнаружен при регрессии 2026-07-30: «Article A. General
    # Provisions» ловило «General Provisions» как имя). Список не исчерпывающий —
    # это снижение риска для типовых заголовков, не полное решение.
    "general", "provisions", "entire", "agreement", "force", "majeure",
    "dispute", "resolution", "governing", "law", "representations",
    "warranties", "indemnification", "confidentiality", "termination",
    "miscellaneous", "severability", "counterparts", "amendment", "waiver",
    "notices", "assignment", "definitions", "interpretation", "execution",
    # Должности, подразделения и география (фикс 2026-09-30: «Head of
    # International Commerce Department», «Economic & Technological Development
    # Zone» ловились как ФИО) — зеркалит кириллический список должностей выше.
    "head", "director", "manager", "officer", "president", "chairman", "executive",
    "deputy", "chief", "department", "division", "international", "commerce",
    "commercial", "business", "development", "representative", "sales", "finance",
    "financial", "company", "bank", "branch", "economic", "technological", "zone",
    "road", "street", "district", "province", "region", "city", "republic", "people",
    "dollars", "dollar", "states", "united", "kingdom", "federation",
    "nations", "convention", "european", "pharmacopoeia", "organization", "organisation",
    # Регуляторные руководства (ICH/GCP/GMP): «Good Clinical Practice», «Technical
    # Requirements … for Human Use» (фикс 2026-10-02).
    "good", "clinical", "practice", "practices", "manufacturing", "laboratory",
    "technical", "requirements", "human", "use", "harmonization", "harmonisation",
    "conference", "guideline", "guidelines", "registration", "pharmaceuticals",
    "council", "commission", "eurasian", "union", "decision", "regulation",
    # Роли сторон (2026-10-05: «Name: Customer» → ФИО и распространение по тексту).
    "customer", "customers", "supplier", "suppliers", "buyer", "buyers", "seller", "sellers",
    "contractor", "subcontractor", "vendor", "purchaser", "licensor", "licensee", "sublicensee",
    "manufacturer", "consignee", "consignor", "party", "parties", "client", "employer",
    "employee", "lessor", "lessee", "landlord", "tenant", "distributor", "agent", "principal",
})

# Предшествующее слово-рубрикатор: «Exhibit B. Pricing», «Article A. General».
_STRUCT_PREV_WORDS: frozenset[str] = frozenset({
    "article", "section", "exhibit", "schedule", "annex", "annexure", "attachment",
    "appendix", "part", "clause", "paragraph", "chapter", "table", "figure", "item",
})


def _fio_latin_accept(m: re.Match) -> bool:
    """Фильтр для латинских ФИО: отклоняет юр. термины и нарицательные слова."""
    tokens = re.findall(r"[A-Za-z]+", m.group(0))
    if any(t.lower() in _FIO_LATIN_STOPWORDS for t in tokens):
        return False
    prev = re.findall(r"[A-Za-z]+", m.string[max(0, m.start() - 20):m.start()])
    return not (prev and prev[-1].lower() in _STRUCT_PREV_WORDS)


# ── Признак имени для ФИО из полных слов (2026-10-02) ───────────────────
# Шаблон «2–3 слова с заглавной» без инициалов и отчества — главный источник
# ложных ФИО в юр. тексте («Злоупотребление Истцом», «Управление Росреестра»,
# «Western Blotting»). Такой матч принимается, только если одно из слов —
# известное имя (рус. — в любом падеже, лат. — точно). Инициалы и отчество —
# самостоятельный признак имени. Не гэзетир всех имён: редкое имя без
# инициалов/отчества/якоря может проскочить — его ловят SIGNATORY/«Mr.»/«Name:».
_FIRST_NAMES_RU = frozenset("""
александр алексей анатолий андрей антон аркадий арсений артем артур богдан борис вадим
валентин валерий василий виктор виталий владимир владислав всеволод вячеслав геннадий
георгий глеб григорий даниил данила денис дмитрий евгений егор иван игорь илья кирилл
константин леонид максим марат матвей михаил никита николай олег павел петр роман руслан
сергей станислав степан тимофей тимур федор филипп эдуард юрий ярослав рустам ринат
александра алина алла алена анастасия ангелина анна антонина валентина валерия вера
вероника виктория галина дарья диана евгения екатерина елена елизавета жанна зинаида
инна ирина карина кира кристина ксения лариса лидия любовь людмила маргарита марина
мария надежда наталья наталия нина оксана олеся ольга полина раиса светлана софия софья
тамара татьяна ульяна юлия яна эльвира альбина регина алиса милана вероника
""".split())
_FIRST_NAMES_LAT = frozenset("""
john michael david james robert william richard thomas mark paul peter george steven
andrew kenneth brian kevin daniel anthony edward jason matthew timothy eric stephen jacob
ryan nicholas frank scott charles christopher joseph patrick sean simon martin henry
alexander alexey alexei sergey sergei ivan dmitry dmitri andrey andrei mikhail nikolay
nikolai vladimir igor oleg pavel maxim anton artem yuri yury roman denis evgeny evgeniy
konstantin viktor victor boris kirill ilya elena olga natalia natalya irina tatiana
tatyana anna maria ekaterina yekaterina svetlana marina yulia julia anastasia ksenia
mary patricia jennifer linda elizabeth barbara susan jessica sarah karen nancy lisa
margaret sandra emily michelle laura helen anne emma sophie hans klaus jean pierre marie
luca marco carlos juan wei li hua ming jun lei jing yan fang
""".split())


def _ru_name_root(name: str) -> str:
    n = name.replace("ё", "е")
    return n[:-1] if n[-1] in "аяйь" and len(n) > 4 else n


_FIRST_NAME_ROOTS_RU = frozenset(_ru_name_root(n) for n in _FIRST_NAMES_RU)


def _is_first_name(token: str) -> bool:
    low = token.lower().replace("ё", "е")
    if low in _FIRST_NAMES_LAT or low in _FIRST_NAMES_RU:
        return True
    for k in range(4, min(len(low), 12) + 1):
        if low[:k] in _FIRST_NAME_ROOTS_RU and len(low) - k <= 3:
            return True
    # Короткое имя в косвенном падеже: «Анну/Анне/Анной» → «Анна», «Веру» → «Вера»
    # (корневая проверка выше требует основу ≥ 4 букв), фикс 2026-10-08.
    for ending in ("ой", "ою", "у", "ю", "е", "ы", "и"):
        if low.endswith(ending):
            stem = low[: -len(ending)]
            if len(stem) >= 2 and (stem + "а" in _FIRST_NAMES_RU or stem + "я" in _FIRST_NAMES_RU):
                return True
    return False


def _has_name_evidence(value: str) -> bool:
    """Инициалы, отчество или известное имя среди слов матча."""
    if re.search(r"(?:^|[\s.])[A-ZА-ЯЁ]\.", value) or re.match(r"(?:Mr|Mrs|Ms|Dr)\.?\s", value):
        return True
    tokens = re.findall(r"[A-Za-zА-ЯЁа-яё]{2,}", value)
    return any(_is_patronymic(t) or _is_first_name(t) for t in tokens)


# Сдвиг окна (фикс 2026-10-08): матч «Направляем Иванову Ивану», за которым идёт
# отчество «Петровичу», начался на слово раньше имени и обрезал отчество — оно
# оставалось открытым. Такой матч отбрасывается, и сканирование находит полное ФИО
# со следующего слова. Сдвиг — только если матч неполный: без инициалов и отчества
# и кончается именем. Полное ФИО («Ивановым И. П.», «Смирнов Сергей Петрович») не
# сдвигается, даже если дальше стоит слово, похожее на отчество («Основной долг»).
_NEXT_WORD = re.compile(r"[ \t]+([А-ЯЁ][а-яё]+)")


def _starts_one_word_early(value: str) -> bool:
    if "." in value:
        return False
    tokens = re.findall(r"[А-ЯЁа-яё]+", value)
    if not tokens or any(_is_patronymic(t) for t in tokens):
        return False
    return _is_first_name(tokens[-1])


def _fio_ru_accept(m: re.Match) -> bool:
    nxt = _NEXT_WORD.match(m.string, m.end())
    if nxt and _is_patronymic(nxt.group(1)) and _starts_one_word_early(m.group(0)):
        return False
    return _fio_accept(m) and _has_name_evidence(m.group(0))


def _fio_latin_named_accept(m: re.Match) -> bool:
    value = m.group(0)
    if re.match(r"(?:Mr|Mrs|Ms|Dr)\.?\s", value):
        # обращение — признак имени; стоп-лист проверяем только по фамилии
        rest = re.sub(r"^(?:Mr|Mrs|Ms|Dr)\.?\s+", "", value)
        return not any(w.lower() in _FIO_LATIN_STOPWORDS for w in re.findall(r"[A-Za-z]+", rest))
    return _fio_latin_accept(m) and _has_name_evidence(value)


# Должность перед именем подписанта (SIGNATORY_EN): слова роли пропускаются,
# маскируется только имя за ними.
_ROLE_EN = (
    r"(?:(?:its|the|their|his|her|Mr\.?|Mrs\.?|Ms\.?|Dr\.?|General|Executive|Managing|"
    r"Deputy|Vice|Chief|Commercial|Sales|Financial|Finance|Legal|Technical|Regional|"
    r"Senior|Country|Head|Director|Manager|President|Officer|CEO|CFO|COO|of|and|"
    r"International|Commerce|Business|Development|Department|Division|Procurement|"
    r"Supply|Operations|Representative|Authori[sz]ed|Attorney|Chairman|Board)\s+)*"
)


def _address_span_accept(m: re.Match) -> bool:
    """Адрес по якорю: только если похож на адрес (цифра или несколько частей)."""
    span = m.group(1)
    if "\x00" in span:  # whitelist-токен внутри — не трогаем
        return False
    return bool(re.search(r"\d", span)) or "," in span


def _signatory_accept(m: re.Match) -> bool:
    """Имя подписанта: отсекает роли/стороны вместо имени («в лице Представителя Заказчика»)."""
    name = m.group(1)
    tokens = re.findall(r"[A-Za-zА-ЯЁа-яё]{2,}", name)
    if not tokens:
        return False
    low = [t.lower() for t in tokens]
    return not any(t in _FIO_STOPWORDS or t in _FIO_LATIN_STOPWORDS for t in low)


# Отчество — сильный признак имени: такой матч не отменяется фильтром документа.
_PATRONYMIC = re.compile(r"(?:ович|евич|ич|овна|евна|ична|инична)(?:а|у|ем|е|ы|ой|ою)?$", re.IGNORECASE)
# Женское отчество в косвенном падеже («Ивановне», «Петровны», «Сергеевной»).
# Те же окончания у прилагательных («Основной», «Уголовной», «Публичной»), поэтому
# форма признаётся отчеством только при основе-имени: «Иван|овне», «Серге|евне».
_PATRONYMIC_F_OBLIQUE = re.compile(r"(?:овн|евн|ичн|иничн)(?:ы|е|у|ой|ою)$", re.IGNORECASE)


# Основы отчеств от имён, которых нет в словаре имён: Львовна, Яковлевна,
# Семеновна, Кузьминична.
_PATRONYMIC_ONLY_STEMS = frozenset({"льв", "яковл", "семен", "кузьм"})


def _patronymic_stem_is_name(stem: str) -> bool:
    """Основа отчества — имя: «Иван|овне», «Павл|овне» (Павел), «Юрь|евне» (Юрий),
    «Михайл|овне» (Михаил), «Иль|иничне» (Илья)."""
    s = stem.lower().replace("ё", "е")
    if s in _PATRONYMIC_ONLY_STEMS:
        return True
    candidates = {s, s + "а", s + "я"}
    if s.endswith("ь"):
        candidates.add(s[:-1] + "ий")
    if s.endswith("йл"):
        candidates.add(s[:-2] + "ил")
    if s.endswith("л"):
        candidates.add(s[:-1] + "ел")
    return any(_is_first_name(c) for c in candidates)


def _is_patronymic(token: str) -> bool:
    if _PATRONYMIC.search(token):
        return True
    m = _PATRONYMIC_F_OBLIQUE.search(token)
    return bool(m) and _patronymic_stem_is_name(token[: m.start()])

# Определённые термины документа в кавычках: (the “Effective Date”), (далее — «Продукт»).
_QUOTED_TERM = re.compile(r"[“\"«‘]([^“”\"«»‘’\n\d]{2,80})[”\"»’]")


def _doc_context(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """Словарь документа для фильтра ложных ФИО.

    Возвращает (слова, встречающиеся в тексте со строчной буквы; основы слов
    определённых терминов в кавычках).
    Имя человека в договоре со строчной буквы не пишется и определённым
    термином не бывает — «Business Days» при «30 days» в тексте и
    «Effective Date» при (the “Effective Date”) — не ФИО.
    """
    # По основе: «Дополнительного» ↔ «дополнительное» в тексте (фикс 2026-10-01).
    vocab = frozenset(
        _stem(w.lower()) for w in re.findall(r"(?<![A-Za-zА-ЯЁа-яё])[a-zа-яё][a-zа-яё'\-]{2,}", text)
    )
    stems: set[str] = set()
    for phrase in _QUOTED_TERM.findall(text):
        toks = re.findall(r"[A-Za-zА-ЯЁа-яё]{3,}", phrase)
        if 1 <= len(toks) <= 6:
            stems.update(_stem(t.lower()) for t in toks)
    return vocab, frozenset(stems)


# Окончания для грубой основы слова: «Продукта» ↔ «Продукт», «Рабочих» ↔ «Рабочий»,
# «Days» ↔ «Day». Длинные — раньше коротких; основа не короче 4 букв.
_ENDINGS: tuple[str, ...] = tuple(sorted((
    "ами", "ями", "ого", "его", "ему", "ому", "ыми", "ими", "ах", "ях", "ов", "ев",
    "ей", "ой", "ый", "ий", "ая", "яя", "ое", "ее", "ом", "ем", "ую", "юю", "их", "ых",
    "а", "я", "у", "ю", "е", "ы", "и", "о", "ь", "es", "s",
), key=len, reverse=True))


def _stem(word: str) -> str:
    for e in _ENDINGS:
        if word.endswith(e) and len(word) - len(e) >= 4:
            return word[: -len(e)]
    return word


# Паттерны применяются В ПОРЯДКЕ. Первый матч «съедает» подстроку.
# Паттерн-запись: (имя, regex, метка_плейсхолдера, номер_группы_для_замены, accept).
# group=0 — заменяется весь матч; иначе — только эта группа (остальное сохраняется,
# чтобы LLM видела структуру «Наименование товара: [ТОВАР_1]»).
# accept(match) — необязательный фильтр; если возвращает False, замена пропускается.
# ── Контрольные суммы реквизитов (идея из стороннего анонимайзера, 2026-10-02) ──
# Позволяют маскировать ИНН/ОГРН/БИК без слова-метки: случайное число проходит
# проверку с вероятностью ~1/11, номер договора/артикул — как правило нет.
def _w11(d: list[int], w: list[int]) -> int:
    return sum(a * b for a, b in zip(w, d)) % 11 % 10


def _valid_inn(s: str) -> bool:
    if len(s) not in (10, 12) or s.startswith("00") or len(set(s)) == 1:
        return False
    d = [int(c) for c in s]
    if len(s) == 10:
        return _w11(d, [2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    return (_w11(d, [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10]
            and _w11(d, [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11])


def _valid_ogrn(s: str) -> bool:
    if len(s) not in (13, 15) or s[0] == "0" or len(set(s)) == 1:
        return False
    return int(s[:-1]) % (11 if len(s) == 13 else 13) % 10 == int(s[-1])


def _valid_bik(s: str) -> bool:
    if not re.fullmatch(r"04\d{7}", s):
        return False
    tail = int(s[6:])
    return tail <= 3 or tail >= 50


def _digits_accept(validator: Callable[[str], bool]) -> Callable[[re.Match], bool]:
    return lambda m: validator(m.group(1))


# Публичные государственные и правовые ресурсы — не маскируются (ссылки на
# pravo.gov.ru, kad.arbitr.ru, consultant.ru — часть правового текста).
_PUBLIC_DOMAIN = re.compile(
    r"(?:^|[./])(?:[a-z0-9-]+\.)*(?:gov\.ru|gov|госуслуги\.рф|gosuslugi\.ru|arbitr\.ru|sudrf\.ru|"
    r"vsrf\.ru|ksrf\.ru|consultant\.ru|garant\.ru|cbr\.ru|nalog\.ru|fips\.ru|"
    r"rosminzdrav\.ru|eaeunion\.org|wipo\.int|who\.int|ich\.org|europa\.eu|wikipedia\.org)(?:[/:?#]|$)",
    re.IGNORECASE,
)


def _url_accept(m: re.Match) -> bool:
    value = re.sub(r"^(?i:https?://)", "", m.group(0)).lower()
    host = value.split("/")[0]
    return not _PUBLIC_DOMAIN.search(host + "/")


_AcceptFn = Callable[[re.Match], bool]

# Дата в ссылке на нормативный/правовой акт — часть правовой ссылки, а не данные
# сторон: «Решение Совета ЕЭК от 03.11.2016 № 79», «закон № 61-ФЗ от 12.04.2010»
# (фикс 2026-10-05). Признак: слово акта перед датой (в пределах фразы) и номер
# акта сразу после даты или прямо перед ней («№ 61-ФЗ от <дата>»).
_ACT_WORD_BEFORE = re.compile(
    r"(?i)(?:решени|постановлени|приказ|распоряжени|указ|закон|кодекс|письм|рекомендаци"
    r"|определени|разъяснени|методическ|регламент|правил|директив|регулировани|decision"
    r"|resolution|regulation|directive|law|order)\w*[^.;\n]{0,140}$"
)
_ACT_NUMBER_AFTER = re.compile(r"^\s*(?:г\.|года|y\.)?\s*(?:№|N|No\.?)\s*\d")
_ACT_NUMBER_BEFORE = re.compile(r"(?:№|N|No\.?)\s*[\w\-/]+\s+от\s*[«\"]?$")


_PARTY_DOC_WORD = re.compile(
    r"(?i)(?:договор|соглашени|контракт|протокол|сч[её]т|заказ|\bакт\b|доверенност|"
    r"накладн|спецификаци|agreement|contract|invoice|order\b|protocol)"
)


def _not_act_date(m: re.Match) -> bool:
    before = m.string[max(0, m.start() - 160):m.start()]
    after = m.string[m.end():m.end() + 12]
    act = _ACT_WORD_BEFORE.search(before)
    if act and not _PARTY_DOC_WORD.search(act.group(0)[3:]) and (
            _ACT_NUMBER_AFTER.match(after) or _ACT_NUMBER_BEFORE.search(before)):
        return False
    return True


_MONTHS_EN = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
              r"|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)")

# Тело якорного фрагмента: переходит через ОДИНОЧНЫЙ перенос строки (текст из
# PDF рвётся посреди адреса — фикс 2026-09-30), не через пустую строку и не
# через «[» (плейсхолдеры внутрь оригинала АДРЕС не попадают).
_SPAN_BODY = r"(?:[^\n|;\[]|\n(?![ \t]*\n)){5,400}?"
# Конец фрагмента: пустая строка, следующая строка-метка («OGRN:», «Tel.:»),
# «;», граница столбца таблицы, конец текста. Точка в конце строки — не конец:
# «Sosnovaya st.\nPokrov» — адрес продолжается.
_SPAN_END = r"\s*\n[ \t]*\n|\s*\n(?=[^\n]{0,40}:)|\s*;|\s*\||\s*$"
# Номер договора: с разделителем («15/2026», «77-15-К») или от 3 цифр («1234»).
_CONTRACT_NUMBER_VALUE = (
    r"(\d{1,8}(?:[/\-.]\d{1,8})+(?:-?[А-ЯЁA-Z]{1,3})?|\d{3,25})(?![\w/\-])"
)
# Между договорным словом и «№» стоит публичный акт или дело — номер не договора:
# «по договору … Постановлением Правительства № 1479», «по договору займа по делу
# № 2-1234/2025», «Agreement on … No. 123 of WTO».
# Основы привязаны к границам слов: «договор контрактного производства»,
# «разрешения», «указанного», «законсервированного» — не акты.
_CONTRACT_GAP_PUBLIC = re.compile(
    r"(?i)\bдел(?:о|а|у|е|ам|ах)\b"
    r"|(?:исполнительн|судебн)\w*\s+производств|\bпроизводств(?:о|е|а|у)\s+по\s+делу"
    r"|\bпостановлени|\bприказ(?:а|у|ом|е|ы|ов)?\b|\bуказ(?:а|у|ом|е)?\b"
    r"|\bрешени(?:е|я|ю|ем|и|й)\b|\bраспоряжени|\bзакон(?:а|у|ом|е|ы|ов)?\b"
    r"|\bписьм(?:о|а|у|ом|е)\b|\bопределени|\bфз\b"
    r"|convention|regulation|decision|\blaw\b|\bwto\b",
)
_PATTERNS: list[tuple[str, Pattern[str], str, int, _AcceptFn | None]] = [
    # E-mail
    ("EMAIL",
     # Границы — по символам адреса, не \b: markdown-рендер оставляет «_» вплотную
     # к адресу («name@domain.ru_»), и \b между «u» и «_» не срабатывал — e-mail
     # целиком оставался открытым (реальный договор 2026-09-30).
     re.compile(r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])"),
     "EMAIL", 0, None),
    # E-mail с артефактом OCR: пробел перед/после «@», кириллица в домене
    # («123456789 @qq.com», «x @аа.сот») — реальный скан 2026-10-01.
    ("EMAIL_OCR",
     re.compile(r"(?<![\w.])[A-Za-z0-9._%+\-]{3,}\s@\s?[A-Za-zА-Яа-я0-9.\-]+\.[A-Za-zА-Яа-я]{2,}(?![\w])"),
     "EMAIL", 0, None),
    # Наименование банка по якорю (значение — до пустой строки / следующей метки).
    ("BANK_NAME",
     re.compile(
         r"(?i:\b(?:bank\s+name|beneficiary(?:'s)?\s+bank|name\s+of\s+(?:the\s+)?bank"
         r"|наименование\s+банка|банк\s+получателя)\s*:)"
         rf"\s*({_SPAN_BODY})"
         rf"(?={_SPAN_END})"
     ),
     # значение с «:» — это следующая метка пустого шаблона («Bank name:  Bank Address:»)
     "КОМПАНИЯ", 1, lambda m: "\x00" not in m.group(1) and ":" not in m.group(1)),
    # Регистрационный номер по англ./рус. якорю: «State registration number:
    # 1037700000000», «Registration number: 91320700…X» (китайский USCC).
    ("REG_NUMBER",
     re.compile(
         r"(?i:\b(?:(?:state\s+|company\s+)?registration\s+(?:number|no\.?)|unified\s+social\s+credit\s+code"
         r"|регистрационный\s+номер))[\s:№.]*([A-Z0-9][A-Z0-9\-]{6,24}[A-Z0-9])\b"
     ),
     "РЕГ_НОМЕР", 1, None),
    # Компания: ОПФ внутри кавычек — «АО Пример Групп», "ООО Ромашка".
    ("COMPANY_QUOTED_OPF",
     re.compile(rf"[«\"](?:{_OPF})\s+[^»\"\n]{{2,80}}[»\"]"),
     "КОМПАНИЯ", 0, None),
    # Сайт / URL (фикс 2026-10-01: шаблона не было — адрес сайта контрагента
    # оставался открытым, а «услуги по …» рвал markdown-ссылку пополам).
    ("URL",
     re.compile(r"(?i:\b(?:https?://|www\.))[^\s)\]<>«»\"]+[^\s)\]<>«»\".,;:]"),
     "САЙТ", 0, _url_accept),
    # Голый домен без www/http: «example-apteka.ru», «пример.рф» (2026-10-02).
    ("DOMAIN",
     re.compile(
         r"(?<![\w@./\-\[])(?:[a-zа-яё0-9](?:[a-zа-яё0-9-]{0,61}[a-zа-яё0-9])?\.)+"
         r"(?:ru|com|org|net|su|io|info|biz|pro|online|site|tech|me|uk|de|eu|kz|by|ua|us|cn|uz|рф)"
         r"(?![\w\-])(?:/[^\s<>\"«»)\]]*)?",
         re.IGNORECASE,
     ),
     "САЙТ", 0, _url_accept),
    # Номер документа с буквами/дефисом после «№ / No.»: «№ ДП-400-2023»,
    # «No. F(DP)-31-2026», «Доверенность № ДВ-104». Чисто цифровой номер («ДС № 14»)
    # и номер арбитражного дела («№ А40-12345/2025» — публичный) не трогаем.
    ("DOC_NUMBER",
     re.compile(
         r"(?:№|\bNo\.?|\bN)\s*"
         r"((?=[^\s,;]*[A-Za-zА-ЯЁа-яё])(?=[^\s,;]*[\-/])"
         # публичные реквизиты — не маскировать: дело АС «А40-…/…», СИП, номер
         # определения ВС «307-ЭС21-…», номер НПА «115-ФЗ», «1556-р», «12-П»
         r"(?![АA]\d{1,2}-\d+/\d{2,4}\b|СИП-\d+/\d{2,4}\b"
         r"|\d{1,3}-[А-ЯЁ]{2,3}\d{2}-\d+|\d+-(?:ФЗ|ФКЗ|КЗ|ОЗ|ЗО|П|р|рп|пр|у|н)\b)"
         r"[A-Za-zА-ЯЁа-яё0-9][A-Za-zА-ЯЁа-яё0-9()\-/.]{2,40}[A-Za-zА-ЯЁа-яё0-9)])"
     ),
     "НОМЕР_ДОК", 1, None),
    # Внутренний код разработки препарата («FBGL-010426», «ABC-12345») рядом со словом
    # препарат/ЛП/drug/product — решение юриста 2026-10-06: в образцах скрывать.
    ("DRUG_CODE",
     re.compile(
         r"(?i:препарат\w*|\bЛП\b|лекарственн\w*|\bdrug\b|\bproduct\b|\bcompound\b|кандидат\w*)"
         r"[^.\n]{0,40}?(?<![A-Za-z])([A-Z]{2,6}\s?-\s?\d{4,8})(?!\d)"
     ),
     "КОД_ПРЕПАРАТА", 1, None),
    # ── Адрес целым фрагментом по якорю (фикс 2026-09-30) ────────────────
    # Покомпонентные адресные паттерны ниже не ловят голые города/провинции
    # («Lianyungang, Jiangsu», «Ляньюньган»). В договоре у адреса есть надёжные
    # границы: якорь «address at / Registered address: / адрес места нахождения:»
    # и терминатор «, hereinafter / , именуемое / (далее / перевод строки».
    # Идут сразу после EMAIL — до остальных паттернов, чтобы в оригинал
    # плейсхолдера АДРЕС не попали другие плейсхолдеры (иначе restore вложенный).
    ("ADDRESS_SPAN_EN",
     re.compile(
         r"(?i:\b(?:(?:principal|business|registered|legal|postal|mailing|actual|delivery)\s+)?"
         r"address(?:\s+of\s+(?:the\s+)?(?:registered\s+office|business))?(?:\s+at|\s*:)"
         r"|\b(?:consignee|consignor|shipper)\s*:|\b(?:located|situated)\s+at)"
         rf"\s*({_SPAN_BODY})"
         r"(?=\s*,\s*(?i:hereinafter|herein|which|represented|acting|and\s+having|tel\.|phone|e-?mail|inn\b|ogrn\b)"
         r"|\s+(?i:is|are|shall|will)\b"
         rf"|\s*\((?i:hereinafter|the|each)|{_SPAN_END})"
     ),
     "АДРЕС", 1, lambda m: _address_span_accept(m)),
    ("ADDRESS_SPAN_RU",
     re.compile(
         r"(?i:(?:(?:юридический|почтовый|фактический)\s+)?"
         r"(?:адрес(?:у|а|ом)?(?:\s+места\s+нахождения|\s+местонахождения|\s+регистрации|\s+банка)?"
         r"|место\s+нахождения|местонахождени[еяю]|грузополучатель|грузоотправитель)\s*:)"
         rf"\s*({_SPAN_BODY})"
         r"(?=\s*,?\s*(?i:именуем|далее|в\s+лице|действующ|является|являющ|тел\.|телефон|e-?mail|инн\b|огрн\b|кпп\b)"
         # скобка — конец, только если это «(далее…» / «(hereinafter…»: в скобках бывает
         # продолжение адреса (английская версия того же адреса в двуязычном тексте)
         rf"|\s*\((?i:далее|именуем|hereinafter|the)|{_SPAN_END})"
     ),
     "АДРЕС", 1, lambda m: _address_span_accept(m)),
    # Компания в кавычках с ОПФ: ООО «Ромашка», АО "Вектор-М".
    # Закрывающая кавычка зависит от открывающей — это устраняет ложные
    # обрезания при вложенных кавычках: ООО «Страховая Компания "Север"».
    ("COMPANY",
     re.compile(
         rf"(?:{_OPF})\s+"
         r"(?:«[^»]{2,120}»"       # «guillemets» — вложенные " допустимы
         r"|\"[^\"]{2,120}\""       # "double"
         r"|'[^']{2,120}')",        # 'single'
         re.IGNORECASE,
     ),
     "КОМПАНИЯ", 0, None),
    # Иностранная компания: название + OPF-суффикс (GmbH, LLC, Ltd …).
    # Захватывает 1–4 слова перед суффиксом. Идёт после COMPANY, чтобы
    # русские ОПФ уже были съедены.
    # `,?\s+` (не только `\s+`) перед суффиксом — реальные компании часто
    # пишутся как «Name, LLC» с запятой (баг найден на реальном контракте
    # 2026-07-30: «Example Group, LLC» не распознавалось вовсе).
    ("COMPANY_FOREIGN",
     re.compile(
         rf"[A-ZА-ЯЁ][A-Za-zА-ЯЁа-яё\-]{{1,30}}"
         rf"(?:\s+[A-ZА-ЯЁ][A-Za-zА-ЯЁа-яё\-]{{0,30}}){{0,3}}"
         rf",?\s+(?:{_OPF_FOREIGN})\b",
     ),
     "КОМПАНИЯ", 0, None),
    # ── Подписант по якорю (фикс 2026-09-30) ─────────────────────────────
    # «represented by <должность> <ИМЯ>, acting…» / «в лице <должности> <ИМЯ>,
    # действующего…». Маскируется только имя (группа 1), должность остаётся.
    # Ловит то, что форма-паттерны пропускают: «K. Matveev», китайские имена,
    # имена рядом со стоп-словами.
    ("SIGNATORY_EN",
     re.compile(
         r"(?i:\b(?:represented\s+by|in\s+the\s+person\s+of|signed\s+by"
         r"|attention\s*:|attn\.?\s*:?|contact\s+person\s*:|name\s*:))\s+"
         rf"{_ROLE_EN}"
         r"((?:[A-Z]\.\s?){0,2}[A-Z][A-Za-z'\-]+(?:\s+(?:[A-Z]\.\s?){0,2}[A-Z][A-Za-z'\-]+){0,3})"
         r"(?=\s*,|\s+acting\b|\s+who\b|\s+and\b|\s*\(|\s*\n|\s*$|\s+on\s+the\s+basis|\.(?:\s|$))"
     ),
     "ФИО", 1, lambda m: _signatory_accept(m)),
    ("SIGNATORY_RU",
     re.compile(
         r"\bв\s+лице\s+(?:[А-ЯЁа-яё\-]+\s+){0,8}?"
         r"((?:[А-ЯЁ][а-яё\-']+|[А-ЯЁ]\.\s?(?:[А-ЯЁ]\.)?)"
         r"(?:\s+(?:[А-ЯЁ][а-яё\-']+|[А-ЯЁ]\.\s?(?:[А-ЯЁ]\.)?)){1,3})"
         r"(?=\s*,|\s+действующ|\s*\(|\s*\n|\s*$)"
     ),
     "ФИО", 1, lambda m: _signatory_accept(m)),
    # Наименование стороны в блоке реквизитов: «The Manufacturer: Jiangsu Example
    # Pharmaceuticals» — без ОПФ/кавычек форма-паттерны компании молчат (фикс
    # 2026-09-30). Только метка стороны в начале строки и значение до конца строки;
    # уже замаскированное значение («Покупатель: [КОМПАНИЯ_1]») не трогается.
    ("PARTY_LABEL",
     re.compile(
         r"(?im:^[ \t*]*(?:the\s+)?(?:manufacturer|buyer|supplier|seller|customer|contractor|"
         r"licensor|licensee|consignee|consignor|shipper|производитель|покупатель|поставщик|"
         r"продавец|заказчик|исполнитель|подрядчик|лицензиар|лицензиат)[ \t*]*:[ \t*]*)"
         r"([^\n\[]{3,120}?)[ \t*]*(?=\n|$)"
     ),
     "КОМПАНИЯ", 1, lambda m: bool(re.search(r"[A-Za-zА-ЯЁа-яё]{3,}", m.group(1)))),
    # ── Страна + почтовый индекс рядом со страной (Итерация 4) ───────────
    # Индекс перед названием страны (lookahead — сам не потребляет название
    # страны, чтобы COUNTRY ниже замаскировал его отдельно своим плейсхолдером).
    ("POSTAL_NEAR_COUNTRY",
     re.compile(
         rf"\b\d{{5,6}}\b(?=\s*,?\s*(?:the\s+)?(?:{_COUNTRIES})\b)"
     ),
     "ИНДЕКС", 0, None),
    # Название страны (латиница). Идёт до FIO_LATIN, иначе «Russia»/«China»
    # маскируются как персональное имя, а составные официальные названия
    # («People's Republic of China») дробятся на куски.
    ("COUNTRY",
     re.compile(rf"\b(?:{_COUNTRIES})\b"),
     "СТРАНА", 0, None),
    # Адрес на латинице: «<номер> <Название> Street/Road/...».
    # Идёт до FIO_LATIN — иначе «Chuanda Road» ловится как ФИО.
    ("ADDRESS_STREET_EN",
     re.compile(
         rf"\b\d{{1,6}}\s+[A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+){{0,3}}"
         rf"\s+(?:{_ADDR_STREET_EN})\b"
     ),
     "АДРЕС", 0, None),
    # Адрес на латинице: «<Название> Region/District/...» и «city <Название>».
    # (?i:...) — только маркер регистронезависим («Pokrov village» — маркер
    # часто со строчной буквы), сами Title-Case слова остаются с большой буквы.
    ("ADDRESS_AREA_EN",
     re.compile(
         rf"\b[A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+){{0,3}}\s+(?i:{_ADDR_AREA_EN})\b"
         rf"|\b(?i:city)\s+[A-Z][A-Za-z']+\b"
     ),
     "АДРЕС", 0, None),
    # ИП ФИО
    ("IP_FIO",
     re.compile(
         r"\b(?:ИП|Индивидуальный\s+предприниматель)\s+"
         r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s?[А-ЯЁ]\."
         r"|\b(?:ИП|Индивидуальный\s+предприниматель)\s+"
         r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+",
         re.IGNORECASE,
     ),
     "ИП_ФИО", 0, None),
    # ── ФИО (Итерация 1 + 2) ─────────────────────────────────────────────
    # accept=_fio_accept — фильтр стоп-слов (B1, B2): пропускает матчи с
    # юридическим контекстом («Гражданский Кодекс Российской», «Договору И.О.»).
    # Поддержка (Итерация 2):
    #   A7 — двойные/тройные фамилии через дефис (Салтыков-Щедрин, Семёнов-Тян-Шанский)
    #   A8 — дефисное имя (Жан-Пьер)
    #   A9 — национальные постфиксы (оглы, кызы, ибн, бин, бен)
    #   A4 — инициалы перед фамилией (И.И. Иванов, А.С. Пушкин)
    #   A5 — опциональная последняя точка («Иванов И.И» без точки)
    # CAPS-вариант («ИВАНОВ И.И.») вынесен в отдельный паттерн FIO_CAPS,
    # чтобы не включать re.IGNORECASE для всей FIO-ветки (иначе строчные
    # тройки слов начнут давать ложные срабатывания).
    ("FIO",
     re.compile(
         # 1. Три «длинных» слова (3+ символа) + нац. постфикс.
         #    Апостроф (О'Брайен) и em-dash (Иванов—Петров) поддерживаются через _WL_RU.
         rf"\b(?:{_WL_RU})\s+(?:{_WL_RU})\s+(?:{_WL_RU}){_SUF_RU}\b"
         # 2. «Длинная» фамилия + два инициала (последняя точка опциональна). [A5]
         rf"|\b(?:{_WL_RU})\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.?(?!\w)"
         # 3. Два инициала + «длинная» фамилия. [A4]
         rf"|\b[А-ЯЁ]\.\s?[А-ЯЁ]\.\s+(?:{_WL_RU})\b"
         # 4. «Длинная» фамилия + один инициал (Дёмин С., Петров А.). [новое]
         rf"|\b(?:{_WL_RU})\s+[А-ЯЁ]\.(?!\w)"
         # 5. Три «средних» слова (2+ символа) + нац. постфикс. [A6]
         #    Покрывает короткие восточные имена: Ким Чен Ын, Ли Чен Цзинь.
         rf"|\b(?:{_WM_RU})\s+(?:{_WM_RU})\s+(?:{_WM_RU}){_SUF_RU}\b"
         # 6. Два «длинных» слова — ФИО без отчества. [A3]
         #    Иван Иванов, Сидоров Пётр. Стоп-лист блокирует юр. контекст.
         rf"|\b(?:{_WL_RU})\s+(?:{_WL_RU})\b"
     ),
     "ФИО", 0, _fio_ru_accept),
    # CAPS-формы: «ИВАНОВ И.И.» и «ИВАНОВ ИВАН ИВАНОВИЧ» в шапках, штампах, подписных блоках.
    # Без IGNORECASE на основном FIO, чтобы не ловить строчные тройки.
    ("FIO_CAPS",
     re.compile(
         # 1. ФАМИЛИЯ И.О.
         r"\b[А-ЯЁ]{3,}(?:[-—][А-ЯЁ]+)*\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.?(?!\w)"
         # 2. ТРИ СЛОВА КАПСЛОКОМ — полное ФИО в реестрах, ЭДО, сертификатах
         r"|\b[А-ЯЁ]{3,}(?:[-—][А-ЯЁ]+)*\s+[А-ЯЁ]{3,}(?:[-—][А-ЯЁ]+)*\s+[А-ЯЁ]{3,}(?:[-—][А-ЯЁ]+)*\b"
     ),
     "ФИО", 0, _fio_ru_accept),
    # ── ФИО на латинице (Итерация 3) ─────────────────────────────────────
    # Покрывает: John Smith, Jean-Pierre Dupont, Ivan Petrov,
    #            Jean-Pierre Martin Leblanc (3 компонента),
    #            Anton A. Tikhonov (средний инициал — фикс от 2026-07-30,
    #            баг найден на реальном контракте: имя подписанта осталось
    #            в открытом виде, потому что старый паттерн требовал ровно
    #            2-3 ПОЛНЫХ слова без инициалов).
    # Фильтр _fio_latin_accept отклоняет: LLC/GmbH/Inc, служебные слова, месяцы,
    # структурные слова документа (Article/Section/Exhibit и т. п.).
    ("FIO_LATIN",
     re.compile(
         r"\b[A-Z][a-z]{1,}(?:-[A-Z][a-z]+)?"
         r"\s+[A-Z][a-z]{1,}(?:-[A-Z][a-z]+)?"
         r"(?:\s+[A-Z][a-z]{1,}(?:-[A-Z][a-z]+)?)?\b"
         # FirstName M. LastName / FirstName M.M. LastName (1-2 инициала)
         r"|\b[A-Z][a-z]{1,}(?:-[A-Z][a-z]+)?"
         r"\s+(?:[A-Z]\.\s?){1,2}"
         r"[A-Z][a-z]{1,}(?:-[A-Z][a-z]+)?\b"
         # I. Surname / I.I. Surname (фикс 2026-09-30: «K. Matveev» — открыт).
         # «Exhibit B. Pricing» отсекает проверка предшествующего слова в accept.
         r"|\b(?:[A-Z]\.\s?){1,2}[A-Z][a-z]{2,}(?:-[A-Z][a-z]+)?\b"
         # Mr./Ms./Dr. Surname — обращение само по себе признак имени
         r"|\b(?:Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b"
     ),
     "ФИО", 0, _fio_latin_named_accept),
    # ── Коммерческие данные ───────────────────────────────────────────
    # Тема услуги: «услуги по X» — маскирует X до ближайшей запятой/точки/переноса.
    # Минимум 10 символов отсекает «услуги по договору», «услуги по акту» и т.п.
    ("SERVICE_TOPIC",
     re.compile(
         r"(?:услуг[аи]?\s+по|оказани[еяю]\s+услуг\s+по"
         r"|предоставлени[еяю]\s+(?:услуг|сервис[аов])\s+по)"
         r"\s+"
         r"([^,\n.;]{10,300})",
         re.IGNORECASE,
     ),
     "ТЕМА_УСЛУГИ", 1, None),
    # Описание товара/услуги: якорь сохраняется, содержимое маскируется.
    # Многострочный захват (до пустой строки): (?:[^\n]|\n(?!\n))+
    # «а именно:» — якорь для таблиц в договорах об услугах.
    ("PRODUCT_DESC",
     re.compile(
         r"(Наименование\s+(?:товара|услуг[аи]?|продукции|работ)"
         r"|Предмет\s+договора"
         r"|Описание\s+(?:товара|услуг[аи]?|продукции|работ)"
         r"|Ассортимент"
         r"|Спецификация"
         r"|Товар(?:\s+и\s+его\s+характеристики)?"
         r"|Услуг[аи]"
         r"|Продукция"
         r"|Артикул"
         r"|Товарный\s+знак"
         r"|а\s+именно"
         r"|Предмет\s+обращения)"
         r"\s*[:–-]\s*"
         r"((?:[^\n]|\n(?!\n)){3,2000})",
         re.IGNORECASE,
     ),
     "ОПИСАНИЕ", 2, None),
    # Срок оплаты — раньше DATE/PRICE, чтобы забрать более длинный матч.
    ("PAYMENT_TERM",
     re.compile(
         r"(?:оплата|оплатить|оплачивает(?:ся)?|платёж|платеж|перечисляет(?:ся)?)"
         r"[^\n.]{0,60}?"
         r"(?:в\s+течение\s+\d{1,4}\s+(?:календарных\s+|рабочих\s+|банковских\s+)?(?:дней|дня|дн\.|суток)"
         r"|не\s+позднее\s+\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}"
         r"|не\s+позднее\s+«?\d{1,2}»?\s+[а-яё]+\s+\d{4}"
         r"|до\s+«?\d{1,2}»?\s+[а-яё]+\s+\d{4}"
         r"|до\s+\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
         re.IGNORECASE,
     ),
     "СРОК_ОПЛАТЫ", 0, None),
    # Название клинического исследования: якорь + текст в кавычках «…».
    # [^«]{0,60} — допускает перенос строки между якорем и открывающей кавычкой.
    ("PROTOCOL_NAME",
     re.compile(
         r"(?:протокол(?:а|у|ом|е)?\s+исследовани[яею]"
         r"|клинического\s+исследовани[яею]"
         r"|название\s+исследовани[яею])"
         r"[^«]{0,60}"
         r"«(?:[^»]|\n){5,1000}»",
         re.IGNORECASE,
     ),
     "ПРОТОКОЛ", 0, None),
    # Цена / сумма с валютой. Опциональный скобочный текст между числом и валютой.
    ("PRICE",
     re.compile(
         r"\b\d{1,3}(?:[\s ]\d{3})*(?:[.,]\d{1,2})?"
         r"(?:\s*\([^)]{0,100}\))?\s?"
         # CNY/юань, GBP, CHF и др. — фикс 2026-10-05 (цена в юанях оставалась открытой)
         # «\$» — знак доллара; голый «$» означал «конец текста» и делал суммой любое
         # число в конце документа («Дополнительное соглашение № 14»), фикс 2026-10-08
         r"(?:руб(?:\.|лей|ля)?|₽|RUB|USD|\$|EUR|€|долл\.?(?:\s*США)?|евро|копеек|коп\.?"
         r"|CNY|RMB|юан(?:ь|я|ей|ям|ями)?|GBP|£|фунт(?:ов|а)?(?:\s+стерлингов)?|CHF|франк(?:ов|а)?"
         r"|JPY|¥|иен|KZT|тенге|AED|дирхам(?:ов|а)?|р\.(?=[\s,;)|]|$))",
         re.IGNORECASE,
     ),
     "СУММА", 0, None),
    # Число с суммой прописью в скобках — цена при любой валюте (в т. ч. OCR-искажённой:
    # «129.17 (one hundred twenty nine and 17/100) СМУ»), фикс 2026-10-05.
    ("PRICE_WORDS",
     re.compile(
         # «**» между числом и скобкой — жирная разметка Word→md (фикс 2026-10-05)
         r"\b\d{1,3}(?:[\s\u00a0,]\d{3})*(?:[.,]\d{1,2})?(?:\*\*)?\s*"
         r"\((?=[^)]*(?:\d{1,2}/100|hundred|thousand|million|сот|тысяч|миллион|рубл|копе))[^)\d]{0,120}(?:\d{1,2}/100)?[^)]{0,20}\)"
     ),
     "СУММА", 0, None),
    # Валюта перед числом: «USD 1,200.50», «CHF 1,200», «£500».
    ("PRICE_PREFIX",
     re.compile(r"(?:USD|EUR|GBP|CHF|CNY|RMB|JPY|AED|RUB|\$|€|£|¥)\s?\d{1,3}(?:[,\s ]\d{3})*(?:\.\d{1,2})?(?!\d)"),
     "СУММА", 0, None),
    # Сумма с множителем (тыс./млн./млрд.) отдельно — сначала число, потом масштаб, потом валюта
    ("PRICE_SCALED",
     re.compile(
         r"\b\d+(?:[.,]\d+)?\s?(?:тыс|млн|млрд)\.?\s?(?:руб(?:\.|лей)?|₽|USD|EUR|€|долл\.?|евро)",
         re.IGNORECASE,
     ),
     "СУММА", 0, None),
    # НДС
    ("VAT",
     re.compile(
         r"НДС[^.\n]{0,30}?\d{1,2}(?:[.,]\d{1,2})?\s?%"
         r"|без\s+НДС"
         r"|НДС\s+не\s+облагается",
         re.IGNORECASE,
     ),
     "НДС", 0, None),
    # Процент (наценка, скидка, штраф)
    ("PERCENT",
     re.compile(
         r"(?:скидк[аи]|наценк[аи]|неустойк[аи]|штраф[а-я]*|пен[яи])"
         r"[^\n.]{0,40}?\d{1,3}(?:[.,]\d+)?\s?%",
         re.IGNORECASE,
     ),
     "ПРОЦЕНТ", 0, None),
    # Количество с единицей измерения
    ("QUANTITY",
     re.compile(
         r"\b\d+(?:[\s\u00a0]\d{3})*(?:[.,]\d+)?\s?"
         r"(?:шт\.?|штук[аи]?|кг|кг\.|гр\.?|тонн[аы]?|т\.|"
         r"упак(?:овок|овки)?\.?|уп\.|коробок|паллет[аы]?|"
         r"литр[аов]?|л\.|мл|м³|м3|м²|м2|метров?|"
         r"ед\.|единиц[аы]?|компл\.|комплектов?|доз[аы]?|ампул[аы]?|флаконов?|таблеток)\b",
         re.IGNORECASE,
     ),
     "КОЛИЧЕСТВО", 0, None),
    # Даты на английском: «14 November 2024», «"17" of September 2026», «March 3, 2025»
    # (фикс 2026-10-05: даты англ. колонки двуязычного договора оставались открытыми).
    ("DATE_TEXT_EN",
     re.compile(
         r"[\"“]?\b\d{1,2}(?:st|nd|rd|th)?[\"”]?\s+(?:of\s+)?" + _MONTHS_EN + r"\s*,?\s+\d{4}\b"
         r"|\b" + _MONTHS_EN + r"\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s+\d{4}\b"
     ),
     "ДАТА", 0, _not_act_date),
    # Дата рождения — ПДн: отдельный тип, чтобы маскировалась и в профиле без дат
    # (analytic, перепроверка образцов) — 2026-10-05.
    ("BIRTHDATE",
     re.compile(
         r"(?i:дат[аы]\s+рождения|д\.\s?р\.|date\s+of\s+birth|DOB)\s*[:\-–]?\s*"
         r"(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}|\d{1,2}\s+[а-яё]+\s+\d{4})"
         r"|(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4}|\d{1,2}\s+[а-яё]+\s+\d{4})\s*(?:г\.?\s?р\.|года\s+рождения)"
     ),
     "ДАТА_РОЖДЕНИЯ", 0, None),
    # Даты DD.MM.YYYY / DD-MM-YYYY / DD/MM/YYYY
    ("DATE_NUM",
     # (?!\d), не \b: «01.03.2026г.» — «г» вплотную к году (фикс 2026-10-02)
     re.compile(r"\b\d{1,2}[.\-/]\d{1,2}[.\-/](?:\d{4}|\d{2})(?!\d)"),
     "ДАТА", 0, _not_act_date),
    # Даты «15 января 2025 г.»
    ("DATE_TEXT",
     re.compile(
         r"[«\"]?\d{1,2}[»\"]?\s+(?:январ[ея]|феврал[ея]|март[а]?|апрел[ея]|ма[яй]|"
         r"июн[ея]|июл[ея]|август[а]?|сентябр[ея]|октябр[ея]|ноябр[ея]|декабр[ея])"
         r"\s+\d{4}\s*(?:г\.|года)?",
         re.IGNORECASE,
     ),
     "ДАТА", 0, _not_act_date),
    # ── Числовые реквизиты с обязательным контекстным якорем (фикс A10) ──
    # До фикса любое 10-значное число маскировалось как «паспорт», 13-значное —
    # как «ОГРН» (под раздачу попадали номера договоров, EAN, IMEI, SKU).
    # Теперь маскируем только при наличии явного префикса-якоря.
    # Реквизиты в шапке/таблице без префикса не маскируются — их должен
    # отдавать NER (Этап 5 в roadmap). Organization whitelist не задет —
    # он обрабатывается раньше через _protect_whitelist.
    # ОГРНИП (15 цифр) идёт раньше ОГРН (13 цифр), чтобы не пересекаться;
    # ИНН ФЛ (12 цифр) раньше ИНН ЮЛ (10 цифр) по той же причине.
    ("PASSPORT",
     re.compile(
         r"(?:паспорт(?:а|у|ом|е)?|серия\s+и\s+номер)[\s:№]*"
         r"(\d{2}\s?\d{2}\s?\d{6})(?!\d)",
         re.IGNORECASE,
     ),
     "ПАСПОРТ", 1, None),
    # СНИЛС: XXX-XXX-XXX XX (11 цифр, разделители опциональны)
    ("SNILS",
     re.compile(
         r"(?:СНИЛС|страховой\s+номер(?:\s+ИЛС)?)"
         r"[\s:№]*(\d{3}[-\s]?\d{3}[-\s]?\d{3}[-\s]?\d{2})(?!\d)",
         re.IGNORECASE,
     ),
     "СНИЛС", 1, None),
    # Водительское удостоверение: «77 АА 123456» (серия = регион + 2 буквы)
    ("DL",
     re.compile(
         r"(?:водительск(?:ое|ого|ому)\s+удостоверени[ея]|вод\.?\s*уд\.?|в\.у\.?)"
         r"[\s:№]*(\d{2}\s?[А-ЯЁA-Z]{2}\s?\d{6})",
         re.IGNORECASE,
     ),
     "ВОД_УД", 1, None),
    # Госномер автомобиля: А123ВГ 77 / А123ВГ177.
    # Допустимые буквы АВЕКМНОРСТУХ (кириллица, используемая на RU-табличках).
    ("CAR_PLATE",
     re.compile(
         r"\b[АВЕКМНОРСТУХ]\d{3}[АВЕКМНОРСТУХ]{2}[\s]?\d{2,3}\b"
     ),
     "ГОЗНАК", 0, None),
    # Кадастровый номер: 77:01:0001001:123 — формат достаточно уникален без якоря
    ("CADASTRE",
     re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d{1,6}\b"),
     "КАДАСТР", 0, None),
    ("OGRN15",
     re.compile(r"(?:ОГРНИП|OGRNIP)[\s:№.)]*(\d{15})(?!\d)", re.IGNORECASE),
     "ОГРНИП", 1, None),
    ("OGRN13",
     re.compile(r"(?:ОГРН|OGRN|PSRN)[\s:№.)]*(\d{13})(?!\d)", re.IGNORECASE),
     "ОГРН", 1, None),
    # «ИНН/КПП: 5036000000/503601001» и латинские якоря (фикс 2026-09-30:
    # английская колонка двуязычного договора — INN/KPP/OGRN/OKPO/BIC/Account
    # не распознавались, реквизиты оставались открытыми).
    ("INN_KPP",
     re.compile(r"(?:ИНН|INN|TIN)\s*/\s*(?:КПП|KPP)[\s:№.]*(\d{10,12}\s*/\s*\d{9})(?!\d)", re.IGNORECASE),
     "ИНН_КПП", 1, None),
    ("INN12",
     re.compile(r"(?:ИНН\s+ФЛ|ИНН|INN|TIN|ITN)[\s:№.)]*(\d{12})(?!\d)", re.IGNORECASE),
     "ИНН_ФЛ", 1, None),
    ("INN10",
     re.compile(r"(?:ИНН|INN|TIN|ITN)[\s:№.)]*(\d{10})(?!\d)", re.IGNORECASE),
     "ИНН_ЮЛ", 1, None),
    ("KPP",
     re.compile(r"(?:КПП|KPP|RRC|IEC)[\s:№.)]*(\d{9})(?!\d)", re.IGNORECASE),
     "КПП", 1, None),
    ("OKPO",
     re.compile(r"(?:ОКПО|OKPO)[\s:№.)]*(\d{8,10})(?!\d)", re.IGNORECASE),
     "ОКПО", 1, None),
    ("OKTMO",
     re.compile(r"(?:ОКТМО)[\s:№]*(\d{8,11})(?!\d)", re.IGNORECASE),
     "ОКТМО", 1, None),
    ("OKATO",
     re.compile(r"(?:ОКАТО)[\s:№]*(\d{8,11})(?!\d)", re.IGNORECASE),
     "ОКАТО", 1, None),
    ("OKVED",
     re.compile(r"(?:ОКВЭД\d*|вид\s+деятельности)[\s:№]*(\d{2}(?:\.\d{1,2}){0,2})", re.IGNORECASE),
     "ОКВЭД", 1, None),
    ("OKUGU",
     re.compile(r"(?:ОКОГУ)[\s:№]*(\d{7})(?!\d)", re.IGNORECASE),
     "ОКОГУ", 1, None),
    ("ACC20",
     re.compile(
         r"(?:р[/.\s]?с|к[/.\s]?с|сч[её]т[аов]?|"
         r"расч[её]тный\s+сч[её]т|корреспондентский\s+сч[её]т|"
         r"(?:settlement\s+|current\s+|correspondent\s+|beneficiary(?:'s)?\s+)?account(?:\s+(?:no\.?|number|№))?|a/c)[\s:№.]*"
         r"(\d{20})(?!\d)",
         re.IGNORECASE,
     ),
     "СЧЕТ", 1, None),
    # Счёт с латинским якорем, цифры группами через пробел (иностранный банк:
    # «Beneficiary account: 95508 8022 5999 700 173»).
    ("ACC_SPACED",
     re.compile(
         r"(?i:(?:beneficiary(?:'s)?\s+)?(?:bank\s+)?(?:account|acc\.|a/c|сч[её]т|р/с|к/с)"
         r"(?:\s+(?:no\.?|number|№))?(?:\s*\([A-ZА-ЯЁ]{2,4}\))?)"
         r"[\s:№.]*(\d[\d \-]{8,40}\d)(?!\d)"
     ),
     "СЧЕТ", 1, None),
    # БИК
    ("BIK",
     re.compile(r"\b(?:БИК|BIK|RCBIC|BIC)[\s:№.]*0?\d{8,9}\b", re.IGNORECASE),
     "БИК", 0, None),
    # ── IBAN / SWIFT / банковская карта (Итерация 5) ─────────────────────
    # IBAN — идёт ДО LONGNUM: без этого паттерна «DE89370400440532013000»
    # режется на «DE» + [НОМЕР_1_20цифр]. Якорь «IBAN» обязателен для
    # компактной записи; пробельный формат (DE89 3704 …) ловится вторым альтернативом.
    ("IBAN",
     re.compile(
         r"IBAN[\s:]*([A-Z]{2}\d{2}[A-Z0-9]{10,30})"   # компактный: DE89370400440532013000
         r"|IBAN[\s:]*([A-Z]{2}\d{2}(?:[\s\-]\w{4}){3,9})",  # пробельный: DE89 3704 0044 …
         re.IGNORECASE,
     ),
     "IBAN", 0, None),
    # SWIFT/BIC: 8 или 11 символов (4 буквы банка + 2 страны + 2 лок. + 3 отд.)
    ("SWIFT",
     re.compile(
         r"(?:SWIFT|BIC)(?:\s+code)?[\s:]*([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b",
         re.IGNORECASE,
     ),
     "SWIFT", 1, None),
    # Банковская карта — с якорем (любой формат 16 цифр)
    ("CARD",
     re.compile(
         r"(?:(?:номер\s+)?карт[ыаеу]|card(?:\s+(?:number|no))?|pan)"
         r"[\s:№]*(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})(?!\d)",
         re.IGNORECASE,
     ),
     "КАРТА", 1, None),
    # Банковская карта — без якоря, но явные пробелы между 4 группами цифр
    ("CARD_BARE",
     re.compile(r"(?<!\d)(\d{4}[\s]\d{4}[\s]\d{4}[\s]\d{4})(?!\d)"),
     "КАРТА", 1, None),
    # ── Телефоны (Итерация 2: A12) ───────────────────────────────────────
    # Российский формат: префикс +7 / 7 (без +) / 8, опциональные точки в
    # разделителях. Покрывает CRM-выгрузки (79001234567), формат с точками
    # (+7.900.123.45.67) и канонический +7 (495) XXX-XX-XX.
    # Применяется ПЕРЕД PHONE_INTL: российские номера съедаются здесь и не
    # доходят до международного паттерна.
    ("PHONE",
     re.compile(
         # «+» внутри матча: раньше \b перед «+» не срабатывал, и плюс оставался
         # снаружи метки («+[ТЕЛЕФОН_1]»), фикс 2026-10-08
         r"(?:(?<!\+)\+7|\b[78])[\s\-.()]*\d{3}[\s\-.()]*\d{3}[\s\-.()]*\d{2}[\s\-.()]*\d{2}\b"
     ),
     "ТЕЛЕФОН", 0, None),
    # Международный E.164: обязательный префикс «+» с кодом страны (1-3 цифры),
    # дальше 7-15 цифр с любыми разделителями. Якорь — сам «+», поэтому ложных
    # срабатываний на длинных числах меньше. Российские (+7) уже съедены выше.
    # Фикс 2026-09-30: разделитель после кода страны необязателен —
    # «+8620-8306 4568» (Китай, код 86 + код города слитно) оставался открытым.
    ("PHONE_INTL",
     re.compile(
         r"\+\d{1,4}[\s\-.()]*\d[\d\s\-.()]{6,16}\d"
     ),
     "ТЕЛЕФОН", 0, None),
    # Телефон без кода страны рядом со словом «тел./tel./phone/факс»:
    # «Тел./факс: (495) 665-0000, 571-0000» (фикс 2026-09-30).
    ("PHONE_ANCHORED",
     re.compile(
         r"(?<![A-Za-zА-ЯЁа-яё])(?i:(?:тел(?:ефон)?|tel|phone|fax|факс)\.?"
         r"(?:\s*/\s*(?:факс|fax)\.?)?\s*[:№]?\s*)"
         r"(\(?\d[\d\s\-()]{5,18}\d(?:\s*,\s*\(?\d[\d\s\-()]{5,18}\d)*)"
     ),
     "ТЕЛЕФОН", 1, None),
    # Адрес: индекс + улица/дом
    # Фикс 2026-07-31 (часть 1): было [^.;\n] в промежутке между индексом и
    # маркером улицы — реальный адрес содержит сокращения «г.», «с.», «обл.»
    # с точками ДО маркера («142143, Россия, ..., г. Подольск, с. Покров,
    # ул. ...»), и класс символов, исключающий точку, обрывал совпадение
    # раньше, чем регэксп доходил до «ул.». Промежуток ослаблен до [^;|\n]
    # (без точки в исключениях) — якорь (6 цифр + запятая) уже достаточно
    # специфичен, чтобы не ловить случайные последовательности предложений.
    # Фикс 2026-07-31 (часть 2): и middle-, и tail-часть также исключают «|» —
    # промежуточное md-представление конвейера это таблицы «ячейка | ячейка»,
    # и без этого исключения хвост {0,80} без точек внутри «(далее –
    # «Клиент»), |» перепрыгивал через границу столбца в СЛЕДУЮЩУЮ ячейку
    # таблицы, ломая структуру строки (обнаружено при верификации фикса 1
    # на реальном документе).
    ("ADDRESS_INDEX",
     re.compile(
         # маркеры без учёта регистра: шапка иска капсом «УЛ. ЛЕНИНА, Д. 5» (2026-10-05)
         r"\b\d{6},\s?[^;|\n]{5,200}(?i:ул\.|улица|пр\.|проспект|"
         r"д\.|дом|корп\.|стр\.|оф\.|офис|кв\.|пом\.)[^.;|\n]{0,80}"
     ),
     "АДРЕС", 0, None),
    # Страна на кириллице рядом с индексом (Итерация 5, фикс 2026-07-31):
    # индекс перед страной, не пойманный ADDRESS_INDEX (нет ул./дом маркера —
    # например, адрес контрагента из Китая, записанный кириллицей).
    # Идёт ПОСЛЕ ADDRESS_INDEX: полный русский адрес должен сначала уйти
    # туда целиком, чтобы не терять индекс/страну по отдельности раньше.
    ("POSTAL_NEAR_COUNTRY_RU",
     re.compile(rf"\b\d{{5,6}}\b(?=\s*,?\s*(?:{_COUNTRIES_RU})\b)"),
     "ИНДЕКС", 0, None),
    # Страна на кириллице сама по себе. Реальный баг: «Россия»/«Российской
    # Федерации»/«Китай» в русской колонке билингвального контракта не
    # маскировались вовсе (в отличие от английской колонки, см. COUNTRY выше).
    # Остаточное ограничение — как и для англ. COUNTRY: голое название города
    # («Шанхай») без маркера рядом не покрывается (не гэзетир городов).
    ("COUNTRY_RU",
     re.compile(rf"\b(?:{_COUNTRIES_RU})\b"),
     "СТРАНА", 0, None),
    # Реквизиты без метки — только при валидной контрольной сумме (2026-10-02).
    ("OGRN15_BARE",
     re.compile(r"(?<![\d\[_\-./])(\d{15})(?![\d\]])"),
     "ОГРНИП", 1, _digits_accept(_valid_ogrn)),
    ("OGRN13_BARE",
     re.compile(r"(?<![\d\[_\-./])(\d{13})(?![\d\]])"),
     "ОГРН", 1, _digits_accept(_valid_ogrn)),
    ("INN12_BARE",
     re.compile(r"(?<![\d\[_\-./])(\d{12})(?![\d\]])"),
     "ИНН_ФЛ", 1, _digits_accept(_valid_inn)),
    ("INN10_BARE",
     re.compile(r"(?<![\d\[_\-./])(\d{10})(?![\d\]])"),
     "ИНН_ЮЛ", 1, _digits_accept(_valid_inn)),
    ("BIK_BARE",
     re.compile(r"(?<![\d\[_\-./])(04\d{7})(?![\d\]])"),
     "БИК", 1, _digits_accept(_valid_bik)),
    # Fallback для длинных идентификаторов (16-25 цифр без префикса).
    # Достаточно длинно, чтобы пересечений с EAN-13 (13) и IMEI (15) не было.
    ("LONGNUM",
     re.compile(r"(?<!\d)\d{16,25}(?!\d)"),
     "НОМЕР", 0, None),
    # Номер договора/контракта/соглашения/спецификации/заказа/доверенности из цифр
    # (2026-10-08): «Договор поставки № 15/2026», «по договору от 01.03.2026 № 1234»,
    # «Supply Agreement No. 15/2026». Последним в списке — счета, телефоны и даты
    # уже забраны своими шаблонами (в тексте на их месте метки). Номера НПА и
    # приказов сюда не попадают (нет договорного слова), номера дел («по делу №»)
    # отсекает фильтр; короткий номер без разделителя («ДС № 14») открыт.
    # Замаскированный номер распространяется по документу (_propagate).
    ("CONTRACT_NUMBER",
     re.compile(
         r"(?i:\b(?:договор(?:а|у|ом|е|ы|ов|ам|ами|ах)?|контракт(?:а|у|ом|е|ы|ов)?"
         r"|(?:доп(?:олнительн(?:ое|ого|ому|ым)|\.)\s*)?соглашени(?:е|я|ю|ем|и|й)"
         r"|спецификаци(?:я|и|ю|ей|й)|заказ(?:а|у|ом|е|ы|ов)?|доверенност(?:ь|и|ью|ей))\b"
         r"(?:\s+[А-ЯЁа-яё][А-ЯЁа-яё\-]*){0,8}?"
         r"(?:\s+от\s+(?:\d{1,2}[./]\d{1,2}[./]\d{2,4}|\[ДАТА_\d+\])(?:\s*г\.?)?)?)"
         r"\s*(?:№|N\b\.?)\s*" + _CONTRACT_NUMBER_VALUE
     ),
     "НОМЕР_ДОК", 1, lambda m: not _CONTRACT_GAP_PUBLIC.search(m.group(0))),
    # Английский вариант: «Supply Agreement No. 15/2026», «Purchase Order # 4521».
    # Не больше двух слов между ключевым словом и номером — «Agreement on Trade in
    # Services No. 123» (международный акт) сюда не попадает.
    ("CONTRACT_NUMBER_EN",
     re.compile(
         # «order» — только коммерческий (Purchase/Sales/Work/Change Order):
         # «Executive Order No. 13662», «Court Order No.» — публичные акты.
         r"(?i:\b(?:agreement|contract|specification|(?:purchase|sales|work|change)\s+order)\b"
         r"(?:\s+[A-Za-z][A-Za-z\-]*){0,2}?"
         r"(?:\s+dated\s+(?:\d{1,2}[./]\d{1,2}[./]\d{2,4}|\[ДАТА_\d+\]))?)"
         r"\s*(?:\b[Nn]o\.?|№|#)\s*" + _CONTRACT_NUMBER_VALUE
     ),
     "НОМЕР_ДОК", 1, lambda m: not _CONTRACT_GAP_PUBLIC.search(m.group(0))),
]


# Распространение по документу: из каких плейсхолдеров брать слова и какие
# общие слова адресов/названий не распространять.
_PROPAGATE_LABELS: frozenset[str] = frozenset({"АДРЕС", "ФИО", "КОМПАНИЯ"})
_PROPAGATE_SKIP: frozenset[str] = frozenset({
    "economic", "technological", "development", "road", "street", "avenue", "lane",
    "section", "center", "centre", "building", "floor", "room", "suite", "office",
    "industrial", "park", "zone", "village", "district", "province", "region", "city",
    "pharmaceutical", "pharmaceuticals", "pharma", "trading", "group", "holding",
    "limited", "company", "branch", "moscow", "russia", "china",
    "москва", "москвы", "московская", "московской", "область", "области", "район",
    "района", "улица", "проспект", "город", "фарм", "фармасьютикал", "компания",
    "общество", "ответственностью", "ограниченной", "зона", "развития", "экономического",
    "технологического", "помещение",
    # Общие слова названий организаций (2026-10-05: «Национальный институт…» →
    # «Резолюцией Национального совета» маскировалось распространением).
    "национальный", "национального", "национальная", "национальной", "институт",
    "института", "центр", "центра", "научный", "научного", "исследовательский",
    "медицинский", "медицинского", "фармацевтический", "здравоохранения", "качества",
    "федеральный", "федерального", "российский", "российского", "международный",
    "biologics", "biotech", "medical", "national", "institute", "research", "swift",
})
_COUNTRY_TOKEN = re.compile(rf"(?:{_COUNTRIES}|{_COUNTRIES_RU})", re.IGNORECASE)


# Падежные окончания для распространения кириллических слов: фамилия «Петров» →
# «Петрова/Петрову/Петровым», название «Ромашка» → «Ромашки/Ромашке» (2026-10-02).
_RU_INFL_ENDINGS = ("ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими", "ой", "ей", "ою",
                    "ый", "ий", "ая", "яя", "ую", "юю", "ым", "им", "ом", "ем", "ах", "ях",
                    "ам", "ям", "а", "я", "у", "ю", "е", "ы", "и")
_RU_INFL_GROUP = "(?:" + "|".join(_RU_INFL_ENDINGS) + ")?"
_RU_INFL_ENDINGS_LONGEST_FIRST = tuple(sorted(_RU_INFL_ENDINGS, key=len, reverse=True))
_FIO_KEY_TOKEN = re.compile(r"[A-Za-zА-ЯЁа-яё]+")


def _fio_key(name: str) -> str | None:
    """Падежно-независимый ключ ФИО: «Иванову Ивану Петровичу», «Ивановым Иваном
    Петровичем», «Иванов Иван Петрович» → «иванов иван петрович». Морфологии в
    системе нет: отсекается падежное окончание (основа ≥ 3 букв), затем мягкий
    хвост «й/ь/и/е» («Сергей/Сергею», «Игорь/Игорю», «Дмитрий/Дмитрию»).

    None — если это не полное ФИО из трёх слов с отчеством не на первом месте:
    без отчества отсечение окончаний стирает пол («Сидоров Валентин» / «Сидорова
    Валентина», «Иванов И. П.» / «Иванова И. П.»), а неизменяемая фамилия на «-ич»
    («Бабич Александр» / «Бабич Александра») похожа на отчество. Такие формы
    склеиваются только точно — иначе разные люди получили бы одну метку."""
    tokens = _FIO_KEY_TOKEN.findall(name)
    if len(tokens) != 3 or not any(_is_patronymic(t) for t in tokens[1:]):
        return None
    parts = []
    for token in (t.lower().replace("ё", "е") for t in tokens):
        for ending in _RU_INFL_ENDINGS_LONGEST_FIRST:
            if token.endswith(ending) and len(token) - len(ending) >= 3:
                token = token[: -len(ending)]
                break
        if token[-1:] in ("й", "ь", "и", "е") and len(token) > 3:
            token = token[:-1]
        parts.append(token)
    return " ".join(parts)


def _is_nominative_fio(name: str) -> bool:
    """Отчество в именительном падеже («Петрович», «Петровна») не на первом месте:
    первое слово — фамилия, она бывает на «-ич» в любом падеже («Бабич Ирины»)."""
    return any(re.search(r"(?:ич|вна|чна)$", t) for t in _FIO_KEY_TOKEN.findall(name)[1:])


def restore_reverse(mapping: dict[str, str]) -> dict[str, str]:
    """Метка → оригинал для восстановления по словарю «оригинал → метка».
    У метки ФИО бывает несколько падежных форм: берётся форма в именительном
    падеже, если она встречалась, иначе — первая встреченная (порядок словаря
    = порядок встречи; сохраняется при JSON-обходе)."""
    reverse: dict[str, str] = {}
    for original, placeholder in mapping.items():
        current = reverse.get(placeholder)
        if current is None:
            reverse[placeholder] = original
        elif (placeholder.startswith("[ФИО_") and _is_nominative_fio(original)
              and not _is_nominative_fio(current)):
            reverse[placeholder] = original
    return reverse


def _inflected(token: str) -> str:
    """Шаблон слова с падежными окончаниями (для кириллицы), иначе — точное слово."""
    if not re.search(r"[А-ЯЁа-яё]", token):
        return re.escape(token)
    low = token.lower()
    stem = low
    for e in sorted(_RU_INFL_ENDINGS, key=len, reverse=True):
        if low.endswith(e) and len(low) - len(e) >= 4:
            stem = low[: -len(e)]
            break
    return re.escape(stem) + _RU_INFL_GROUP


# Таблица цен: заголовок со словами цены; ячейка — одно число с разрядами (≥ 4 цифр),
# возможно в ** (жирный) и с копейками.
_PRICE_HEADER = re.compile(r"(?i)стоимост|цен[аыу]\b|сумм|руб\.|\bprice\b|amount|\bcost\b|\btotal\b|итого")
_TABLE_AMOUNT_CELL = re.compile(
    r"(\|\s*\**)(\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d{1,2})?|\d{4,}(?:[.,]\d{1,2})?)((?:\s*\\?\*)*\s*(?=\|))"
)


# Блок реквизитов: последний заголовок «Реквизиты / Подписи сторон / Signatures /
# Bank details…»; нет заголовка — блок не выделяется (без угадывания по объёму).
_REQ_HEADING = re.compile(
    r"(?im)^[\W\d_]*(?:(?:раздел|статья|section|article)\s+\d*\.?\s*)?[а-яёa-z,\s]{0,40}?"
    r"(?:реквизиты|подписи\s+сторон|адреса\s+сторон|signatures?\b|bank\s+details|"
    r"details\s+of\s+the\s+parties|addresses\s+and\s+details|in\s+witness\s+whereof)[^\n]{0,120}$"
)
_BLOCK_NUMBER = re.compile(r"(?<![\w\[\]./\-])\d{6,}(?![\w\]])")
_BLOCK_CODE = re.compile(r"(?<![\w\[\]])(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6,20}(?![\w\]])")


def _requisites_start(text: str) -> int | None:
    last = None
    for m in _REQ_HEADING.finditer(text):
        last = m.start()
    return last


# Паттерны имён, к которым применяется фильтр словаря документа.
_DOC_FILTERED: frozenset[str] = frozenset({
    "FIO", "FIO_CAPS", "FIO_LATIN", "SIGNATORY_EN", "SIGNATORY_RU",
})


class Anonymizer:
    """Двусторонний маппинг оригинал ↔ плейсхолдер для одного запроса."""

    def __init__(self, exclude_labels: set[str] | None = None) -> None:
        self._map: dict[str, str] = {}       # original → placeholder
        self._reverse: dict[str, str] = {}   # placeholder → original
        self._counters: dict[str, int] = {}
        self._fio_keys: dict[str, str] = {}  # падежно-независимый ключ ФИО → placeholder
        self._exclude_labels: set[str] = exclude_labels or set()

    # ── Public API ─────────────────────────────────────────────────────
    def anonymize(self, text: str) -> str:
        if not text:
            return text
        # 1. Защищаем whitelist подстановкой временных токенов (чтобы не задеть маскировкой).
        protected, wl_map = self._protect_whitelist(text)

        # 1.5. Опциональный NER-слой (Natasha): маскирует ФИО/организации, которые
        # regex пропускает (имена рядом со стоп-словами, компании без ОПФ). Гейтится
        # ANONYMIZER_NER_ENABLED; при выключенном флаге — no-op. Идёт ДО regex, чтобы
        # numeric-реквизиты затем обработал regex, а имена/орг уже были замаскированы.
        protected = self._apply_ner(protected)

        # 2. Прогоняем паттерны по порядку.
        # Когда accept-фильтр отвергает матч, продвигаемся на 1 символ от
        # его старта (а не на m.end(), как делает re.sub) — иначе следующий
        # валидный матч, перекрывающийся с отвергнутым, теряется. Пример:
        # «Подрядчик Дюпон Жан-Пьер Антуанович» — стоп-слово «подрядчик»
        # отвергает матч «Подрядчик Дюпон Жан-Пьер», но настоящий «Дюпон
        # Жан-Пьер Антуанович» должен быть найден следующим проходом.
        # Фильтр документа для ФИО-паттернов (фикс 2026-09-30): определённые
        # термины договора («Effective Date», «Рабочий День») и слова, которые в
        # тексте встречаются со строчной буквы, — не имена. Контекст строится по
        # исходному тексту до маскировки.
        vocab, def_stems = _doc_context(text)

        def doc_ok(m: re.Match, g: int) -> bool:
            value = m.group(g)
            tokens = re.findall(r"[A-Za-zА-ЯЁа-яё]{3,}", value)
            if not tokens or any(_is_patronymic(t) for t in tokens):
                return True
            # «Material Safety Data Sheet (MSDS)», «European Pharmacopoeia (EP)» —
            # фраза с аббревиатурой в скобках — термин/организация, не человек.
            if re.match(r"(?:\s+[A-ZА-ЯЁ][a-zа-яё]+){0,3}\s*\((?:[A-Z]{2,6}|[А-ЯЁ]{2,6})\)",
                        m.string[m.end(g):m.end(g) + 60]):
                return False
            low = [t.lower() for t in tokens]
            if any(_stem(t) in vocab for t in low):
                return False
            return not any(_stem(t) in def_stems for t in low)

        for name, pattern, label, group_idx, accept in _PATTERNS:
            if label in self._exclude_labels:
                continue
            if name in _DOC_FILTERED:
                accept = (lambda m, base=accept, g=group_idx:
                          (base is None or base(m)) and doc_ok(m, g))
            protected = self._apply_pattern(protected, pattern, label, group_idx, accept)

        # 2.5. Распространение по документу (фикс 2026-10-01): слово, уже
        # замаскированное в адресе/имени/компании («Lianyungang» в адресе по якорю),
        # маскируется и там, где якоря нет (OCR-перемешанные таблицы, повторы).
        if "СУММА" not in self._exclude_labels:
            protected = self._table_amounts(protected)
        protected = self._requisites_block(protected)
        protected = self._propagate(protected, vocab)

        # 3. Возвращаем whitelist-токены обратно.
        for token, original in wl_map.items():
            protected = protected.replace(token, original)

        return protected

    def _propagate(self, text: str, vocab: frozenset[str]) -> str:
        # Суммы: число, уже замаскированное как СУММА, маскируется и там, где рядом
        # нет валюты (формула расчёта, повтор в таблице) — фикс 2026-10-05.
        if "СУММА" not in self._exclude_labels:
            nums: set[str] = set()
            for original, placeholder in list(self._map.items()):
                if placeholder.startswith("[СУММА_"):
                    for n in re.findall(r"\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d{1,2})?|\d{6,}(?:[.,]\d{1,2})?", original):
                        if sum(c.isdigit() for c in n) >= 6:
                            nums.add(n)
            for n in sorted(nums, key=len, reverse=True):
                pat = re.compile(r"(?<![\d\[])" + re.escape(n).replace("\\ ", "[ \u00a0]") + r"(?![\d\]])")
                text = pat.sub(lambda m: self._replace(m.group(0), "СУММА"), text)
        # Код препарата — везде в документе, в т. ч. с префиксом («LFBGL-010426»).
        for original, placeholder in list(self._map.items()):
            if placeholder.startswith("[КОД_ПРЕПАРАТА_"):
                m = re.match(r"([A-Z]{2,6})\s?-\s?(\d{4,8})$", original)
                if m:
                    pat = re.compile(r"(?<![A-Za-z0-9\[])[A-Z]{0,3}" + m.group(1) + r"\s?-\s?" + m.group(2) + r"(?!\d)")
                    text = pat.sub(lambda mm: self._replace(mm.group(0), "КОД_ПРЕПАРАТА"), text)
        # Номер договора/документа — везде в документе (фикс 2026-10-08): иначе
        # заголовок капсом «ДОГОВОР ПОСТАВКИ № 15/2026» оставался открытым рядом с
        # «договор поставки № [НОМЕР_ДОК_1]» и выдавал, что прячет метка.
        # Свободно — только «узнаваемый» номер: от 6 цифр или с разделителем от 5
        # знаков («15/2026»). Короткий («№ 4521», «№ 2-15») — только сразу после
        # знака номера и не у публичного акта: иначе метка накрыла бы «125 дней»,
        # «ст. 125», «пункты 2-15», «Приказу № 152».
        for original, placeholder in list(self._map.items()):
            if not placeholder.startswith("[НОМЕР_ДОК_") or len(original) < 3:
                continue
            body = re.escape(original) + r"(?![\w\]/\-])"
            distinctive = len(original) >= (6 if original.isdigit() else 5)
            if distinctive:
                pat = re.compile(r"(?<![\w\[/\-])" + body)
                text = pat.sub(lambda mm: self._replace(mm.group(0), "НОМЕР_ДОК"), text)
                continue
            pat = re.compile(r"((?:№|\bNo\.?|\bN\b\.?|#)\s*)" + body)

            def anchored(mm: re.Match, ph: str = placeholder) -> str:
                before = mm.string[max(0, mm.start() - 40): mm.start()]
                if _CONTRACT_GAP_PUBLIC.search(before):
                    return mm.group(0)
                return mm.group(1) + ph

            text = pat.sub(anchored, text)
        cands: dict[str, str] = {}
        for original, placeholder in list(self._map.items()):
            label = placeholder[1:].split("_")[0]
            if label not in _PROPAGATE_LABELS:
                continue
            for tok in re.findall(r"(?<![\w])[A-ZА-ЯЁ][A-Za-zА-ЯЁа-яё'\-]{4,}", original):
                low = tok.lower()
                if (low in _FIO_STOPWORDS or low in _FIO_LATIN_STOPWORDS
                        or low in _PROPAGATE_SKIP or _stem(low) in vocab
                        or _COUNTRY_TOKEN.fullmatch(tok)):
                    continue
                cands.setdefault(tok, label)
        for tok, label in sorted(cands.items(), key=lambda x: -len(x[0])):
            pat = re.compile(r"(?<![\w\[])" + _inflected(tok) + r"(?![\w\]])", re.IGNORECASE)
            text = pat.sub(lambda m, lb=label: self._replace(m.group(0), lb), text)
        return text

    def _table_amounts(self, text: str) -> str:
        """Сумма в markdown-таблице без валюты в ячейке (валюта — в заголовке столбца:
        «Стоимость этапа (руб.)»), фикс 2026-10-05. Маскируются ячейки из одного числа
        с разрядами только в таблицах, где заголовок говорит о цене/стоимости/сумме."""
        out: list[str] = []
        price_table = False
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped.startswith("|"):
                price_table = False
                out.append(line)
                continue
            if not price_table and _PRICE_HEADER.search(stripped) and "---" not in stripped:
                price_table = True
                out.append(line)
                continue
            if price_table:
                line = _TABLE_AMOUNT_CELL.sub(
                    lambda m: m.group(1) + self._replace(m.group(2), "СУММА") + m.group(3), line)
            out.append(line)
        return "\n".join(out)

    def _requisites_block(self, text: str) -> str:
        """Жёсткий режим в блоке реквизитов (2026-10-02): оторванные от меток коды
        и номера (OCR-страница подписей, таблица реквизитов) — маскируются целиком."""
        start = _requisites_start(text)
        if start is None:
            return text
        head, block = text[:start], text[start:]
        block = _BLOCK_NUMBER.sub(lambda m: self._replace(m.group(0), "НОМЕР"), block)
        block = _BLOCK_CODE.sub(lambda m: self._replace(m.group(0), "КОД"), block)
        return head + block

    def deanonymize(self, text: str) -> str:
        if not text or not self._reverse:
            return text
        # Заменяем от более длинных к коротким, чтобы не пересекались.
        for placeholder in sorted(self._reverse, key=len, reverse=True):
            text = text.replace(placeholder, self._reverse[placeholder])
        # Фолбэк: LLM иногда воспроизводит плейсхолдеры без квадратных скобок
        # (КОМПАНИЯ_31 вместо [КОМПАНИЯ_31]). Проверяем голые метки отдельным проходом.
        for placeholder in sorted(self._reverse, key=len, reverse=True):
            bare = placeholder[1:-1]   # [КОМПАНИЯ_31] → КОМПАНИЯ_31
            if bare and bare in text:
                text = text.replace(bare, self._reverse[placeholder])
        return text

    # ── Internals ──────────────────────────────────────────────────────
    def _protect_whitelist(self, text: str) -> tuple[str, dict[str, str]]:
        wl_map: dict[str, str] = {}
        out = text
        for i, value in enumerate(_WHITELIST_SORTED):
            if value in out:
                token = f"\x00WL{i:04d}\x00"
                wl_map[token] = value
                out = out.replace(value, token)
        return out, wl_map

    def _apply_ner(self, text: str) -> str:
        """NER-пред-проход (Natasha). No-op, если флаг выключен или текст длинный.

        Маскирует найденные ФИО/организации литеральной заменой по границам слова
        через общий механизм _replace (плейсхолдеры консистентны, деанонимизация
        работает). Любая ошибка NER не должна ломать анонимизацию — fallback к
        regex-only.
        """
        if not text:
            return text
        import os
        if os.environ.get("PRE_ANON_NER") != "1":
            return text

        try:
            # Длинный текст — по частям на границах абзацев (раньше NER молча
            # отключался на тексте > 40 000 символов, т. е. именно на договорах).
            entities = []
            for chunk in _chunks(text, 20000):
                entities.extend(_natasha_extract(chunk))
        except Exception as exc:
            import logging
            logging.getLogger("pre-anonymize").warning(
                "[NER] extract failed: %s — regex-only", exc
            )
            return text

        # Длинные сущности раньше: «ПАО Сбербанк» заменяем до «Сбербанк».
        for ent_text, label in sorted(set(entities), key=lambda x: len(x[0]), reverse=True):
            if len(ent_text) < 3:
                continue
            pat = re.compile(r"(?<!\w)" + re.escape(ent_text) + r"(?!\w)")
            text = pat.sub(lambda m: self._replace(m.group(0), label), text)
        return text

    def _apply_pattern(
        self,
        text: str,
        pattern: Pattern[str],
        label: str,
        group_idx: int,
        accept: _AcceptFn | None,
    ) -> str:
        out: list[str] = []
        pos = 0
        n = len(text)
        while pos <= n:
            m = pattern.search(text, pos)
            if m is None:
                out.append(text[pos:])
                break
            if accept is not None and not accept(m):
                # Отвергнутый матч: переходим на 1 символ от старта,
                # чтобы не пропустить перекрывающийся валидный матч.
                step = max(m.start() + 1, pos + 1)
                out.append(text[pos:step])
                pos = step
                continue
            out.append(text[pos:m.start()])
            if group_idx == 0:
                out.append(self._replace(m.group(0), label))
            else:
                out.append(self._replace_group(m, group_idx, label))
            pos = m.end()
            if m.end() == m.start():
                pos += 1  # защита от пустого матча
        return "".join(out)

    def _replace_group(self, match: re.Match, group_idx: int, label: str) -> str:
        """Заменить только указанную группу, сохранив остальной матч (якоря типа «Наименование товара:»)."""
        full = match.group(0)
        captured = match.group(group_idx)
        if captured is None:
            return full
        start = match.start(group_idx) - match.start(0)
        end = match.end(group_idx) - match.start(0)
        placeholder = self._replace(captured, label)
        return full[:start] + placeholder + full[end:]

    # Метки, для которых важна длина цифр (реквизиты) — вшиваем суффикс для проверки формата.
    _DIGIT_LEN_LABELS = {
        "ИНН_ЮЛ", "ИНН_ФЛ", "КПП", "ОГРН", "ОГРНИП",
        "СЧЕТ", "БИК", "ПАСПОРТ", "НОМЕР",
    }

    def _replace(self, original: str, label: str) -> str:
        if original in self._map:
            return self._map[original]
        # Одно лицо в разных падежах — одна метка («Иванова Ивана Петровича» и
        # «Иванову Ивану Петровичу» → [ФИО_1]); для восстановления хранится форма
        # в именительном падеже, если она встречалась, иначе первая (фикс 2026-10-08).
        if label == "ФИО":
            key = _fio_key(original)
            known = self._fio_keys.get(key) if key else None
            if known is not None:
                self._map[original] = known
                if _is_nominative_fio(original) and not _is_nominative_fio(self._reverse[known]):
                    self._reverse[known] = original
                return known
        self._counters[label] = self._counters.get(label, 0) + 1
        idx = self._counters[label]
        suffix = ""
        if label in self._DIGIT_LEN_LABELS:
            digits = sum(ch.isdigit() for ch in original)
            if digits >= 6:
                suffix = f"_{digits}цифр"
        placeholder = f"[{label}_{idx}{suffix}]"
        self._map[original] = placeholder
        self._reverse[placeholder] = original
        if label == "ФИО":
            key = _fio_key(original)
            if key:
                self._fio_keys.setdefault(key, placeholder)
        return placeholder

    def stats(self) -> dict[str, int]:
        """Возвращает количество замен по типу ПДн без раскрытия значений.

        Пример: {"ФИО": 3, "ТЕЛЕФОН": 1, "ИНН_ЮЛ": 1}
        Используется для структурированного аудит-лога в main.py (фикс C3).
        """
        return dict(self._counters)

    # ── Общий словарь проекта ──────────────────────────────────────────
    STATE_VERSION = 1

    def export_state(self) -> dict:
        """Словарь и счётчики — чтобы следующий документ проекта получил те же метки."""
        return {"version": self.STATE_VERSION, "map": dict(self._map),
                "counters": dict(self._counters)}

    @classmethod
    def from_state(cls, state: dict | None,
                   exclude_labels: set[str] | None = None) -> "Anonymizer":
        engine = cls(exclude_labels=exclude_labels)
        if not state:
            return engine
        if state.get("version") != cls.STATE_VERSION:
            raise ValueError(f"неподдерживаемая версия словаря: {state.get('version')}")
        engine._map = dict(state.get("map") or {})
        # У метки ФИО может быть несколько падежных форм (см. restore_reverse).
        engine._reverse = restore_reverse(engine._map)
        for orig, ph in engine._map.items():
            key = _fio_key(orig) if ph.startswith("[ФИО_") else None
            if key:
                engine._fio_keys.setdefault(key, ph)
        engine._counters = {k: int(v) for k, v in (state.get("counters") or {}).items()}
        return engine

    # ── Debug ──────────────────────────────────────────────────────────
    def mapping(self) -> dict[str, str]:
        return dict(self._map)


def _natasha_extract(text: str) -> list[tuple[str, str]]:
    """Инлайн-извлечение PER/ORG через natasha (если установлена)."""
    from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter
    global _NATASHA
    if "_NATASHA" not in globals() or _NATASHA is None:
        emb = NewsEmbedding()
        _NATASHA = (Segmenter(), NewsNERTagger(emb))
    segmenter, tagger = _NATASHA
    doc = Doc(text)
    doc.segment(segmenter)
    doc.tag_ner(tagger)
    # LOC не маскируется (адреса ловят паттерны; иначе портятся ссылки «ГК РФ»,
    # города судов); госорганы/суды/регуляторы — публичные, не контрагент.
    out: list[tuple[str, str]] = []
    for span in doc.spans:
        if span.type == "PER":
            out.append((span.text, "ФИО"))
        elif span.type == "ORG" and not _is_public_org(span.text):
            out.append((span.text, "КОМПАНИЯ"))
    return out


def _chunks(text: str, size: int) -> list[str]:
    """Нарезка текста на части ≤ size по границам абзацев."""
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) + 2 > size:
            parts.append(buf)
            buf = ""
        buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        parts.append(buf)
    return parts


# Фильтр публичных организаций для NER (перенесён из legal-assistant-v4
# backend/ner_tagger.py): госорган/суд/регулятор/кодекс — не маскируем.
_PUBLIC_ORG_WORDS: frozenset[str] = frozenset({
    "суд", "министерство", "ведомство", "прокуратура", "правительство",
    "администрация", "дума", "парламент", "кодекс", "конституция", "госуслуги",
    "росздравнадзор", "роспотребнадзор", "роскомнадзор", "рособрнадзор",
    "роспатент", "ростехнадзор", "росреестр", "роструд", "росстат",
    "фас", "фнс", "фсс", "пфр", "сфр", "фссп", "мвд", "фсб", "мчс", "цик",
})
_PUBLIC_ORG_PHRASES: tuple[str, ...] = (
    "банк россии", "центральный банк", "совет федерации",
    "федеральная служба", "федеральное агентство", "верховный суд",
    "конституционный суд", "арбитражный суд", "пенсионный фонд",
    "социальный фонд", "счётная палата", "счетная палата", "генеральная прокуратура",
)


def _is_public_org(text: str) -> bool:
    """True, если организация — госорган/суд/регулятор/правовой термин."""
    low = text.lower()
    if any(ph in low for ph in _PUBLIC_ORG_PHRASES):
        return True
    return bool(set(re.findall(r"[а-яёa-z]+", low)) & _PUBLIC_ORG_WORDS)


def _load_whitelist_file() -> None:
    """Загружает whitelist-записи (реквизиты своей компании, которые не маскируем)
    из tools/pre_anonymize/whitelist.local.txt — файл локальный, в .gitignore.

    Вызывается один раз при импорте модуля. Отсутствие файла — норма.
    """
    import logging as _logging
    import pathlib as _pathlib
    _log = _logging.getLogger(__name__)
    path = _pathlib.Path(__file__).with_name("whitelist.local.txt")
    try:
        if not path.exists():
            return
        added = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                _WHITELIST.add(line)
                added += 1
        if added:
            global _WHITELIST_SORTED
            _WHITELIST_SORTED = sorted(_WHITELIST, key=len, reverse=True)
            _log.info(f"[WHITELIST] Загружено записей: {added} из {path.name}")
    except Exception as exc:
        _log.warning(f"[WHITELIST] Ошибка загрузки: {exc}")


_load_whitelist_file()


def dlp_scan(text: str) -> dict[str, int]:
    """DLP-сканер: подсчитывает ПДн-маркеры в тексте без замены (фикс D5).

    Используется при загрузке документов в RAG, чтобы предупредить администратора
    о наличии персональных данных в файле перед индексацией.
    Возвращает {метка_типа_ПДн: количество_совпадений}. Сами значения не сохраняются.
    Пример: {"ФИО": 2, "ТЕЛЕФОН": 1, "ИНН_ЮЛ": 1}
    """
    # Защищаем organization whitelist заглушками, чтобы не считать реквизиты
    # своей компании как ПДн третьих лиц.
    protected = text
    for value in _WHITELIST_SORTED:
        if value in protected:
            protected = protected.replace(value, "\x00" * len(value))

    counts: dict[str, int] = {}
    for _name, pattern, label, _group_idx, accept in _PATTERNS:
        for m in pattern.finditer(protected):
            if accept is not None and not accept(m):
                continue
            counts[label] = counts.get(label, 0) + 1
    return counts
