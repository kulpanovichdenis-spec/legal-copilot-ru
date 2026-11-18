# Legal DD Navigator — спецификация v1

> Интеграционные overrides `legal-copilot` (2026-09-28): DD-state создаётся в `workflow/YYYY.MM.DD <название>/dd-state/`; основной результат для юриста — «reports/dd-review.docx»; «html/index.html» остаётся дополнительной технической review-поверхностью. Канонические runtime-ресурсы находятся в `tools/legal_dd/resources/`, а команды запускаются как `python -m tools.legal_dd.cli ...`. При расхождении с этим историческим архитектурным описанием применяются `skills/legal-dd-navigator/SKILL.md` и общие правила `CLAUDE.md`.

## 0. Назначение

Система предназначена для агентского Legal Due Diligence при приобретении прав на лекарственные препараты и связанных активов, с возможностью расширения на share deal / mixed deal.

**Transaction Intake → Applicable Checks → Evidence Requirements → Dataroom → Findings → Human Review → Deal Documentation → Signed Documents → Roadmap**

Система проектируется не как таблица для человека, а как машиночитаемый слой знаний и состояния проекта. Excel и HTML являются представлениями данных, а не источником истины.

## 1. Базовые принципы

1. DD-проверка и документ не равны друг другу: один документ может подтверждать несколько фактов и checks; один check может требовать несколько документов и внешних источников.
2. Evidence шире документа: документ, сведения продавца, письмо-подтверждение, данные официального реестра, результат внешней проверки, структурированная информация из API/MCP, факт из документа.
3. Отсутствие найденного документа не означает отсутствие риска: если evidence не найден, статус `missing_information` / `cannot_conclude`, а не `clear`.
4. Ни один окончательный статус DD не возникает без подтверждения человеком.
5. Каждый подтвержденный факт должен иметь traceability: конкретный источник, точное место, краткий фрагмент/факт, связанный check, статус human review.
6. HTML — основной review UI. Источник истины — project state.
7. DD должен переходить в сделочную документацию.
8. После подписания документов должен переиспользоваться существующий skill подготовки Excel-roadmap по существенным условиям сделки.

## 2. Запуск проекта

Смысловые триггеры: «создаем проект DD», «новый DD», «запусти due diligence», «создай проверку сделки» и эквиваленты.

При запуске агент:
1. генерирует `project_id`;
2. сразу создает рабочую папку проекта;
3. формирует единый intake-вопросник;
4. показывает человеку список вопросов одним блоком;
5. после ответов записывает структуру сделки в `project.yaml`;
6. определяет применимые DD modules;
7. формирует первоначальный Evidence Request List;
8. подключает или создает dataroom.

## 3. Рабочая структура проекта

```text
workflow/
└── dd/
    └── <project_id>/
        ├── project.yaml
        ├── intake.md
        ├── navigator-state.json
        ├── dataroom/                 # только local/наш dataroom
        │   ├── inbox/
        │   └── manifest.json
        ├── connector/                # для external API/MCP
        │   └── dataroom.json
        ├── secrets/
        │   └── dataroom.env
        ├── state/
        │   ├── assets.json
        │   ├── parties.json
        │   ├── evidence.json
        │   ├── checks.json
        │   ├── findings.json
        │   ├── decisions.json
        │   └── contract-inputs.json
        ├── requests/
        │   ├── initial-request.md
        │   ├── gap-request.md
        │   └── closing-deliverables.md
        ├── html/
        │   └── index.html
        ├── drafts/
        │   ├── term-sheet/
        │   ├── agreements/
        │   ├── schedules/
        │   └── disclosure/
        ├── signed/
        ├── roadmap/
        └── logs/
            └── audit.jsonl
```

### 3.1. Secrets

Если dataroom внешний:
- секрет сохраняется в `secrets/dataroom.env`;
- `secrets/` исключается из git/Gitea/GitHub;
- секрет не попадает в HTML, logs или `project.yaml`;
- файл connector/dataroom.json хранит только несекретные параметры;
- при отсутствии секрета агент создает шаблон и запрашивает значение.

Если dataroom наш/local:
- создается `dataroom/`;
- материалы индексируются в `manifest.json`.

## 4. Transaction Intake

| ID | Вопрос / параметр | Тип | Влияние |
|---|---|---|---|
| TX-I-01 | Тип сделки: asset / share / mixed | select | набор модулей |
| TX-I-02 | Что приобретается | multi-select | assets/checks |
| TX-I-03 | Модель передачи: отчуждение / exclusive licence / non-exclusive / mixed | select | checks + drafting |
| TX-I-04 | Тип продукта: ЛП / БАД / иной | multi-select | regulatory routing |
| TX-I-05 | Юрисдикции сделки и коммерциализации | multi | jurisdiction routing |
| TX-I-06 | Кто продавец/правообладатель/держатель РУ | entity | party model |
| TX-I-07 | Остаются ли у продавца права после сделки | yes/no + details | retained rights |
| TX-I-08 | Передаются ли ТЗ / патенты / know-how / copyrights / domains / websites | multi | IP modules |
| TX-I-09 | Кто производит продукт сейчас | entity | manufacturing |
| TX-I-10 | Кто будет производить после сделки | entity | transition |
| TX-I-11 | Нужен ли transfer производства | yes/no/unknown | tech transfer |
| TX-I-12 | Будет ли продавец/affiliate поставлять продукт после сделки | yes/no | supply |
| TX-I-13 | Приобретаются ли товарные остатки | yes/no | inventory |
| TX-I-14 | Есть ли иностранные продавцы/правообладатели/регистрации | yes/no | local approvals |
| TX-I-15 | Есть ли физлица среди продавцов/правообладателей | yes/no | spouse/title |
| TX-I-16 | Dataroom: local / API / MCP / не создан | select | adapter |
| TX-I-17 | Планируемая дата signing / closing | date | roadmap/CP |
| TX-I-18 | Есть ли term sheet / согласованная структура | file/yes-no | drafting |

После intake агент формирует резюме: transaction structure, assets in scope, jurisdictions, parties and roles, manufacturing model, supply model, transfer model, open questions, applicable DD modules.

## 5. Dataroom Adapter

Единый интерфейс:

```text
list_items()
search(query)
read_item(id)
get_metadata(id)
get_updates(since)
get_locator(id, fact)
```

Local adapter читает `workflow/dd/<project_id>/dataroom/`, индексирует рекурсивно, определяет новые/измененные файлы, считает hash и не считает структуру папок юридической истиной.

API/MCP adapter хранит стабильные remote IDs, timestamps, capabilities и несекретные параметры. Skill не связан с конкретным MCP-server.

## 6. Evidence и точные локаторы

```yaml
evidence_id: EVOBJ-000123
source:
  type: local | api | mcp | external_registry | seller_statement
  source_id: "..."
  provider: "..."
document:
  name: "..."
  mime_type: "..."
  hash: "..."
classification:
  document_type: patent_assignment
  state: answered | unclear | needs_review | not_present
entities:
  parties: []
  assets: []
  jurisdictions: []
facts:
  - fact_id: FACT-001
    statement: "..."
    proposed_value: "..."
    locator:
      locator_type: page | section | paragraph | line | sheet_cell | table_row | api_field
      page: 12
      section: "3.2"
      paragraph: 4
      sheet: null
      cell: null
      provider_locator: null
    extraction_state: answered | unclear | needs_review | not_present | conflict_detected
    quote: "..."
    human_review:
      status: pending | confirmed | modified | rejected
      reviewed_by: null
      reviewed_at: null
      comment: null
supports:
  checks: []
  evidence_requirements: []
```

