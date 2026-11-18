# Индекс карточек договорного плейбука

Всего карточек: 82. Развёрнутых: 42; коротких (перенесены из прежнего плейбука без переработки): 40. Роутер — `references/contract-playbook.md`, раздел 0, шаг 0.1a.

Карточки читаются по разделам, а не целиком: `python tools/contract_playbook/cards.py show <карточка> --section <раздел>`. Поиск — `find`, соседи по графу — `neighbors`. Машиночитаемые данные: `_index.json` (карточки и прежние идентификаторы), `_graph.json` (связи). Легенда классов коротких карточек — `_klassy-suschestvennosti.md`.

Все карточки — черновой материал для юриста. Маркеры `[ПРОВЕРИТЬ …]` и `[СВЕРИТЬ …]` показывают, что именно не проверено по первоисточнику.

## Общая часть (`general`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Заключение договора и существенные условия | [zakliuchenie-dogovora](general/zakliuchenie-dogovora.md) | развёрнутая | `RU.GENERAL.ZAKLIUCHENIE_DOGOVORA` | 2026-10-30 | 1 |
| Изменение и расторжение договора; прекращение обязательств | [izmenenie-rastorzhenie](general/izmenenie-rastorzhenie.md) | развёрнутая | `RU.GENERAL.IZMENENIE_RASTORZHENIE` | 2026-10-30 | 1 |
| Исполнение обязательств по договору | [ispolnenie](general/ispolnenie.md) | развёрнутая | `RU.GENERAL.ISPOLNENIE` | 2026-10-31 | 1 |
| Недействительность договора | [nedeistvitelnost](general/nedeistvitelnost.md) | развёрнутая | `RU.GENERAL.NEDEISTVITELNOST` | 2026-10-30 | 1 |
| Обеспечение исполнения договора | [obespechenie](general/obespechenie.md) | развёрнутая | `RU.GENERAL.OBESPECHENIE` | 2026-10-31 | 1 |
| Ответственность за нарушение договора | [otvetstvennost](general/otvetstvennost.md) | развёрнутая | `RU.GENERAL.OTVETSTVENNOST` | 2026-10-31 | 1 |
| Рамочный договор | [ramochnyi-dogovor](general/ramochnyi-dogovor.md) | развёрнутая | `RU.GENERAL.RAMOCHNYI_DOGOVOR` | 2026-11-01 | 1 |
| Толкование договора | [tolkovanie-dogovora](general/tolkovanie-dogovora.md) | развёрнутая | `RU.GENERAL.TOLKOVANIE_DOGOVORA` | 2026-10-30 | 1 |
| Уступка требования, перевод долга, передача договора | [ustupka-perevod-dolga](general/ustupka-perevod-dolga.md) | развёрнутая | `RU.GENERAL.USTUPKA_PEREVOD_DOLGA` | 2026-10-30 | 1 |
| Опционный договор | [optsionnyi-dogovor](general/optsionnyi-dogovor.md) | короткая | `RU.GENERAL_CONSTRUCTIONS.OPTSIONNYI_DOGOVOR` | 2026-11-10 | 1 |

## Передача имущества (`property_transfer`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Дарение и пожертвование | [darenie-pozhertvovanie](property_transfer/darenie-pozhertvovanie.md) | развёрнутая | `RU.PROPERTY_TRANSFER.DARENIE` | 2026-11-06 | 1 |
| Купля-продажа (общие положения) | [kuplia-prodazha](property_transfer/kuplia-prodazha.md) | развёрнутая | `RU.PROPERTY_TRANSFER.KUPLIA_PRODAZHA` | 2026-10-31 | 1 |
| Мена | [mena](property_transfer/mena.md) | развёрнутая | `RU.PROPERTY_TRANSFER.MENA` | 2026-11-06 | 1 |
| Поставка | [postavka](property_transfer/postavka.md) | развёрнутая | `RU.PROPERTY_TRANSFER.POSTAVKA` | 2026-10-31 | 1 |
| Продажа недвижимости и предприятия | [prodazha-nedvizhimosti](property_transfer/prodazha-nedvizhimosti.md) | развёрнутая | `RU.PROPERTY_TRANSFER.PRODAZHA_NEDVIZHIMOSTI` | 2026-11-09 | 1 |
| Розничная купля-продажа | [roznichnaia-kuplia-prodazha](property_transfer/roznichnaia-kuplia-prodazha.md) | развёрнутая | `RU.PROPERTY_TRANSFER.ROZNICHNAIA_KUPLIA_PRODAZHA` | 2026-10-31 | 1 |
| Энергоснабжение | [energosnabzhenie](property_transfer/energosnabzhenie.md) | развёрнутая | `RU.PROPERTY_TRANSFER.ENERGOSNABZHENIE` | 2026-11-06 | 1 |
| Контрактация | [kontraktatsiia](property_transfer/kontraktatsiia.md) | короткая | `RU.PROPERTY_TRANSFER.KONTRAKTATSIIA` | 2026-11-10 | 1 |
| Пожизненная рента | [pozhiznennaia-renta](property_transfer/pozhiznennaia-renta.md) | короткая | `RU.PROPERTY_TRANSFER.POZHIZNENNAIA_RENTA` | 2026-11-10 | 1 |
| Пожизненное содержание с иждивением | [pozhiznennoe-soderzhanie-s-izhdiveniem](property_transfer/pozhiznennoe-soderzhanie-s-izhdiveniem.md) | короткая | `RU.PROPERTY_TRANSFER.POZHIZNENNOE_SODERZHANIE_S_IZHDIVENIEM` | 2026-11-10 | 1 |
| Постоянная рента | [postoiannaia-renta](property_transfer/postoiannaia-renta.md) | короткая | `RU.PROPERTY_TRANSFER.POSTOIANNAIA_RENTA` | 2026-11-10 | 1 |

