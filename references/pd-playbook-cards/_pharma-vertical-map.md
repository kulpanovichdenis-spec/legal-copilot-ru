# Pharma / Healthcare vertical map (плейбук по персональным данным)

<!-- norm-verification-policy:v1 -->
> **Проверка нормы.** Этот файл — навигация и методика, а не источник права. Перед использованием нормы как правового основания вызвать `route_norm_verification(jurisdiction="RU", probe=true)`, открыть полный текст только по маршруту с `usable_now: true` и проверить редакцию, статус, pinpoint и provenance. Если пригодного маршрута нет — поставить `[ПРОВЕРИТЬ НОРМУ]`.

Support-файл плейбука по персональным данным. Индекс — `references/personal-data-playbook.md`.

Этот файл не создаёт отдельный «фармацевтический закон о ПД». Он показывает, какие базовые карточки должны быть связаны при типичных процессах фармкомпании.

| Pharma use case | Обязательные карточки | Дополнительные проверки |
|---|---|---|
| HCP conference / webinar | S28, S09, S16 | S11, S13, S22, S23, S29 |
| HCP CRM / professional communications | S04, S07 | S11, S12, S16, S22/S23 |
| Pharmacovigilance case | S21 | S16, S22/S23, S24, S25, S29 |
| Medical information request | S21 | S08/S09, S16, S24, S29 |
| Patient support program | S21, S06 | S08/S09, S11, S16, S22/S23, S24, S25, S29 |
| Clinical / observational data flow | S21 | специальное регулирование исследования — вне рамок этой версии; S16/S22/S23/S25/S29 |
| AI medical case summary | S29, S21 | S16, S22/S23, S25 |
| HCP segmentation / recommendation | S12 | S04, S07, S11, S29 |
| Pharma advertising event | S28 | ст. 24 38-ФЗ (NORM-028), audience qualification, S11/S13 |
| Employees / medical examinations | S03, S21 | S02, S16 |

## Правило

Если процесс содержит сведения о здоровье, агент **не заканчивает** анализ на общей ст. 6 152-ФЗ: запускается S21 и находится конкретное основание специальной категории по ст. 10 (NORM-005).

Если процесс связан с HCP-мероприятием, агент проверяет не только privacy, но и фармацевтический слой: ст. 67.1–67.2 61-ФЗ (NORM-034, NORM-035), ст. 74 323-ФЗ (NORM-036) и, при рекламе лекарственных средств, ст. 24 38-ФЗ (NORM-028). Пересечение с рекламным анализом креатива — `references/ad-creative-playbook.md` и `skills/fas-ad-practice-search/SKILL.md`.

## Следующая глубина развития

Версия 0.1 оставляет для отдельной фарма-надстройки подробные карточки: pharmacovigilance; patient support programs; medical information; clinical trials / observational studies; patient/HCP consent architecture; safety databases и международные фармаконадзорные потоки. Их целесообразно строить поверх готовых S21/S22/S23/S28/S29, а не дублировать общий privacy-layer.