Правило: **Факт → Документ → Место → Фрагмент → Check → Human status.**

Для PDF — страница + раздел/пункт + фрагмент; DOCX — заголовок/абзац/пункт; XLSX — sheet + row/cell; API/MCP — item ID + field/content location; реестр — дата + объект + URL/ID результата.

## 7. Check status и Human Review

```yaml
check_id: IP-PAT-007
agent_assessment:
  status: clear | issue | missing_information | not_applicable | external_review_required
  conclusion: "..."
human_review:
  status: pending | confirmed | modified | rejected
  reviewer_comment: "..."
final_status:
  value: null
```

`final_status` не появляется до `confirmed` или `modified`. В HTML агентский `clear` до подтверждения показывается как **Proposed clear — awaiting human confirmation**.

## 8. Evidence Requirement

```yaml
id: ER-IP-CHAIN-001
title: Полная цепочка возникновения/перехода исключительного права
applies_to:
  asset_types: [patent, trademark, copyright, regulatory_documentation, know_how]
acceptable_evidence:
  - creation_agreement
  - employment_agreement
  - assignment_agreement
  - license_agreement
  - transfer_act
  - payment_confirmation
  - corporate_transfer_document
  - official_registry_extract
sufficiency:
  requires_complete_chain: true
requestable_from_seller: true
externally_verifiable: true
required_for: [IP-DOC-001, IP-TM-004, IP-PAT-006]
```



# 9. Каталог 57 DD Cards

Общая схема карточки:

```yaml
id:
title:
module:
objective:
applies_when:
inputs:
evidence_requirements:
external_checks:
subchecks:
outputs:
contract_effect:
dependencies:
human_confirmation_required: true
```

## A. Transaction Scope — 7

### TX-001 — Transaction Type and Perimeter
Цель: определить asset/share/mixed deal и общий периметр сделки. Trigger: всегда. Evidence: term sheet, correspondence, draft structure, seller list, asset list. Output: transaction_type, scope_summary, open questions. Contract effect: выбор основного договора и ancillary package.

### TX-002 — Parties and Roles
Цель: идентифицировать продавца, правообладателя, держателя РУ, производителя, поставщика, покупателя, будущего производителя. Trigger: всегда. Evidence: corporate docs, RUs, registers, contracts, intake. Output: party-role matrix. Contract effect: стороны, guarantees, covenants, joinder.

### TX-003 — Transfer Model
Цель: определить assignment/licence/mixed модель для каждого актива. Trigger: всегда. Evidence: term sheet, intake, current licences. Output: transfer model by asset. Contract effect: assignment vs licence provisions, exclusivity, sublicensing, registration.

### TX-004 — Territorial Scope
Цель: определить применимые территории и территорию коммерциализации. Trigger: всегда. Evidence: RUs, IP certificates, licences, intake. Output: jurisdiction matrix. Contract effect: territory clause, retained territories, local actions.

### TX-005 — Asset Inventory and Completeness
Цель: построить полный asset register и проверить пропущенные необходимые активы. Trigger: asset/mixed; в share deal — для product perimeter. Evidence: RUs, dossier index, IP portfolio, domains, websites, agreements, seller schedule. Output: asset register + gaps. Contract effect: asset schedules/excluded assets/closing deliverables.

### TX-006 — Retained Rights / Exclusivity / Field
Цель: установить сохраняемые продавцом/третьими лицами права. Trigger: licence/mixed либо продавец сохраняет деятельность. Evidence: licences, term sheet, distribution/manufacturing agreements. Output: retained-rights matrix. Contract effect: exclusivity, field, non-compete, carve-outs.

### TX-007 — Transaction Package and Interdependent Agreements
Цель: определить взаимосвязанные договоры и последовательность сделки. Trigger: всегда. Evidence: term sheet, drafts, supply/manufacturing/transfer arrangements. Output: transaction document map. Contract effect: APA/assignment/licence/supply/quality/tech-transfer/transition package.

## B. Regulatory / Medical — 9

### REG-001 — Registration Status and Holder
Подтвердить наличие, статус и holder каждой регистрации. Evidence: RU/certificate, official register, seller data. Output: registration matrix. Contract: transfer mechanics, CP, reps.

### REG-002 — Registration Dossier Completeness
Определить состав и фактическую полноту передаваемого досье. Evidence: dossier index, administrative/CMC/non-clinical/clinical files. Output: completeness map. Contract: asset schedule, delivery obligations, CP/gaps.

### REG-003 — Variations / Renewal / Lifecycle History
Проверить историю изменений, перерегистраций и текущих заявок. Evidence: submissions, approvals, authority correspondence. Output: lifecycle history + open applications. Contract: transition obligations/pending filings.

### REG-004 — Foreign Registrations
Проверить регистрации и статус продукта в иных юрисдикциях. Trigger: foreign territories. Evidence: foreign certificates/registers/local counsel. Output: country matrix. Contract: country schedules/approvals.

### REG-005 — Labeling / Instructions / Packaging
Сопоставить актуальные инструкции, макеты и зарегистрированные материалы. Evidence: IFU, packaging artworks, approved materials. Output: approved set + discrepancies. Contract: transferred materials/update obligations.

### REG-006 — Pharmacovigilance
Проверить PV documentation, responsibilities и переход функций. Trigger: лекарственный препарат. Evidence: PV system docs, agreements, safety reports, risk-management materials. Output: PV transition requirements. Contract: PV agreement/covenants.

### REG-007 — Preclinical and Clinical Documentation
Подтвердить наличие отчетов и прав на ДоКИ/КИ материалы. Evidence: protocols, reports, approvals, CRO agreements, rights chain. Output: study register + rights gaps. Contract: asset definition, reps, delivery obligations.

### REG-008 — Regulatory Commitments / Pending Proceedings
Выявить commitments перед регуляторами и незавершенные процедуры. Evidence: authority letters, submissions, corrective actions. Output: open regulatory obligations. Contract: CP/covenants.

### REG-009 — Product Quality / Stability / Series Evidence
Проверить key quality evidence, стабильность, series certificates. Evidence: CoA, stability data, batch data, specifications. Output: quality evidence status. Contract: quality reps/supply acceptance.

## C. Manufacturing / Quality / Supply — 9

### MFG-001 — Manufacturing Chain and Sites
Построить карту участников и площадок производства/упаковки/контроля. Evidence: dossier, licences, agreements, site master file. Output: manufacturing chain. Contract: manufacturing/supply schedules.

### MFG-002 — GMP / Manufacturing Authorisations
Проверить GMP/authorisations и статус. Evidence: GMP certificates/conclusions, licences, inspections. Output: authorisation status. Contract: CP/reps.

### MFG-003 — Technology / Process Documentation
Проверить полноту технологической документации. Evidence: process descriptions, technical instructions, industrial regulations, packaging instructions. Output: technology package completeness. Contract: tech-transfer deliverables.

### MFG-004 — Validation
Проверить process, cleaning и analytical validation. Evidence: validation plans/reports. Output: validation matrix/gaps. Contract: transfer milestones/acceptance.

### MFG-005 — Quality Agreements and Responsibility Matrix
Определить распределение quality responsibilities. Evidence: quality/technical agreements. Output: responsibility matrix. Contract: replacement/new quality agreement.

### MFG-006 — Suppliers / Raw Materials / Packaging
Проверить критичных suppliers/materials/contracts. Evidence: supplier lists, qualification, specs, contracts. Output: critical supplier map. Contract: continuity/assignment/novation.

