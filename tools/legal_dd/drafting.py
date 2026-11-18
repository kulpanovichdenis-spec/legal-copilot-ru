def suggest_document_package(project):
    intake=project.get("intake",{})
    assets=set(intake.get("assets_in_scope") or [])
    model=intake.get("transfer_model")
    package=[]
    if project.get("transaction_type")=="share" or intake.get("transaction_type")=="share":
        package.append("share_purchase_agreement")
    else:
        package.append("asset_purchase_or_master_transfer_agreement")
    if model in {"exclusive_licence","nonexclusive_licence"}:
        package.append("licence_agreement")
    if assets & {"trademarks","patents","copyright_design","domains","web_content"}:
        package.append("IP_transfer_schedule_or_agreement")
    if "registration_rights" in assets or "regulatory_dossier" in assets:
        package.append("regulatory_asset_schedule")
    if intake.get("postdeal_supply")=="yes":
        package.append("supply_or_manufacturing_agreement")
        package.append("quality_agreement")
    if intake.get("tech_transfer")=="yes":
        package.append("technology_transfer_agreement_or_schedule")
    if "medicinal_product" in set(intake.get("product_types") or []):
        package.append("PV_transition_agreement_or_annex")
    return list(dict.fromkeys(package))