## Работы и услуги (`works_services`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Возмездное оказание услуг | [uslugi](works_services/uslugi.md) | развёрнутая | `RU.WORKS_SERVICES.USLUGI` | 2026-11-01 | 1 |
| НИР и ОКР | [niokr](works_services/niokr.md) | развёрнутая | `RU.WORKS_SERVICES.NIOKR` | 2026-11-01 | 1 |
| Подряд (общие положения) | [podriad](works_services/podriad.md) | развёрнутая | `RU.WORKS_SERVICES.PODRIAD` | 2026-11-01 | 1 |
| Строительный подряд (с проектными и изыскательскими работами) | [stroitelnyi-podriad](works_services/stroitelnyi-podriad.md) | развёрнутая | `RU.WORKS_SERVICES.STROITELNYI_PODRIAD` | 2026-11-10 | 1 |
| Бытовой подряд | [bytovoi-podriad](works_services/bytovoi-podriad.md) | короткая | `RU.WORKS_RESEARCH_SERVICES.BYTOVOI_PODRIAD` | 2026-11-10 | 1 |

## Аренда и пользование (`lease`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Аренда | [arenda](lease/arenda.md) | развёрнутая | `RU.LEASE.ARENDA` | 2026-11-02 | 1 |
| Аренда зданий, сооружений и помещений | [arenda-zdanii-pomeshchenii](lease/arenda-zdanii-pomeshchenii.md) | развёрнутая | `RU.LEASE.ARENDA_ZDANII_POMESHCHENII` | 2026-11-02 | 1 |
| Безвозмездное пользование (ссуда) | [bezvozmezdnoe-polzovanie](lease/bezvozmezdnoe-polzovanie.md) | развёрнутая | `RU.LEASE.BEZVOZMEZDNOE_POLZOVANIE` | 2026-11-02 | 1 |
| Лизинг | [lizing](lease/lizing.md) | развёрнутая | `RU.LEASE.LIZING` | 2026-11-02 | 1 |
| Аренда земельного участка | [arenda-zemel-nogo-uchastka](lease/arenda-zemel-nogo-uchastka.md) | короткая | `RU.TEMPORARY_POSSESSION_USE.ARENDA_ZEMEL_NOGO_UCHASTKA` | 2026-11-10 | 1 |
| Аренда предприятия | [arenda-predpriiatiia](lease/arenda-predpriiatiia.md) | короткая | `RU.TEMPORARY_POSSESSION_USE.ARENDA_PREDPRIIATIIA` | 2026-11-10 | 1 |
| Наем жилого помещения (коммерческий наем) | [naem-zhilogo-pomeshcheniia](lease/naem-zhilogo-pomeshcheniia.md) | короткая | `RU.TEMPORARY_POSSESSION_USE.NAEM_ZHILOGO_POMESHCHENIIA` | 2026-11-10 | 1 |
| Прокат | [prokat](lease/prokat.md) | короткая | `RU.TEMPORARY_POSSESSION_USE.PROKAT` | 2026-11-10 | 1 |
| Социальный наем / наем жилищного фонда социального использования | [sotsial-nyi-naem-naem-zhilishchnogo-fonda-sotsial-nogo-ispol-zovaniia](lease/sotsial-nyi-naem-naem-zhilishchnogo-fonda-sotsial-nogo-ispol-zovaniia.md) | короткая | `RU.TEMPORARY_POSSESSION_USE.SOTSIAL_NYI_NAEM_NAEM_ZHILISHCHNOGO_FONDA_SOTSIAL_NOGO_ISPOL_ZOVANIIA` | 2026-11-10 | 1 |

## Посредничество и совместная деятельность (`intermediation`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Агентский договор | [agentskii-dogovor](intermediation/agentskii-dogovor.md) | развёрнутая | `RU.INTERMEDIATION.AGENTSKII_DOGOVOR` | 2026-11-02 | 1 |
| Дистрибуция | [distributsiia](intermediation/distributsiia.md) | развёрнутая | `RU.INTERMEDIATION.DISTRIBUTSIIA` | 2026-11-02 | 1 |
| Комиссия | [komissiia](intermediation/komissiia.md) | развёрнутая | `RU.INTERMEDIATION.KOMISSIIA` | 2026-11-02 | 1 |
| Поручение | [poruchenie](intermediation/poruchenie.md) | развёрнутая | `RU.INTERMEDIATION.PORUCHENIE` | 2026-11-01 | 1 |
| Действия в чужом интересе без поручения | [deistviia-v-chuzhom-interese-bez-porucheniia](intermediation/deistviia-v-chuzhom-interese-bez-porucheniia.md) | короткая | `RU.INTERMEDIATION_MANAGEMENT_JOINT_ACTIVITY.DEISTVIIA_V_CHUZHOM_INTERESE_BEZ_PORUCHENIIA` | 2026-11-10 | 1 |
| Доверительное управление имуществом | [doveritel-noe-upravlenie-imushchestvom](intermediation/doveritel-noe-upravlenie-imushchestvom.md) | короткая | `RU.INTERMEDIATION_MANAGEMENT_JOINT_ACTIVITY.DOVERITEL_NOE_UPRAVLENIE_IMUSHCHESTVOM` | 2026-11-10 | 1 |
| Простое товарищество / совместная деятельность | [prostoe-tovarishchestvo-sovmestnaia-deiatel-nost](intermediation/prostoe-tovarishchestvo-sovmestnaia-deiatel-nost.md) | короткая | `RU.INTERMEDIATION_MANAGEMENT_JOINT_ACTIVITY.PROSTOE_TOVARISHCHESTVO_SOVMESTNAIA_DEIATEL_NOST` | 2026-11-10 | 1 |

## Коммерческая концессия (`commercial_concession`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Коммерческая концессия | [kommercheskaia-kontsessiia](commercial_concession/kommercheskaia-kontsessiia.md) | развёрнутая | `RU.IP.KOMMERCHESKAIA_KONTSESSIIA` | 2026-11-09 | 1 |