### MFG-007 — Deviations / Inspections / Rejected Batches
Выявить существенные quality events и inspections. Evidence: deviations, OOS/OOT, audits, rejection data. Output: quality risk findings. Contract: reps/indemnities/disclosure.

### MFG-008 — Technology Transfer
Определить необходимость и объем transfer производства. Evidence: process docs, transfer protocols, site capabilities. Output: transfer workstream/dependencies. Contract: tech-transfer agreement/schedule.

### MFG-009 — Supply Continuity / Inventory
Определить continuity model, остатки, safety stock, переход supply. Evidence: inventory, supply agreements, forecasts, lead times. Output: continuity plan. Contract: supply agreement/inventory purchase/transition services.

## D. IP / Digital — 12

### IP-DOC-001 — Title to Regulatory / Technical Documentation
Подтвердить право продавца распоряжаться документацией. Evidence: R&D, clinical/preclinical, assignment, licence, employment, acceptance, payment. Output: chain of title. Contract: title reps/CP/asset schedule.

### IP-DOC-002 — Transferability / Encumbrances of Documentation
Проверить возможность передачи и ограничения. Evidence: licences, restrictions, consents, pledges. Output: transferability. Contract: consent CP/carve-outs.

### IP-KH-003 — Know-how / Trade Secrets
Идентифицировать know-how и проверить режим конфиденциальности и принадлежность. Evidence: trade-secret policies, NDAs, employee obligations, technical materials. Output: know-how inventory/status. Contract: definition/confidentiality/handover.

### IP-TM-004 — Trademark Portfolio / Title / Status
Проверить ТЗ/заявки, владельца, статус и территорию. Evidence: certificates, applications, registers, chain. Output: TM matrix. Contract: TM assignment/licence schedule.

### IP-TM-005 — Trademark Clearance / Third-Party Rights
Выявить конфликтующие права третьих лиц. Evidence: official databases/search, external counsel if needed. Output: clearance by jurisdiction. Contract: risk allocation/rebrand CP if needed.

### IP-PAT-006 — Patent Portfolio / Title / Status
Проверить патенты/заявки, правообладателя и статус. Evidence: patents, applications, registers, chain. Output: patent matrix. Contract: patent assignment/licence schedule.

### IP-PAT-007 — Patent FTO
Выявить patents третьих лиц, способные препятствовать commercialization. Evidence: patent search, claim analysis, patent counsel. Output: FTO by territory. Contract: CP/carve-out/indemnity/opinion.

### IP-CR-008 — Copyright / Packaging / Design
Проверить права на дизайн упаковки и copyright/design assets. Evidence: design agreements, employment, assignment, acts, payment. Output: rights chain. Contract: assignment/licence.

### IP-EMP-009 — Employee / Service IP and Remuneration
Проверить служебные РИД, права работодателя и выплаты авторам. Evidence: employment, job duties, service IP docs, remuneration evidence. Output: employee-IP gaps. Contract: reps/indemnities/curative CP.

### IP-DOM-010 — Domain Names
Проверить принадлежность admin rights и transfer mechanics. Evidence: registrar contracts, WHOIS/provider data. Output: domain register. Contract: transfer schedule/closing steps.

### IP-WEB-011 — Websites / Content / Marketing Materials
Проверить права на сайты, контент, рекламу, marketing materials. Evidence: development/design/content agreements, acts, payment. Output: digital/content rights map. Contract: assignment/licence + schedule.

### IP-ENC-012 — IP Licences / Encumbrances / Restrictions
Выявить licences, pledges, restrictions, third-party rights. Evidence: licences, pledge registers, seller confirmations. Output: encumbrance matrix. Contract: releases/consents/CP/permitted encumbrances.

## E. Corporate / Authority — 8

### CORP-001 — Legal Existence and Status
Подтвердить существование и статус продавца/правообладателя. Evidence: charter, register extract, good standing/incumbency. Output: corporate status. Contract: reps/party details.

### CORP-002 — Capacity / Required Licences
Проверить правоспособность и требуемые разрешения. Evidence: charter, licences, permits. Output: capacity. Contract: CP/reps.

### CORP-003 — CEO / Signatory Authority
Подтвердить полномочия ЕИО/подписанта. Evidence: appointment resolution, register, charter. Output: authority. Contract: execution block/closing docs.

### CORP-004 — Power of Attorney
Проверить доверенность представителя. Evidence: POA, revocation registers, approvals. Output: authority. Contract: closing document.

### CORP-005 — Major Transaction Approval
Определить необходимость approval крупной сделки. Evidence: balance sheet, asset value, charter, decisions. Output: approval requirement. Contract: CP.

### CORP-006 — Interested Party / Conflict Approval
Определить approval для заинтересованности/конфликта. Evidence: governance/ownership/approvals. Output: approval requirement. Contract: CP.

### CORP-007 — Internal Restrictions / Corporate Agreements
Выявить ограничения из charter/corporate agreements/internal docs. Output: restrictions/consents. Contract: consents/CP.

### CORP-008 — Natural Person Seller / Spousal / Ownership Issues
Проверить capacity/title/spousal consent физлица. Evidence: ID, marital docs, agreements, court decisions. Output: consents. Contract: CP/closing deliverables.

## F. Competition / Government Approvals — 5

### APP-001 — FAS / Economic Concentration
Определить необходимость consent/notification. Evidence: group data, balances, asset values, transaction structure. Output: filing requirement. Contract: regulatory CP/long-stop.

### APP-002 — Group Structure / Threshold Data
Собрать group/financial threshold dataset. Evidence: group chart, financials. Output: threshold dataset. Contract: filing support.

### APP-003 — Foreign Investment / Strategic Business
Проверить foreign investment control. Evidence: ownership/control, licences, activities. Output: approval requirement. Contract: CP/long-stop.

### APP-004 — Foreign Antitrust / Health Authority Approvals
Определить иностранные approvals по территориям. Evidence: local law routing + local counsel/official sources. Output: country approval matrix. Contract: CP/local mechanics.

### APP-005 — Public Procurement / Public Property / Special Procedures
Проверить торги/спецпроцедуры/consents публичного собственника. Evidence: status, procurement rules, asset status. Output: special procedure requirement. Contract: CP/feasibility.

## G. Disputes / Compliance — 4

### RISK-001 — Material Litigation / Enforcement
Выявить disputes/enforcement по продавцу или assets. Evidence: court/enforcement databases, seller info. Output: material disputes. Contract: disclosure/reps/indemnity/CP.

### RISK-002 — IP Disputes / Challenges / Administrative Proceedings
Проверить disputes/challenges по IP. Evidence: courts, patent/trademark offices, correspondence. Output: IP dispute register. Contract: specific indemnity/disclosure.

### RISK-003 — Regulatory / Quality Enforcement
Выявить regulatory claims, recalls, inspection findings, material violations. Evidence: authority correspondence, inspections, CAPA, recall data. Output: enforcement risks. Contract: reps/indemnities/covenants.

### RISK-004 — Sanctions / Anti-Corruption / Compliance
Выявить compliance risks, влияющие на сделку/исполнение. Evidence: policies, confirmations, public checks, counterparties. Output: compliance findings. Contract: compliance reps/covenants/termination.

## H. Closing / Transition — 3

### CLS-001 — Conditions Precedent / Closing Deliverables
Преобразовать unresolved material gaps и approvals в CP/closing list. Evidence: all confirmed findings. Output: CP/closing matrix. Contract: CP section + closing agenda.

