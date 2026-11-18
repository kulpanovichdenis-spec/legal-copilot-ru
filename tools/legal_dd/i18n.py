from __future__ import annotations

STATUS_RU = {
    "human_review":"проверка человеком",
    "dataroom_setup":"подключение data room",
    "not_started":"не начата",
    "in_progress":"в работе",
    "clear":"предварительно без замечаний",
    "issue":"выявлен вопрос",
    "cannot_conclude":"недостаточно данных",
    "external_review_required":"требуется внешняя проверка",
    "not_applicable":"не применимо",
    "pending":"ожидает подтверждения",
    "confirmed":"подтверждено",
    "modified":"изменено и подтверждено",
    "rejected":"отклонено",
    "reconfirmation_required":"требуется повторное подтверждение",
    "answered":"извлечено",
    "not_present":"не найдено",
    "unclear":"неоднозначно",
    "needs_review":"требует проверки",
    "conflict_detected":"обнаружено противоречие",
    "not_requested":"не запрошено",
    "requested":"запрошено",
    "received":"получено",
    "partially_satisfied":"частично подтверждено",
    "satisfied":"достаточно",
    "invalid":"не подходит",
    "outdated":"устарело",
    "unavailable":"недоступно",
    "external_source":"внешний источник",
    "material":"существенный",
    "critical":"критический",
    "high":"высокий",
    "medium":"средний",
    "low":"низкий",
    "info":"информационный",
    "proposed":"предложено агентом",
}

VALUE_RU = {
    "asset":"приобретение активов",
    "share":"приобретение акций / долей",
    "mixed":"смешанная структура",
    "assignment":"отчуждение права",
    "exclusive_licence":"исключительная лицензия",
    "nonexclusive_licence":"неисключительная лицензия",
    "local":"локальная",
    "api":"внешняя через API",
    "mcp":"внешняя через MCP",
    "registration_right":"регистрационное право",
    "registration_rights":"регистрационные права",
    "regulatory_dossier":"регуляторное досье",
    "trademark":"товарный знак",
    "trademarks":"товарные знаки",
    "patent":"патент",
    "patents":"патенты",
    "know_how":"ноу-хау",
    "medicinal_product":"лекарственный препарат",
    "supplement":"БАД",
    "medical_device":"медицинское изделие",
    "payment":"оплата",
    "signing":"подписание",
    "acceptance_act":"акт приема-передачи",
    "registration":"регистрация",
    "cure_before_closing":"устранить до закрытия",
    "specific_indemnity":"специальное возмещение потерь / indemnity",
    "holdback":"удержание части цены",
    "exclude_asset":"исключить актив из сделки",
    "asset_purchase_or_master_transfer_agreement":"договор приобретения / передачи активов",
    "IP_transfer_schedule_or_agreement":"договор / приложение о передаче прав на ИС",
    "regulatory_asset_schedule":"перечень регуляторных активов",
    "share_purchase_agreement":"договор купли-продажи акций / долей",
    "licence_agreement":"лицензионный договор",
    "supply_or_manufacturing_agreement":"договор поставки / производства",
    "quality_agreement":"соглашение по качеству",
    "technology_transfer_agreement_or_schedule":"договор / план трансфера производства",
    "PV_transition_agreement_or_annex":"соглашение / приложение по переходу фармаконадзора",
}

FIELD_RU = {
    "registration_holder":"держатель регистрации",
    "transfer_trigger":"условие / момент перехода права",
    "parties":"стороны",
    "subject_matter":"предмет договора",
    "asset_identifiers":"идентификаторы актива",
    "right_scope":"объем права",
    "transfer_moment":"момент перехода права",
    "payment_condition":"условие оплаты",
    "registration_requirement":"необходимость регистрации",
}

def tr_status(value):
    if value is None: return "—"
    return STATUS_RU.get(str(value), str(value))

def tr_value(value):
    if value is None or value == "": return "—"
    return VALUE_RU.get(str(value), str(value))

def tr_field(value):
    if value is None or value == "": return "—"
    return FIELD_RU.get(str(value), str(value))

def tr_review_item(value):
    s=str(value)
    if s.startswith("Confirm "):
        return "Подтвердить " + s[len("Confirm "):]
    if s.startswith("Review "):
        return "Проверить " + s[len("Review "):]
    return s