## Перевозка, экспедиция, хранение (`logistics`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Перевозка груза | [perevozka-gruza](logistics/perevozka-gruza.md) | развёрнутая | `RU.LOGISTICS.PEREVOZKA_GRUZA` | 2026-11-05 | 1 |
| Перевозка пассажиров и фрахтование для перевозки работников | [perevozka-passazhira](logistics/perevozka-passazhira.md) | развёрнутая | `RU.LOGISTICS.PEREVOZKA_PASSAZHIRA` | 2026-11-09 | 1 |
| Транспортная экспедиция | [transportnaia-ekspeditsiia](logistics/transportnaia-ekspeditsiia.md) | развёрнутая | `RU.LOGISTICS.TRANSPORTNAIA_EKSPEDITSIIA` | 2026-11-05 | 1 |
| Хранение | [hranenie](logistics/hranenie.md) | развёрнутая | `RU.LOGISTICS.KHRANENIE` | 2026-11-05 | 1 |
| Буксировка | [buksirovka](logistics/buksirovka.md) | короткая | `RU.TRANSPORT_LOGISTICS.BUKSIROVKA` | 2026-11-10 | 1 |
| Договор условного депонирования (эскроу) | [dogovor-uslovnogo-deponirovaniia](logistics/dogovor-uslovnogo-deponirovaniia.md) | короткая | `RU.STORAGE_ESCROW_INSURANCE.DOGOVOR_USLOVNOGO_DEPONIROVANIIA` | 2026-11-10 | 1 |
| Договоры эксплуатации подъездных путей / подачи и уборки вагонов | [dogovory-ekspluatatsii-pod-ezdnykh-putei-podachi-i-uborki-vagonov](logistics/dogovory-ekspluatatsii-pod-ezdnykh-putei-podachi-i-uborki-vagonov.md) | короткая | `RU.TRANSPORT_LOGISTICS.DOGOVORY_EKSPLUATATSII_POD_EZDNYKH_PUTEI_PODACHI_I_UBORKI_VAGONOV` | 2026-11-10 | 1 |
| Прямое смешанное сообщение | [priamoe-smeshannoe-soobshchenie](logistics/priamoe-smeshannoe-soobshchenie.md) | короткая | `RU.TRANSPORT_LOGISTICS.PRIAMOE_SMESHANNOE_SOOBSHCHENIE` | 2026-11-10 | 1 |
| Соглашения между транспортными организациями об организации перевозок | [soglasheniia-mezhdu-transportnymi-organizatsiiami-ob-organizatsii-perevozok](logistics/soglasheniia-mezhdu-transportnymi-organizatsiiami-ob-organizatsii-perevozok.md) | короткая | `RU.TRANSPORT_LOGISTICS.SOGLASHENIIA_MEZHDU_TRANSPORTNYMI_ORGANIZATSIIAMI_OB_ORGANIZATSII_PEREVOZOK` | 2026-11-10 | 1 |
| Хранение в гостинице | [khranenie-v-gostinitse](logistics/khranenie-v-gostinitse.md) | короткая | `RU.STORAGE_ESCROW_INSURANCE.KHRANENIE_V_GOSTINITSE` | 2026-11-10 | 1 |
| Хранение в камерах хранения транспортных организаций | [khranenie-v-kamerakh-khraneniia-transportnykh-organizatsii](logistics/khranenie-v-kamerakh-khraneniia-transportnykh-organizatsii.md) | короткая | `RU.STORAGE_ESCROW_INSURANCE.KHRANENIE_V_KAMERAKH_KHRANENIIA_TRANSPORTNYKH_ORGANIZATSII` | 2026-11-10 | 1 |
| Хранение ценностей в банке | [khranenie-tsennostei-v-banke](logistics/khranenie-tsennostei-v-banke.md) | короткая | `RU.STORAGE_ESCROW_INSURANCE.KHRANENIE_TSENNOSTEI_V_BANKE` | 2026-11-10 | 1 |
| Централизованный завоз/вывоз грузов | [tsentralizovannyi-zavoz-vyvoz-gruzov](logistics/tsentralizovannyi-zavoz-vyvoz-gruzov.md) | короткая | `RU.TRANSPORT_LOGISTICS.TSENTRALIZOVANNYI_ZAVOZ_VYVOZ_GRUZOV` | 2026-11-10 | 1 |

## Финансы и расчёты (`finance`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Заём (с товарным и коммерческим кредитом) | [zaem](finance/zaem.md) | развёрнутая | `RU.FINANCE.ZAEM` | 2026-11-05 | 1 |
| Кредитный договор | [kreditnyi-dogovor](finance/kreditnyi-dogovor.md) | развёрнутая | `RU.FINANCE.KREDITNYI_DOGOVOR` | 2026-11-05 | 1 |
| Финансирование под уступку денежного требования (факторинг) | [faktoring](finance/faktoring.md) | развёрнутая | `RU.FINANCE.FAKTORING` | 2026-11-06 | 1 |
| Банковский вклад (депозит) | [bankovskii-vklad](finance/bankovskii-vklad.md) | короткая | `RU.FINANCE_BANKING.BANKOVSKII_VKLAD` | 2026-11-10 | 1 |
| Банковский счет | [bankovskii-schet](finance/bankovskii-schet.md) | короткая | `RU.FINANCE_BANKING.BANKOVSKII_SCHET` | 2026-11-10 | 1 |
| Государственный / муниципальный заем | [gosudarstvennyi-munitsipal-nyi-zaem](finance/gosudarstvennyi-munitsipal-nyi-zaem.md) | короткая | `RU.FINANCE_BANKING.GOSUDARSTVENNYI_MUNITSIPAL_NYI_ZAEM` | 2026-11-10 | 1 |
| Облигационный заем | [obligatsionnyi-zaem](finance/obligatsionnyi-zaem.md) | короткая | `RU.FINANCE_BANKING.OBLIGATSIONNYI_ZAEM` | 2026-11-10 | 1 |
| Потребительский кредит (заем) | [potrebitel-skii-kredit](finance/potrebitel-skii-kredit.md) | короткая | `RU.FINANCE_BANKING.POTREBITEL_SKII_KREDIT` | 2026-11-10 | 1 |
| Расчеты платежными поручениями | [raschety-platezhnymi-porucheniiami](finance/raschety-platezhnymi-porucheniiami.md) | короткая | `RU.FINANCE_BANKING.RASCHETY_PLATEZHNYMI_PORUCHENIIAMI` | 2026-11-10 | 1 |
| Расчеты по аккредитиву | [raschety-po-akkreditivu](finance/raschety-po-akkreditivu.md) | короткая | `RU.FINANCE_BANKING.RASCHETY_PO_AKKREDITIVU` | 2026-11-10 | 1 |
| Расчеты по инкассо | [raschety-po-inkasso](finance/raschety-po-inkasso.md) | короткая | `RU.FINANCE_BANKING.RASCHETY_PO_INKASSO` | 2026-11-10 | 1 |
| Расчеты чеками | [raschety-chekami](finance/raschety-chekami.md) | короткая | `RU.FINANCE_BANKING.RASCHETY_CHEKAMI` | 2026-11-10 | 1 |
| Счет эскроу | [schet-eskrou](finance/schet-eskrou.md) | короткая | `RU.FINANCE_BANKING.SCHET_ESKROU` | 2026-11-10 | 1 |