### CLS-002 — Transfer Registration / Formalities
Определить recordal/registration actions по активам. Evidence: asset type, jurisdiction, register rules. Output: action list. Contract: closing/post-closing mechanics.

### CLS-003 — Post-Closing / Transition Obligations
Определить dossier handover, PV transition, tech transfer, registrations, supply transition, domain/admin handover и иные post-closing actions. Evidence: confirmed deal state/drafts. Output: post-closing matrix. Contract: covenants + roadmap input.



# 10. Contract Impact Model

Каждый Finding может иметь:

```yaml
contract_effect:
  affected_document:
    - main_asset_purchase_agreement
    - ip_assignment
    - licence
    - supply_agreement
    - quality_agreement
    - tech_transfer_agreement
    - transition_services
  mechanism:
    - representation
    - warranty
    - condition_precedent
    - covenant
    - indemnity
    - price_adjustment
    - retention
    - closing_deliverable
    - post_closing_action
    - disclosure
    - schedule_item
  proposed_clause_input: "..."
  human_approved: false
```

Только human-confirmed findings могут автоматически попадать в драфты как установленные факты. Неподтвержденные — только как placeholder/open issue/draft CP/question.

# 11. Переход от DD к драфтам

По команде «готовим договоры по проекту» агент:
1. читает confirmed transaction structure;
2. берет только confirmed assets;
3. берет confirmed findings;
4. берет unresolved material gaps;
5. берет approvals/CP;
6. формирует `contract-inputs.json`;
7. предлагает document package;
8. после human confirmation готовит drafts.

Routing:

```text
RU/dossier assignment → asset purchase / assignment agreement
exclusive licence → licence agreement
trademarks/patents → IP assignment/licence + schedules
seller continues manufacturing → supply/manufacturing agreement
third-party production → assignment/novation/new agreement
tech transfer → tech-transfer agreement/schedule
PV transition → PV agreement / annex
quality split → quality agreement
temporary support → transition services agreement
```

Traceability: **Clause → Contract Decision → Finding → Check → Fact → Evidence Locator.**

# 12. Contract Decision Layer

```yaml
decision_id: CD-001
topic: IP title gap
source_findings: [FND-IP-0021]
options:
  - cure_before_closing
  - specific_indemnity
  - holdback
  - exclude_asset
agent_recommendation: cure_before_closing
human_decision:
  status: pending
  selected_option: null
  comment: null
```

В договор попадает только подтвержденное человеком решение.

# 13. HTML Review Page

HTML пересобирается после meaningful state change.

Header:
- Project
- Transaction Type
- Parties
- Jurisdictions
- Last refresh
- Dataroom source
- Human review progress

Dashboard должен раздельно показывать:
```text
Checks total
Applicable
Agent completed
Awaiting human review
Human confirmed
Missing evidence
Material issues confirmed
```

Transaction perimeter:
```text
Asset ID
Asset type
Name
Jurisdiction
Current holder
Transfer model
Evidence status
Human confirmed
```

Каждая Check Card показывает:
```text
ID / Title
Applicability
Agent assessment
Human status
Conclusion
Risk
Contract impact

FACTS
Fact 1
  Document
  Exact locator
  Extract
  Human confirmation

MISSING EVIDENCE
ACTION
```

Фильтры: module, human review pending, issue, missing evidence, closing blocker, contract impact, jurisdiction, asset, party.

Отдельный Contract Preparation View:
```text
Confirmed deal structure
Confirmed assets
Open DD issues
CP candidates
Indemnity candidates
Covenant candidates
Required schedules
Required ancillary agreements
Pending human contract decisions
```

# 14. Request Lists

Система генерирует:
1. `Full Generic Request` — полный каталог для типа сделки.
2. `Tailored Initial Request` — только applicable requirements после intake.
3. `Gap Request` — отсутствующее/неполное/устаревшее или evidence, не подтверждающее нужный факт.
4. `Closing Deliverables List` — consents, originals, recordal forms, releases, approvals, signed ancillary agreements, handover materials.

# 15. Dataroom Processing

```text
Data room connected
→ Inventory / delta scan
→ Document classification
→ Entity + asset extraction
→ Fact extraction
→ Exact locators saved
→ Evidence Requirement mapping
→ Check evaluation
→ Agent proposed status
→ HTML review
→ Human confirmation
→ Final status
```

Incremental:
```text
get_updates()
→ classify only new/changed
→ identify affected Evidence Requirements
→ re-run only affected Checks
→ mark prior human confirmation as reconfirmation_required if underlying fact changed
```


# 15A. Automatic Evidence Extractors

После появления документов в local data room либо после подключения к удаленной data room через API/MCP агент автоматически запускает не один универсальный OCR/summary-процесс, а **реестр стандартных извлекателей**, выбранных исходя из:

1. типа документа;
2. объекта DD, к которому документ относится;
3. Evidence Requirement, ради которого документ был запрошен;
4. Check, который этот evidence должен подтвердить;
5. юрисдикции и типа сделки.

Ключевой принцип:

**Extractor не делает окончательный юридический вывод.**
Extractor извлекает факты, условия, реквизиты и потенциальные дефекты.
Юридический Check использует эти факты для предлагаемого вывода.
Окончательный статус подтверждает человек.

Общая цепочка:

```text
Document received / discovered
        ↓
Document classification
        ↓
Select extractor profile(s)
        ↓
Extract facts + exact locators
        ↓
Normalize entities and relations
        ↓
Map facts to Evidence Requirements
        ↓
Run relevant DD Checks
        ↓
Agent proposed conclusion
        ↓
HTML review
        ↓
Human confirmation / correction
```

## 15A.1. Extractor Registry

Каждый extractor описывается отдельной карточкой:

```yaml
extractor_id: EXT-CONTRACT-001

title: Contract legal-effect extractor

applies_to:
  document_types:
    - agreement
    - amendment
    - addendum
    - assignment_agreement
    - licence_agreement
    - services_agreement
    - R&D_agreement
    - clinical_trial_agreement

purposes:
  - confirm_conclusion
  - confirm_validity
  - identify_voidability_risks
  - confirm_authority_and_approvals
  - confirm_asset_identification
  - confirm_transfer_of_right
  - confirm_performance

extracts:
  - parties
  - representatives
  - authority_basis
  - date
  - place
  - governing_law
  - subject
  - transferred_assets
  - rights_scope
  - territory
  - term
  - conditions_precedent
  - consideration
  - payment_terms
  - transfer_moment
  - acceptance_mechanics
  - registration_requirement
  - consents_and_approvals
  - warranties
  - restrictions
  - termination
  - signatures
  - annexes
  - performance_evidence

human_review_required: true
```

Один документ может запускать несколько extractor profiles.

Например, договор НИОКР одновременно может обрабатываться:
- `EXT-CONTRACT-001`;
- `EXT-IP-CREATION-001`;
- `EXT-PERFORMANCE-001`;
- при наличии физлиц-авторов — `EXT-EMPLOYEE-CREATOR-001`.

---

# 15B. Standard Extractor Profiles

## EXT-CONTRACT-001 — Contracts / Agreements

Назначение: извлечь факты, необходимые для проверки заключенности, действительности, потенциальной оспоримости, объема переданных прав и надлежащего исполнения договора.

Минимальный набор извлекаемых данных:

### A. Идентификация договора
- наименование;
- дата;
- номер;
- место заключения;
- стороны;
- реквизиты сторон;
- подписанты;
- основание полномочий подписантов;
- применимое право;
- язык/версии договора;
- перечень приложений и дополнительных соглашений.

### B. Заключенность
Extractor должен извлечь факты, позволяющие Check-карточке оценить:
- согласован ли предмет;
- индивидуализирован ли объект;
- согласованы ли иные существенные условия, необходимые для данного типа договора;
- имеются ли ссылки на отсутствующие приложения, без которых предмет/объем обязательств не определяется;
- подписан ли договор всеми требуемыми сторонами;
- имеются ли условия о вступлении в силу;
- имеются ли отлагательные условия.

### C. Действительность / потенциальная оспоримость
Extractor извлекает:
- форму сделки;
- необходимость нотариальной формы;
- необходимость государственной регистрации;
- указанные в договоре корпоративные approvals;
- ссылки на решения органов управления;
- согласия третьих лиц;
- ограничения полномочий;
- признаки сделки с заинтересованностью / крупной сделки, если прямо следуют из документа;
- запреты/ограничения на передачу;
- representations относительно полномочий и прав;
- применимые условия о consent/waiver.

**Важно:** extractor не пишет «договор действителен». Он пишет, какие факты найдены/не найдены и какие проверки должны быть выполнены.

### D. Объект нашей сделки
Извлекается:
- точное наименование объекта;
- регистрационный номер;
- номер патента/ТЗ/РУ;
- название продукта;
- dossier/documentation;
- домен;
- artwork/design;
- know-how;
- иные идентификаторы;
- приложение/таблица, где объект перечислен.

Далее выполняется entity matching с `Asset Register`.

### E. Переход права к нашему контрагенту
Извлекается:
- первоначальный правообладатель;
- приобретатель;
- вид переданного права;
- исключительное/неисключительное право;
- территория;
- срок;
- момент перехода;
- необходимость регистрации перехода;
- условие об оплате как предпосылке перехода;
- акт приема-передачи;
- иные условия возникновения права.

Результат должен позволять построить:

```text
Previous holder
   ↓ agreement / transfer act / registration
Current seller / right holder
   ↓ proposed transaction
Buyer
```

### F. Надлежащее исполнение
Извлекаются:
- цена;
- порядок оплаты;
- акты;
- acceptance certificates;
- deliverables;
- сроки;
- evidence of payment;
- условия, при которых право считается переданным;
- штрафы / claims;
- положения о прекращении;
- сведения о расторжении/изменении;
- документы исполнения, связанные с договором.

Если договор требует оплаты, акта или регистрации для перехода права, отсутствие соответствующего evidence должно автоматически порождать `missing_information`.

---

## EXT-AMENDMENT-002 — Amendments / Addenda

Назначение: определить, какие положения базового договора изменены.

Извлекает:
- базовый договор;
- изменяемые пункты;
- новую редакцию;
- дату вступления изменений в силу;
- продление срока;
- изменение предмета/территории/цены/объема права;
- новые приложения;
- отмененные приложения;
- подписи и approvals.

Система должна строить **consolidated contract state**, а не анализировать каждую редакцию независимо.

---

## EXT-PERFORMANCE-003 — Acts / Payment / Performance Evidence

Применяется к:
- актам приема-передачи;
- актам оказанных услуг;
- платежным поручениям;
- банковским подтверждениям;
- invoices;
- delivery notes;
- registration confirmations.

Извлекает:
- к какому договору относится;
- кто исполнил;
- что именно исполнено;
- сумма;
- дата;
- объект;
- период;
- наличие оговорок/претензий;
- регистрационный факт;
- подтверждение передачи результата/прав.

---

## EXT-IP-CREATION-004 — Creation of IP by Contractor / R&D

Используется для НИОКР, разработки дизайна, документации, программ, исследований и иных РИД.

Извлекает:
- заказчик;
- исполнитель;
- конкретный результат;
- техническое задание;
- авторство/исполнители;
- принадлежность исключительных прав;
- момент возникновения/перехода права;
- территория;
- срок;
- право на переработку;
- право на передачу третьим лицам;
- confidentiality / know-how;
- размер и порядок оплаты;
- акт передачи результата;
- акт передачи прав;
- подтверждение оплаты;
- third-party materials;
- warranties об отсутствии прав третьих лиц.

---

## EXT-EMPLOYEE-IP-005 — Employee-Created IP / Service Works / Inventions

Для РИД, созданных работником, extractor должен использовать отдельный профиль.

Извлекает как минимум:
- работодатель;
- работник/автор;
- период трудовых отношений;
- должность;
- трудовую функцию;
- должностную инструкцию;
- служебное задание;
- связь созданного РИД с трудовыми обязанностями;
- дату создания;
- уведомление работодателя о создании;
- решение работодателя о сохранении/использовании/патентовании;
- документы о подаче заявки;
- авторское/служебное вознаграждение;
- размер, порядок и подтверждение выплаты;
- акты/отчеты;
- NDA/confidentiality;
- подтверждение передачи материалов работодателю;
- договоры с соавторами;
- иные соглашения о правах на РИД.

Check затем должен отдельно оценить:
- имеются ли основания считать РИД служебным;
- возникло ли право у работодателя;
- выполнены ли обязанности перед автором;
- нет ли неустраненных прав автора/третьих лиц.

Все выводы — только после human review.

---

## EXT-CORPORATE-006 — Charter / Corporate Documents

Применяется к:
- уставам;
- корпоративным договорам;
- положениям об органах управления;
- решениям/протоколам;
- выпискам из реестров.

Извлекает:
- фирменное наименование;
- ОГРН/регистрационный номер;
- юридическую форму;
- адрес;
- размер капитала;
- участников/акционеров;
- органы управления;
- компетенцию органов;
- полномочия ЕИО;
- срок полномочий;
- ограничения ЕИО;
- порядок approval крупных сделок;
- порядок approval заинтересованности;
- внутренние thresholds;
- специальные consent requirements;
- ограничения на отчуждение активов/долей;
- quorum;
- voting threshold;
- special rights/veto;
- corporate agreement restrictions;
- branch/representative authority.

Для решения/протокола дополнительно:
- орган;
- дата;
- quorum;
- agenda;
- содержание решения;
- голосование;
- approval конкретной сделки;
- параметры одобренной сделки;
- соответствие параметров объекту DD;
- срок действия approval, если применим.

---

## EXT-POA-007 — Power of Attorney

Извлекает:
- доверитель;
- представитель;
- дата;
- срок;
- передоверие;
- объем полномочий;
- право подписывать конкретный тип договора;
- право определять существенные условия;
- право подписывать акты;
- право получать оплату;
- право подавать заявления в реестры;
- ограничения;
- нотариальная форма;
- revoke information / registry details.

---

## EXT-IP-REGISTERED-008 — Patent / Trademark / Registered IP

Применяется к certificate, patent, application, register extract.

Извлекает:
- объект;
- номер;
- приоритет;
- дата подачи;
- дата регистрации;
- правообладатель;
- авторы/изобретатели;
- территория;
- классы/claims;
- срок правовой охраны;
- статус;
- renewals;
- licences;
- encumbrances;
- assignments;
- pending proceedings.

---

## EXT-REGISTRATION-009 — Medicinal Product Registration

Извлекает:
- название продукта;
- dosage form;
- strength;
- holder;
- manufacturer(s);
- номер РУ;
- дата регистрации;
- срок/статус;
- territories;
- variations;
- current instruction;
- approved packaging;
- dossier references;
- special commitments/restrictions.