## Страхование (`insurance`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Имущественное страхование и общие положения о страховании | [imushchestvennoe-strakhovanie](insurance/imushchestvennoe-strakhovanie.md) | развёрнутая | `RU.INSURANCE.IMUSHCHESTVENNOE_STRAKHOVANIE` | 2026-11-06 | 1 |
| Личное страхование | [lichnoe-strakhovanie](insurance/lichnoe-strakhovanie.md) | развёрнутая | `RU.INSURANCE.LICHNOE_STRAKHOVANIE` | 2026-11-06 | 1 |

## Интеллектуальная собственность (`intellectual_property`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Договор об отчуждении исключительного права | [otchuzhdenie-iskliuchitelnogo-prava](intellectual_property/otchuzhdenie-iskliuchitelnogo-prava.md) | развёрнутая | `RU.IP.OTCHUZHDENIE_ISKLIUCHITELNOGO_PRAVA` | 2026-11-10 | 1 |
| Договоры с авторами | [dogovory-s-avtorami](intellectual_property/dogovory-s-avtorami.md) | развёрнутая | `RU.IP.DOGOVORY_S_AVTORAMI` | 2026-11-10 | 1 |
| Лицензионный договор | [litsenzionnyi-dogovor](intellectual_property/litsenzionnyi-dogovor.md) | развёрнутая | `RU.IP.LITSENZIONNYI_DOGOVOR` | 2026-11-10 | 1 |

## Корпоративные, смешанные, непоименованные (`corporate_mixed_unnamed`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Соглашение о конфиденциальности (NDA) | [nda](corporate_mixed_unnamed/nda.md) | развёрнутая | `RU.UNNAMED.NDA` | 2026-11-09 | 1 |
| Договор о создании АО | [dogovor-o-sozdanii-ao](corporate_mixed_unnamed/dogovor-o-sozdanii-ao.md) | короткая | `RU.CORPORATE_MIXED_UNNAMED.DOGOVOR_O_SOZDANII_AO` | 2026-11-10 | 1 |
| Договор об учреждении ООО | [dogovor-ob-uchrezhdenii-ooo](corporate_mixed_unnamed/dogovor-ob-uchrezhdenii-ooo.md) | короткая | `RU.CORPORATE_MIXED_UNNAMED.DOGOVOR_OB_UCHREZHDENII_OOO` | 2026-11-10 | 1 |
| Инвестиционное / партнерское соглашение (общая коммерческая модель) | [investitsionnoe-partnerskoe-soglashenie](corporate_mixed_unnamed/investitsionnoe-partnerskoe-soglashenie.md) | короткая | `RU.CORPORATE_MIXED_UNNAMED.INVESTITSIONNOE_PARTNERSKOE_SOGLASHENIE` | 2026-11-10 | 2 |
| Корпоративный договор | [korporativnyi-dogovor](corporate_mixed_unnamed/korporativnyi-dogovor.md) | короткая | `RU.CORPORATE_MIXED_UNNAMED.KORPORATIVNYI_DOGOVOR` | 2026-11-10 | 1 |

## Смежные институты (`adjacent_obligations`)

| Договор | Карточка | Вид | `id` | Проверено | Маркеров |
|---|---|---|---|---|---|
| Игры и пари | [igry-i-pari](adjacent_obligations/igry-i-pari.md) | короткая | `RU.ADJACENT_OBLIGATIONS.IGRY_I_PARI` | 2026-11-10 | 1 |
| Публичное обещание награды | [publichnoe-obeshchanie-nagrady](adjacent_obligations/publichnoe-obeshchanie-nagrady.md) | короткая | `RU.ADJACENT_OBLIGATIONS.PUBLICHNOE_OBESHCHANIE_NAGRADY` | 2026-11-10 | 1 |
| Публичный конкурс | [publichnyi-konkurs](adjacent_obligations/publichnyi-konkurs.md) | короткая | `RU.ADJACENT_OBLIGATIONS.PUBLICHNYI_KONKURS` | 2026-11-10 | 1 |

## Прежние идентификаторы

Прежний `contract_id` ведёт на карточку, которая теперь покрывает тему.