---

## EXT-DOSSIER-010 — Registration Dossier / Regulatory Documentation

Extractor работает по структуре dossier и должен уметь определять:
- module/section;
- document type;
- version;
- date;
- product;
- manufacturer;
- substance;
- specification;
- method;
- validation;
- stability;
- clinical/non-clinical study;
- referenced third-party documents;
- rights/ownership indications;
- signatures/approval.

Результат — `dossier manifest` с указанием найденных и отсутствующих ожидаемых sections.

---

## EXT-MFG-011 — Manufacturing / Quality Documents

Применяется к:
- Site Master File;
- GMP;
- технологическим инструкциям;
- validation reports;
- quality agreements;
- specifications;
- deviations/OOS;
- audit/inspection reports.

Извлекает:
- site;
- manufacturer;
- operations;
- licence/GMP scope;
- process steps;
- critical parameters;
- validation status;
- responsibilities;
- deviations;
- CAPA;
- expiry/status;
- product references.

---

## EXT-DOMAIN-012 — Domain / Website Rights

Извлекает:
- domain;
- registrar;
- registrant/admin;
- creation/expiry;
- account holder;
- transfer restrictions;
- related agreements;
- website/content ownership;
- developer/content creator;
- payment/acceptance;
- third-party components.

---

## EXT-LITIGATION-013 — Litigation / Claims

Извлекает:
- court/authority;
- case number;
- parties;
- claims;
- asset/product involved;
- amount;
- stage;
- interim measures;
- outcome;
- appeal status;
- obligations imposed;
- impact on transferred asset;
- relevant dates.

---

## EXT-APPROVAL-014 — Regulatory / Government Approval

Применяется к ФАС, foreign investment approvals, health authority approvals и иным consents.

Извлекает:
- authority;
- applicant;
- transaction;
- assets/parties covered;
- date;
- validity;
- conditions;
- restrictions;
- completion/reporting duties.

---

# 15C. Purpose-Driven Extraction

Выбор extractor должен зависеть не только от типа файла, но и от вопроса, ради которого файл был запрошен.

Пример:

```yaml
document: assignment_agreement.pdf

requested_for:
  - ER-IP-CHAIN-001
  - ER-IP-TRANSFER-002

extractors:
  - EXT-CONTRACT-001
  - EXT-PERFORMANCE-003

questions_to_answer:
  - Кто передал право?
  - Кому?
  - На какой объект?
  - Индивидуализирован ли объект?
  - Какой объем права передан?
  - Какова территория?
  - Когда право переходит?
  - Требуется ли оплата?
  - Требуется ли акт?
  - Требуется ли регистрация?
  - Есть ли ограничения?
  - Имеются ли подтверждения исполнения?
```

То есть extractor получает **контекст цели проверки**, а не делает абстрактное summary документа.

---

# 15D. Automatic Run on Dataroom Intake

После добавления файлов в local dataroom или подключения remote dataroom выполняется:

```text
1. Inventory
2. Deduplication/hash check
3. OCR only where required
4. Document classification
5. Asset/entity matching
6. Select extractor profiles
7. Extract facts
8. Save exact locators
9. Link facts to Evidence Requirements
10. Run affected Checks
11. Generate proposed findings
12. Rebuild HTML
13. Create human review queue
```

Для новой партии документов выполняется только incremental processing.

---

# 15E. Human Verification of Extraction

Все автоматические извлечения проходят human verification.

Статусы extracted fact:

```text
pending_review
confirmed
modified
rejected
superseded
conflict_detected
```

В HTML возле каждого факта должны быть:
- документ;
- точное место;
- извлеченное значение;
- короткий excerpt;
- вопрос/check, для которого факт извлечен;
- кнопка/действие `confirm / modify / reject`.

Если человек изменяет факт:
- исходное agent extraction сохраняется в audit;
- новое значение становится human-confirmed;
- зависимые checks автоматически пересчитываются;
- ранее подтвержденные выводы, зависящие от измененного факта, переводятся в `reconfirmation_required`.

---

# 15F. Extractor QA / Test Set

Перед использованием каждого extractor в рабочем DD он должен быть протестирован человеком на эталонном наборе документов.

Для каждого extractor создается:

```text
tests/extractors/<extractor_id>/
├── fixtures/
├── expected.json
└── test-cases.yaml
```

Проверяются:
- полнота извлечения;
- точность значений;
- корректность entity matching;
- точность locator;
- отсутствие придуманных фактов;
- корректная обработка отсутствующей информации;
- корректная обработка противоречащих документов;
- различие между fact и legal conclusion.

Критичное правило:

**Ни один extractor не считается production-ready, пока человек не проверил его на реальных типовых документах соответствующего класса.**

---

# 15G. Extractor Output as Reusable Knowledge

После подтверждения человеком извлеченные факты становятся частью `project state`, а не просто summary документа.

Например:

```yaml
fact_id: FACT-CHAIN-0042
asset_id: TM-001
predicate: acquired_by
subject: Seller_A
object: Trademark_001
value:
  basis: assignment_agreement
  transfer_date: 2024-05-14
  registration_required: true
  registration_confirmed: true
evidence:
  document_id: DOC-018
  locator:
    page: 7
    section: "4.1"
human_review:
  status: confirmed
```

Такой факт затем может повторно использоваться:
- в DD Check;
- в HTML;
- в asset schedule;
- при подготовке договора;
- в disclosure schedule;
- в CP/closing list;
- после подписания — в transaction roadmap.



# 16. Human Review Rules

1. Агент не ставит окончательное `confirmed_clear`.
2. Агент показывает concrete evidence для каждого вывода.
3. Каждый факт имеет exact locator.
4. При противоречии документов: `conflict_detected`.
5. При изменении источника после confirmation: `reconfirmation_required`.
6. Human comment хранится в state.
7. HTML явно разделяет `Agent proposed` и `Human confirmed`.

# 17. Audit Trail

```json
{
  "timestamp": "...",
  "event": "finding_confirmed",
  "project_id": "...",
  "check_id": "IP-PAT-006",
  "finding_id": "...",
  "actor": "human",
  "old_status": "pending",
  "new_status": "confirmed",
  "evidence_ids": ["..."]
}
```

Секреты/токены/пароли в audit не попадают.

# 18. Share Deal Routing

При `share` или `mixed` подключается отдельный company-DD pack:

```text
legal status
capital / shares
share title
corporate governance
affiliates
powers of attorney
real estate
material assets
IP
IT
licences / regulatory
material agreements
insurance
debt
bank accounts
litigation
employment
tax/compliance
```

Pharma/product pack сохраняется, если продукт/regulatory assets существенны для target.

# 19. Roadmap Integration after Signing

После загрузки signed docs и команды «сформируй roadmap по сделке» DD-skill вызывает существующий Excel-roadmap skill.

```yaml
integrations:
  roadmap_skill:
    ref: "<configured-existing-roadmap-skill>"
    trigger:
      - signed_documents_available
      - user_requests_roadmap
```

Inputs:
```text
signed agreements
confirmed transaction structure
confirmed parties/assets
conditions precedent
closing obligations
post-closing obligations
deadlines
responsible parties
deliverables
dependencies
```

Signed agreement имеет приоритет над draft/project state; расхождения фиксируются.

# 20. Suggested Skill Structure

```text
skills/legal-dd-navigator/
├── SKILL.md
├── navigator.yaml
├── cards/
│   ├── transaction/
│   ├── regulatory/
│   ├── manufacturing/
│   ├── ip/
│   ├── corporate/
│   ├── approvals/
│   ├── risk/
│   └── closing/
├── evidence/
│   ├── regulatory.yaml
│   ├── manufacturing.yaml
│   ├── ip.yaml
│   ├── corporate.yaml
│   ├── approvals.yaml
│   └── risk.yaml
├── schemas/
│   ├── project.schema.json
│   ├── party.schema.json
│   ├── asset.schema.json
│   ├── evidence.schema.json
│   ├── fact.schema.json
│   ├── check.schema.json
│   ├── finding.schema.json
│   └── decision.schema.json
├── prompts/
│   ├── intake.md
│   ├── classify-evidence.md
│   ├── analyze-check.md
│   ├── gap-request.md
│   ├── html-render.md
│   └── contract-routing.md
└── templates/
    ├── project/
    └── html/
```

# 21. MVP Order

Phase 1: project creation, intake, folder structure, local dataroom, asset register, 57 cards, evidence/fact locators, HTML, human confirmation.

Phase 2: API/MCP adapters, incremental updates, gap request, external registry checks.

Phase 3: contract decision layer, draft package routing, deal-document drafts.

Phase 4: signed-document reconciliation, existing roadmap skill integration, Excel roadmap.

# 22. Non-negotiable Acceptance Criteria

1. DD project создается одной командой.
2. Workspace создается автоматически.
3. Intake выдается единым блоком.
4. local/API/MCP data room работают через единый interface.
5. Каждый существенный факт имеет exact source locator.
6. Автоматический вывод не окончательный без человека.
7. HTML показывает evidence за каждым выводом.
8. Генерируется tailored request list.
9. Генерируется gap request.
10. Генерируется CP/closing deliverables list.
11. Confirmed DD data переиспользуются при drafting.
12. Signed docs передаются существующему roadmap skill.
13. Secrets не попадают в HTML/logs/VCS.
14. Project поддерживает incremental review без полного переразбора data room.
15. Любой clause, автоматически предложенный из DD, трассируется назад до finding/check/fact/evidence.
16. После появления нового evidence автоматически запускается подходящий extractor profile.
17. Extractor выбирается с учетом цели запроса документа, а не только MIME/type документа.
18. Для договоров автоматически извлекаются факты о заключенности, форме, approvals, предмете, переходе права и исполнении.
19. Для employee-created IP, corporate documents, registered IP, regulatory dossier, manufacturing и иных классов используются отдельные extractor profiles.
20. Все extracted facts проходят human verification.
21. Ни один production extractor не используется без human-reviewed test set.
22. Изменение human-confirmed факта автоматически переводит зависимые findings/checks в `reconfirmation_required`.


# 15H. Extractor Registry v1 — implementation reference

Полный реестр автоматических извлекателей вынесен в отдельный машиночитаемый файл:

- `legal_dd_extractor_registry_v1.yaml` — runtime registry;
- `legal_dd_extractor_registry_v1.md` — human-readable registry.

В v1 реестр содержит **31 extractor profiles**. Каждый профиль задает:
- применимые типы документов;
- цель извлечения;
- сущности;
- факты;
- связанные 57 DD Checks;
- critical fields;
- вопросы human review;
- fail-safe правило.

## 15H.1. Routing rule

```text
document type
+ reason requested
+ Evidence Requirement
+ Check
+ asset type
+ jurisdiction
+ transaction type
→ extractor selection
```

Один документ может запускать несколько extractors.

## 15H.2. Local dataroom dropzones

Опционально создаются:

```text
dataroom/dropzones/contracts/
dataroom/dropzones/corporate/
dataroom/dropzones/ip/
dataroom/dropzones/regulatory/
dataroom/dropzones/manufacturing/
dataroom/dropzones/litigation/
dataroom/dropzones/approvals/
```

Dropzone является только routing hint. Любой документ сначала проходит базовый `EXT-GEN-001`.

## 15H.3. Runtime requirement

После появления нового/измененного файла или remote item:

```text
classify
→ select extractors
→ extract entities/relations/facts
→ save exact locators
→ map to Evidence Requirements
→ re-run affected Checks
→ regenerate HTML
→ queue for human review
```

Ни одно извлечение не становится окончательным фактом без human confirmation.


# 15I. Evidence Requirements Catalog v1

Между 57 DD Checks и 31 Extractor Profiles вводится самостоятельный слой `Evidence Requirements`.

Полные файлы:
- `legal_dd_evidence_catalog_v1.yaml`;
- `legal_dd_evidence_catalog_v1.md`;
- `legal_dd_check_evidence_extractor_map_v1.yaml`.

Каталог содержит **67 Evidence Requirements** и покрывает **57/57** базовых DD Checks.

## 15I.1. Runtime chain

```text
Transaction Intake
→ Applicable DD Check
→ Applicable Evidence Requirements
→ Initial Request / External Check
→ Dataroom
→ Document Classification
→ Purpose-driven Extractor
→ Facts + Exact Locators
→ Evidence Sufficiency
→ DD Check
→ Agent Proposed Finding
→ Human Review
→ Final Status
→ HTML / Contract Decision / Drafting
```

## 15I.2. Evidence sufficiency

Наличие файла не закрывает requirement.

`Evidence Requirement = satisfied` только если:
- документ/источник действительно относится к требованию;
- извлечены необходимые facts;
- material facts имеют exact source locator;
- выполнено `sufficient_if`;
- обязательные приложения/акты/оплата/регистрация/consents не отсутствуют;
- человек подтвердил достаточность evidence/соответствующий вывод.

## 15I.3. Automatic request generation

`Tailored Initial Request` формируется как объединение `request_text` всех applicable Evidence Requirements с:
- дедупликацией;
- группировкой по адресату;
- учетом уже имеющихся документов;
- учетом external-only requirements;
- маркировкой conditional requirements.

`Gap Request` строится только из требований со статусами:
- `not_requested`;
- `requested`;
- `partially_satisfied`;
- `invalid`;
- `outdated`;
- `unavailable` — если отсутствие создает юридический gap.

## 15I.4. Check execution rule

DD Check не может получить agent status `clear`, пока все обязательные для него Evidence Requirements не имеют допустимого состояния:
- `satisfied`;
- `external_source`;
- либо `not_applicable`, если неприменимость подтверждена.

При ином состоянии check должен оставаться `missing_information`, `in_progress` или иным не-final agent status.

# 15J. Practice Profile + Project Overrides

Вводится двухуровневая конфигурация:

```text
Practice Profile
      +
Project Overrides
```

`Practice Profile` хранит постоянные правила команды, а `workflow/dd/<project_id>/project.yaml` — только настройки конкретного проекта.

Рекомендуемый постоянный файл:

```text
skills/legal-dd-navigator/profile.yaml
```

Базовые параметры:

```yaml
practice:
  default_jurisdiction: RU
  language: ru
  risk_posture: conservative

review:
  human_confirmation_required: true
  exact_quote_required_for_material_fact: true
  exact_locator_required_for_material_fact: true

scope_defaults:
  chain_of_title: exhaustive
  regulatory_title: exhaustive
  regulatory_dossier: exhaustive
  corporate_authority: exhaustive
  IP_encumbrances: exhaustive
  litigation: materiality_filtered
  supplier_contracts: risk_based

external_review:
  patent_FTO: always
  trademark_clearance: jurisdiction_dependent
  foreign_regulatory: jurisdiction_dependent
```

Проектные overrides имеют приоритет над Practice Profile.

---

# 15K. Typed Extraction Model