| Прежний `contract_id` | Прежнее название | Карточка |
|---|---|---|
| `RU.ADJACENT_OBLIGATIONS.IGRY_I_PARI` | Игры и пари | [igry-i-pari](adjacent_obligations/igry-i-pari.md) |
| `RU.ADJACENT_OBLIGATIONS.PUBLICHNOE_OBESHCHANIE_NAGRADY` | Публичное обещание награды | [publichnoe-obeshchanie-nagrady](adjacent_obligations/publichnoe-obeshchanie-nagrady.md) |
| `RU.ADJACENT_OBLIGATIONS.PUBLICHNYI_KONKURS` | Публичный конкурс | [publichnyi-konkurs](adjacent_obligations/publichnyi-konkurs.md) |
| `RU.CORPORATE_MIXED_UNNAMED.DISTRIBUTSIIA_DILERSKII_DOGOVOR` | Дистрибуция / дилерский договор | [distributsiia](intermediation/distributsiia.md) |
| `RU.CORPORATE_MIXED_UNNAMED.DOGOVOR_O_SOZDANII_AO` | Договор о создании АО | [dogovor-o-sozdanii-ao](corporate_mixed_unnamed/dogovor-o-sozdanii-ao.md) |
| `RU.CORPORATE_MIXED_UNNAMED.DOGOVOR_OB_UCHREZHDENII_OOO` | Договор об учреждении ООО | [dogovor-ob-uchrezhdenii-ooo](corporate_mixed_unnamed/dogovor-ob-uchrezhdenii-ooo.md) |
| `RU.CORPORATE_MIXED_UNNAMED.INVESTITSIONNOE_PARTNERSKOE_SOGLASHENIE` | Инвестиционное / партнерское соглашение (общая коммерческая модель) | [investitsionnoe-partnerskoe-soglashenie](corporate_mixed_unnamed/investitsionnoe-partnerskoe-soglashenie.md) |
| `RU.CORPORATE_MIXED_UNNAMED.KORPORATIVNYI_DOGOVOR` | Корпоративный договор | [korporativnyi-dogovor](corporate_mixed_unnamed/korporativnyi-dogovor.md) |
| `RU.CORPORATE_MIXED_UNNAMED.MSA_SOW_ZAKAZNAIA_MODEL` | MSA + SOW / заказная модель | [ramochnyi-dogovor](general/ramochnyi-dogovor.md) |
| `RU.CORPORATE_MIXED_UNNAMED.NDA_SOGLASHENIE_O_KONFIDENTSIAL_NOSTI` | NDA / соглашение о конфиденциальности | [nda](corporate_mixed_unnamed/nda.md) |
| `RU.FINANCE_BANKING.BANKOVSKII_SCHET` | Банковский счет | [bankovskii-schet](finance/bankovskii-schet.md) |
| `RU.FINANCE_BANKING.BANKOVSKII_VKLAD` | Банковский вклад (депозит) | [bankovskii-vklad](finance/bankovskii-vklad.md) |
| `RU.FINANCE_BANKING.FAKTORING` | Факторинг | [faktoring](finance/faktoring.md) |
| `RU.FINANCE_BANKING.GOSUDARSTVENNYI_MUNITSIPAL_NYI_ZAEM` | Государственный / муниципальный заем | [gosudarstvennyi-munitsipal-nyi-zaem](finance/gosudarstvennyi-munitsipal-nyi-zaem.md) |
| `RU.FINANCE_BANKING.KOMMERCHESKII_KREDIT` | Коммерческий кредит | [zaem](finance/zaem.md) |
| `RU.FINANCE_BANKING.KREDIT` | Кредит | [kreditnyi-dogovor](finance/kreditnyi-dogovor.md) |
| `RU.FINANCE_BANKING.OBLIGATSIONNYI_ZAEM` | Облигационный заем | [obligatsionnyi-zaem](finance/obligatsionnyi-zaem.md) |
| `RU.FINANCE_BANKING.POTREBITEL_SKII_KREDIT` | Потребительский кредит (заем) | [potrebitel-skii-kredit](finance/potrebitel-skii-kredit.md) |
| `RU.FINANCE_BANKING.RASCHETY_CHEKAMI` | Расчеты чеками | [raschety-chekami](finance/raschety-chekami.md) |
| `RU.FINANCE_BANKING.RASCHETY_PLATEZHNYMI_PORUCHENIIAMI` | Расчеты платежными поручениями | [raschety-platezhnymi-porucheniiami](finance/raschety-platezhnymi-porucheniiami.md) |
| `RU.FINANCE_BANKING.RASCHETY_PO_AKKREDITIVU` | Расчеты по аккредитиву | [raschety-po-akkreditivu](finance/raschety-po-akkreditivu.md) |
| `RU.FINANCE_BANKING.RASCHETY_PO_INKASSO` | Расчеты по инкассо | [raschety-po-inkasso](finance/raschety-po-inkasso.md) |
| `RU.FINANCE_BANKING.SCHET_ESKROU` | Счет эскроу | [schet-eskrou](finance/schet-eskrou.md) |
| `RU.FINANCE_BANKING.TOVARNYI_KREDIT` | Товарный кредит | [zaem](finance/zaem.md) |
| `RU.FINANCE_BANKING.ZAEM` | Заем | [zaem](finance/zaem.md) |
| `RU.GENERAL_CONSTRUCTIONS.ABONENTSKII_DOGOVOR` | Абонентский договор | [zakliuchenie-dogovora](general/zakliuchenie-dogovora.md) |
| `RU.GENERAL_CONSTRUCTIONS.OPTSION_NA_ZAKLIUCHENIE_DOGOVORA` | Опцион на заключение договора | [zakliuchenie-dogovora](general/zakliuchenie-dogovora.md) |
| `RU.GENERAL_CONSTRUCTIONS.OPTSIONNYI_DOGOVOR` | Опционный договор | [optsionnyi-dogovor](general/optsionnyi-dogovor.md) |
| `RU.GENERAL_CONSTRUCTIONS.PREDVARITEL_NYI_DOGOVOR` | Предварительный договор | [zakliuchenie-dogovora](general/zakliuchenie-dogovora.md) |
| `RU.GENERAL_CONSTRUCTIONS.RAMOCHNYI_DOGOVOR` | Рамочный договор (framework / MSA) | [ramochnyi-dogovor](general/ramochnyi-dogovor.md) |
| `RU.INTELLECTUAL_PROPERTY.AVTORSKII_ZAKAZ` | Авторский заказ | [dogovory-s-avtorami](intellectual_property/dogovory-s-avtorami.md) |
| `RU.INTELLECTUAL_PROPERTY.LITSENZIIA_NA_NOU_KHAU` | Лицензия на ноу-хау (секрет производства) | [litsenzionnyi-dogovor](intellectual_property/litsenzionnyi-dogovor.md) |
| `RU.INTELLECTUAL_PROPERTY.LITSENZIIA_NA_TOVARNYI_ZNAK` | Лицензия на товарный знак | [litsenzionnyi-dogovor](intellectual_property/litsenzionnyi-dogovor.md) |
| `RU.INTELLECTUAL_PROPERTY.LITSENZIONNYI_DOGOVOR` | Лицензионный договор (общая модель) | [litsenzionnyi-dogovor](intellectual_property/litsenzionnyi-dogovor.md) |
| `RU.INTELLECTUAL_PROPERTY.OTCHUZHDENIE_ISKLIUCHITEL_NOGO_PRAVA` | Отчуждение исключительного права | [otchuzhdenie-iskliuchitelnogo-prava](intellectual_property/otchuzhdenie-iskliuchitelnogo-prava.md) |
| `RU.INTELLECTUAL_PROPERTY.SUBLITSENZIIA` | Сублицензия | [litsenzionnyi-dogovor](intellectual_property/litsenzionnyi-dogovor.md) |
| `RU.INTERMEDIATION_MANAGEMENT_JOINT_ACTIVITY.AGENTIROVANIE` | Агентирование | [agentskii-dogovor](intermediation/agentskii-dogovor.md) |
| `RU.INTERMEDIATION_MANAGEMENT_JOINT_ACTIVITY.DEISTVIIA_V_CHUZHOM_INTERESE_BEZ_PORUCHENIIA` | Действия в чужом интересе без поручения | [deistviia-v-chuzhom-interese-bez-porucheniia](intermediation/deistviia-v-chuzhom-interese-bez-porucheniia.md) |
| `RU.INTERMEDIATION_MANAGEMENT_JOINT_ACTIVITY.DOVERITEL_NOE_UPRAVLENIE_IMUSHCHESTVOM` | Доверительное управление имуществом | [doveritel-noe-upravlenie-imushchestvom](intermediation/doveritel-noe-upravlenie-imushchestvom.md) |
| `RU.INTERMEDIATION_MANAGEMENT_JOINT_ACTIVITY.KOMISSIIA` | Комиссия | [komissiia](intermediation/komissiia.md) |
| `RU.INTERMEDIATION_MANAGEMENT_JOINT_ACTIVITY.KOMMERCHESKAIA_KONTSESSIIA` | Коммерческая концессия (франчайзинг по ГК) | [kommercheskaia-kontsessiia](commercial_concession/kommercheskaia-kontsessiia.md) |
| `RU.INTERMEDIATION_MANAGEMENT_JOINT_ACTIVITY.PORUCHENIE` | Поручение | [poruchenie](intermediation/poruchenie.md) |
| `RU.INTERMEDIATION_MANAGEMENT_JOINT_ACTIVITY.PROSTOE_TOVARISHCHESTVO_SOVMESTNAIA_DEIATEL_NOST` | Простое товарищество / совместная деятельность | [prostoe-tovarishchestvo-sovmestnaia-deiatel-nost](intermediation/prostoe-tovarishchestvo-sovmestnaia-deiatel-nost.md) |
| `RU.PROPERTY_TRANSFER.DARENIE` | Дарение | [darenie-pozhertvovanie](property_transfer/darenie-pozhertvovanie.md) |
| `RU.PROPERTY_TRANSFER.ENERGOSNABZHENIE_ROZNICHNYI_RYNOK_ELEKTROENERGII` | Энергоснабжение / розничный рынок электроэнергии | [energosnabzhenie](property_transfer/energosnabzhenie.md) |
| `RU.PROPERTY_TRANSFER.KONTRAKTATSIIA` | Контрактация | [kontraktatsiia](property_transfer/kontraktatsiia.md) |
| `RU.PROPERTY_TRANSFER.KUPLIA_PRODAZHA` | Купля-продажа (общая) | [kuplia-prodazha](property_transfer/kuplia-prodazha.md) |
| `RU.PROPERTY_TRANSFER.MENA` | Мена | [mena](property_transfer/mena.md) |
| `RU.PROPERTY_TRANSFER.POSTAVKA` | Поставка | [postavka](property_transfer/postavka.md) |
| `RU.PROPERTY_TRANSFER.POSTOIANNAIA_RENTA` | Постоянная рента | [postoiannaia-renta](property_transfer/postoiannaia-renta.md) |
| `RU.PROPERTY_TRANSFER.POZHIZNENNAIA_RENTA` | Пожизненная рента | [pozhiznennaia-renta](property_transfer/pozhiznennaia-renta.md) |
| `RU.PROPERTY_TRANSFER.POZHIZNENNOE_SODERZHANIE_S_IZHDIVENIEM` | Пожизненное содержание с иждивением | [pozhiznennoe-soderzhanie-s-izhdiveniem](property_transfer/pozhiznennoe-soderzhanie-s-izhdiveniem.md) |
| `RU.PROPERTY_TRANSFER.PRODAZHA_NEDVIZHIMOSTI` | Продажа недвижимости | [prodazha-nedvizhimosti](property_transfer/prodazha-nedvizhimosti.md) |
| `RU.PROPERTY_TRANSFER.PRODAZHA_PREDPRIIATIIA` | Продажа предприятия | [prodazha-nedvizhimosti](property_transfer/prodazha-nedvizhimosti.md) |
| `RU.PROPERTY_TRANSFER.PRODAZHA_ZHILOGO_POMESHCHENIIA_S_SOKHRANIAIUSHCHIMI_PRAVO_POL_ZOVANIIA_LITSAMI` | Продажа жилого помещения с сохраняющими право пользования лицами | [prodazha-nedvizhimosti](property_transfer/prodazha-nedvizhimosti.md) |
| `RU.PROPERTY_TRANSFER.ROZNICHNAIA_KUPLIA_PRODAZHA` | Розничная купля-продажа | [roznichnaia-kuplia-prodazha](property_transfer/roznichnaia-kuplia-prodazha.md) |
| `RU.SECURITY_CHANGE_OF_PARTIES.NEUSTOIKA` | Неустойка (соглашение о неустойке) | [otvetstvennost](general/otvetstvennost.md) |
| `RU.SECURITY_CHANGE_OF_PARTIES.NEZAVISIMAIA_GARANTIIA` | Независимая гарантия | [obespechenie](general/obespechenie.md) |
| `RU.SECURITY_CHANGE_OF_PARTIES.OBESPECHITEL_NYI_PLATEZH` | Обеспечительный платеж | [obespechenie](general/obespechenie.md) |
| `RU.SECURITY_CHANGE_OF_PARTIES.PEREDACHA_DOGOVORA` | Передача договора | [ustupka-perevod-dolga](general/ustupka-perevod-dolga.md) |
| `RU.SECURITY_CHANGE_OF_PARTIES.PEREVOD_DOLGA` | Перевод долга | [ustupka-perevod-dolga](general/ustupka-perevod-dolga.md) |
| `RU.SECURITY_CHANGE_OF_PARTIES.PORUCHITEL_STVO` | Поручительство | [obespechenie](general/obespechenie.md) |
| `RU.SECURITY_CHANGE_OF_PARTIES.USTUPKA_TREBOVANIIA` | Уступка требования (цессия) | [ustupka-perevod-dolga](general/ustupka-perevod-dolga.md) |
| `RU.SECURITY_CHANGE_OF_PARTIES.ZADATOK` | Задаток | [obespechenie](general/obespechenie.md) |
| `RU.SECURITY_CHANGE_OF_PARTIES.ZALOG` | Залог | [obespechenie](general/obespechenie.md) |
| `RU.STORAGE_ESCROW_INSURANCE.DOGOVOR_USLOVNOGO_DEPONIROVANIIA` | Договор условного депонирования (эскроу) | [dogovor-uslovnogo-deponirovaniia](logistics/dogovor-uslovnogo-deponirovaniia.md) |
| `RU.STORAGE_ESCROW_INSURANCE.IMUSHCHESTVENNOE_STRAKHOVANIE` | Имущественное страхование | [imushchestvennoe-strakhovanie](insurance/imushchestvennoe-strakhovanie.md) |
| `RU.STORAGE_ESCROW_INSURANCE.INDIVIDUAL_NYI_BANKOVSKII_SEIF` | Индивидуальный банковский сейф | [hranenie](logistics/hranenie.md) |
| `RU.STORAGE_ESCROW_INSURANCE.KHRANENIE_TSENNOSTEI_V_BANKE` | Хранение ценностей в банке | [khranenie-tsennostei-v-banke](logistics/khranenie-tsennostei-v-banke.md) |
| `RU.STORAGE_ESCROW_INSURANCE.KHRANENIE_V_GOSTINITSE` | Хранение в гостинице | [khranenie-v-gostinitse](logistics/khranenie-v-gostinitse.md) |
| `RU.STORAGE_ESCROW_INSURANCE.KHRANENIE_V_KAMERAKH_KHRANENIIA_TRANSPORTNYKH_ORGANIZATSII` | Хранение в камерах хранения транспортных организаций | [khranenie-v-kamerakh-khraneniia-transportnykh-organizatsii](logistics/khranenie-v-kamerakh-khraneniia-transportnykh-organizatsii.md) |
| `RU.STORAGE_ESCROW_INSURANCE.KHRANENIE_V_LOMBARDE` | Хранение в ломбарде | [hranenie](logistics/hranenie.md) |
| `RU.STORAGE_ESCROW_INSURANCE.KHRANENIE` | Хранение (общая модель) | [hranenie](logistics/hranenie.md) |
| `RU.STORAGE_ESCROW_INSURANCE.LICHNOE_STRAKHOVANIE` | Личное страхование | [lichnoe-strakhovanie](insurance/lichnoe-strakhovanie.md) |
| `RU.STORAGE_ESCROW_INSURANCE.SEKVESTR` | Секвестр | [hranenie](logistics/hranenie.md) |
| `RU.STORAGE_ESCROW_INSURANCE.SKLADSKOE_KHRANENIE` | Складское хранение | [hranenie](logistics/hranenie.md) |
| `RU.TEMPORARY_POSSESSION_USE.ARENDA_PREDPRIIATIIA` | Аренда предприятия | [arenda-predpriiatiia](lease/arenda-predpriiatiia.md) |
| `RU.TEMPORARY_POSSESSION_USE.ARENDA_TRANSPORTNOGO_SREDSTVA_BEZ_EKIPAZHA` | Аренда транспортного средства без экипажа | [arenda](lease/arenda.md) |
| `RU.TEMPORARY_POSSESSION_USE.ARENDA_TRANSPORTNOGO_SREDSTVA_S_EKIPAZHEM` | Аренда транспортного средства с экипажем | [arenda](lease/arenda.md) |
| `RU.TEMPORARY_POSSESSION_USE.ARENDA_ZDANIIA_SOORUZHENIIA_NEZHILOGO_POMESHCHENIIA` | Аренда здания/сооружения/нежилого помещения | [arenda-zdanii-pomeshchenii](lease/arenda-zdanii-pomeshchenii.md) |
| `RU.TEMPORARY_POSSESSION_USE.ARENDA_ZEMEL_NOGO_UCHASTKA` | Аренда земельного участка | [arenda-zemel-nogo-uchastka](lease/arenda-zemel-nogo-uchastka.md) |
| `RU.TEMPORARY_POSSESSION_USE.ARENDA` | Аренда (общая) | [arenda](lease/arenda.md) |
| `RU.TEMPORARY_POSSESSION_USE.BEZVOZMEZDNOE_POL_ZOVANIE` | Безвозмездное пользование (ссуда) | [bezvozmezdnoe-polzovanie](lease/bezvozmezdnoe-polzovanie.md) |
| `RU.TEMPORARY_POSSESSION_USE.FINANSOVAIA_ARENDA` | Финансовая аренда (лизинг) | [lizing](lease/lizing.md) |
| `RU.TEMPORARY_POSSESSION_USE.NAEM_ZHILOGO_POMESHCHENIIA` | Наем жилого помещения (коммерческий наем) | [naem-zhilogo-pomeshcheniia](lease/naem-zhilogo-pomeshcheniia.md) |
| `RU.TEMPORARY_POSSESSION_USE.PROKAT` | Прокат | [prokat](lease/prokat.md) |
| `RU.TEMPORARY_POSSESSION_USE.SOTSIAL_NYI_NAEM_NAEM_ZHILISHCHNOGO_FONDA_SOTSIAL_NOGO_ISPOL_ZOVANIIA` | Социальный наем / наем жилищного фонда социального использования | [sotsial-nyi-naem-naem-zhilishchnogo-fonda-sotsial-nogo-ispol-zovaniia](lease/sotsial-nyi-naem-naem-zhilishchnogo-fonda-sotsial-nogo-ispol-zovaniia.md) |
| `RU.TRANSPORT_LOGISTICS.BUKSIROVKA` | Буксировка | [buksirovka](logistics/buksirovka.md) |
| `RU.TRANSPORT_LOGISTICS.DOGOVORY_EKSPLUATATSII_POD_EZDNYKH_PUTEI_PODACHI_I_UBORKI_VAGONOV` | Договоры эксплуатации подъездных путей / подачи и уборки вагонов | [dogovory-ekspluatatsii-pod-ezdnykh-putei-podachi-i-uborki-vagonov](logistics/dogovory-ekspluatatsii-pod-ezdnykh-putei-podachi-i-uborki-vagonov.md) |
| `RU.TRANSPORT_LOGISTICS.FRAKHTOVANIE` | Фрахтование (чартер) | [perevozka-passazhira](logistics/perevozka-passazhira.md) |
| `RU.TRANSPORT_LOGISTICS.ORGANIZATSIIA_PEREVOZOK` | Организация перевозок | [perevozka-gruza](logistics/perevozka-gruza.md) |
| `RU.TRANSPORT_LOGISTICS.PEREVOZKA_GRUZA` | Перевозка груза | [perevozka-gruza](logistics/perevozka-gruza.md) |
| `RU.TRANSPORT_LOGISTICS.PEREVOZKA_PASSAZHIRA_I_BAGAZHA` | Перевозка пассажира и багажа | [perevozka-passazhira](logistics/perevozka-passazhira.md) |
| `RU.TRANSPORT_LOGISTICS.PRIAMOE_SMESHANNOE_SOOBSHCHENIE` | Прямое смешанное сообщение | [priamoe-smeshannoe-soobshchenie](logistics/priamoe-smeshannoe-soobshchenie.md) |
| `RU.TRANSPORT_LOGISTICS.SOGLASHENIIA_MEZHDU_TRANSPORTNYMI_ORGANIZATSIIAMI_OB_ORGANIZATSII_PEREVOZOK` | Соглашения между транспортными организациями об организации перевозок | [soglasheniia-mezhdu-transportnymi-organizatsiiami-ob-organizatsii-perevozok](logistics/soglasheniia-mezhdu-transportnymi-organizatsiiami-ob-organizatsii-perevozok.md) |
| `RU.TRANSPORT_LOGISTICS.TRANSPORTNAIA_EKSPEDITSIIA` | Транспортная экспедиция | [transportnaia-ekspeditsiia](logistics/transportnaia-ekspeditsiia.md) |
| `RU.TRANSPORT_LOGISTICS.TSENTRALIZOVANNYI_ZAVOZ_VYVOZ_GRUZOV` | Централизованный завоз/вывоз грузов | [tsentralizovannyi-zavoz-vyvoz-gruzov](logistics/tsentralizovannyi-zavoz-vyvoz-gruzov.md) |
| `RU.WORKS_RESEARCH_SERVICES.BYTOVOI_PODRIAD` | Бытовой подряд | [bytovoi-podriad](works_services/bytovoi-podriad.md) |
| `RU.WORKS_RESEARCH_SERVICES.INFORMATSIONNYE_USLUGI` | Информационные услуги | [uslugi](works_services/uslugi.md) |
| `RU.WORKS_RESEARCH_SERVICES.NIR` | НИР | [niokr](works_services/niokr.md) |
| `RU.WORKS_RESEARCH_SERVICES.OKR_TEKHNOLOGICHESKIE_RABOTY` | ОКР / технологические работы | [niokr](works_services/niokr.md) |
| `RU.WORKS_RESEARCH_SERVICES.PODRIAD` | Подряд (общий) | [podriad](works_services/podriad.md) |
| `RU.WORKS_RESEARCH_SERVICES.PROEKTNYE_I_IZYSKATEL_SKIE_RABOTY` | Проектные и изыскательские работы | [stroitelnyi-podriad](works_services/stroitelnyi-podriad.md) |
| `RU.WORKS_RESEARCH_SERVICES.STROITEL_NYI_PODRIAD` | Строительный подряд | [stroitelnyi-podriad](works_services/stroitelnyi-podriad.md) |
| `RU.WORKS_RESEARCH_SERVICES.VOZMEZDNOE_OKAZANIE_USLUG` | Возмездное оказание услуг (общая модель) | [uslugi](works_services/uslugi.md) |