Для каждого extractor заранее задается строгая схема полей.

Допустимые базовые типы:

```text
verbatim
text
enum
boolean
date
duration
currency
number
entity_ref
asset_ref
document_ref
jurisdiction
legal_effect
```

Пример:

```yaml
field_id: transfer_trigger
type: enum

allowed_values:
  - signing
  - payment
  - acceptance_act
  - registration
  - other

state: answered
value: payment

quote: "..."
location:
  document_id: DOC-018
  page: 7
  section: "4.3"

human_review:
  status: pending
```

## 15K.1. Extraction states

В юридическом state не используются numeric confidence scores.

```text
answered
not_present
unclear
needs_review
conflict_detected
```

Правила:

- `answered` допускается только при наличии `quote` и `location`;
- `not_present` означает, что поле искалось и не найдено;
- `unclear` — релевантный текст найден, но он неоднозначен;
- `needs_review` — значение нельзя надежно нормализовать;
- `conflict_detected` — имеются противоречия внутри документа или между документами.

---

# 15L. Project Calibration Before Bulk Processing

Помимо production QA extractor вводится обязательная project calibration.

```text
Extractor schema
      ↓
3–5 representative documents
      ↓
Human review
      ↓
schema / mapping correction
      ↓
bulk processing
```

До массовой обработки нового класса документов конкретной data room сначала проверяются 3–5 репрезентативных документов. Bulk processing запускается после подтверждения человеком, что схема извлечения и routing подходят для конкретного проекта.

---

# 15M. Document Families

Базовый договор, amendments, addenda, side letters, replacement schedules и связанные документы образуют `Document Family`.

```yaml
document_family_id: DF-001
family_type: agreement

base_document:
  document_id: DOC-001

members:
  - document_id: DOC-014
    relation: amendment
  - document_id: DOC-027
    relation: addendum
  - document_id: DOC-041
    relation: side_letter

current_state:
  generated: true
  effective_date: 2026-01-01
  unresolved_conflicts: []
```

Если Document Family собрана, Check анализирует `current_state`, а не изолированный исходный файл.

Если отсутствует базовый договор или критическое amendment, `current_state = unavailable`, и связанный Check не может получить `clear`.

---

# 15N. Cross-Document Normalizer

После extraction работает отдельный Normalizer.

Он:
- приводит enum/date/currency/party/asset identifiers к единому формату;
- выявляет semantic duplicates;
- обнаруживает противоречия;
- выявляет outliers в однородных наборах;
- проверяет, что `answered` содержит quote + locator;
- формирует human review queue.

Normalizer не вправе автоматически исправлять юридически значимые данные по принципу большинства.

Пример:

```text
30 assignment agreements

28 → transfer_trigger = registration
 2 → transfer_trigger = signing

Normalizer:
  review_cluster = minority_outlier
  documents = DOC-041, DOC-052
```

---

# 15O. Dataroom Watcher

Data room работает в двух режимах:

```text
INVENTORY / WATCH
      ↓
DEEP REVIEW
```

## Watch mode

Для нового/измененного item:

```text
new/changed item
→ classify
→ map to Document Family
→ map to Evidence Requirement
→ identify affected DD Checks
→ queue extractor(s)
```

Watcher не делает окончательный legal review.

## Deep-review mode

```text
run extractors
→ typed facts
→ Document Family current state
→ Normalizer
→ affected DD Checks
→ rebuild HTML
→ human review queue
```

Если новое evidence затрагивает ранее подтвержденный факт, зависимые выводы получают `reconfirmation_required`.

---

# 15P. Evidence Coverage View

HTML получает отдельный экран `Evidence Coverage`.

Пример:

```text
ER-IP-001  Chain of title             PARTIAL
  8 documents
  missing: prior assignment

ER-IP-002  Performance                PARTIAL
  act found
  payment missing

ER-REG-002 Dossier index              SATISFIED
ER-REG-010 Pharmacovigilance          REQUESTED
ER-MFG-005 Quality Agreement          REVIEW
```

Для каждого Evidence Requirement отображаются:
- applicability;
- request status;
- received candidates;
- sufficiency status;
- source documents;
- missing elements;
- linked DD Checks;
- human review state.

---

# 15Q. Review Scope

Каждый Evidence Requirement получает:

```yaml
review_scope:
  mode: exhaustive | materiality_filtered | risk_based
```

### Exhaustive
По умолчанию:
- chain of title;
- права на активы сделки;
- registration rights;
- regulatory dossier completeness;
- IP encumbrances;
- authority/signatory;
- approvals required for transaction;
- активы, прямо входящие в transaction perimeter.

### Materiality-filtered / risk-based
Может применяться к:
- generic commercial agreements;
- broader litigation;
- non-critical suppliers;
- general compliance matters;
- company-wide matters вне прямой проверки title на приобретаемые активы.

Низкая стоимость договора не является основанием пропустить его, если он входит в chain of title или подтверждает право на актив сделки.

---

# 15R. Security Isolation

Материалы data room считаются untrusted input.

Рекомендуемая архитектура:

```text
DATAROOM READER
  read-only raw documents
        ↓
EXTRACTOR
  read-only raw documents
        ↓
STRUCTURED FACT STORE
        ↓
DD CHECKER
  structured facts + legal sources
        ↓
STATE / HTML WRITER
  project outputs only
```

Правила:
- текст документа не может напрямую инициировать filesystem/network/tool actions;
- extractor не имеет write-access к production state;
- writer не обязан иметь доступ к raw documents;
- credentials/secrets недоступны document-processing workers;
- инструкции, обнаруженные внутри документа, трактуются только как содержимое документа;
- external actions выполняются только отдельным разрешенным workflow.

---

# 15S. Legal Authority Provenance

Fact evidence и legal authority хранятся отдельно.

```yaml
finding:
  factual_basis:
    - fact_id: FACT-001

  legal_basis:
    - proposition: "..."
      jurisdiction: RU
      source_type: official | legal_database | court | web_verify | model_unverified
      source: "..."
      locator: "..."
      verified: true
```

`FACT EVIDENCE` подтверждает, что произошло или что написано в документе.

`LEGAL AUTHORITY` подтверждает правовое значение установленного факта.

`model_unverified` не может быть единственным основанием final legal conclusion.

---

# 15T. Formal Skill Handoffs

Между стадиями используются структурированные handoff payloads.

```yaml
handoff_id: HO-001

from:
  component: DD_CHECK
  check_id: IP-DOC-001

to:
  - CONTRACT_DECISIONS
  - CLOSING_CHECKLIST

trigger:
  final_status: issue

payload:
  project_id:
  asset_id:
  finding_id:
  evidence_ids:
  required_action:
  blocking_effect:
  contract_effect:
```

Минимальные handoffs:

```text
DD → Contract Decision
DD → Closing / CP
DD → Drafting
Signed Documents → Roadmap Skill
Post-closing evidence → Roadmap status update
```

---

# 15U. Original Implementation Principle

Legal DD Navigator использует общие инженерные идеи как источник вдохновения, но реализация остается самостоятельной.

Правила:
- не копировать сторонний source code;
- не копировать уникальные prompt templates или текстовые инструкции;
- самостоятельно формулировать schemas, prompts, routing rules и код;
- сохранять собственную предметную модель pharma DD;
- не включать сторонний код в продукт без отдельного сознательного решения по лицензированию.

Основная архитектура продукта остается собственной:
**57 DD Checks + Evidence Requirements + Extractor Registry + human review + drafting + roadmap integration**.
