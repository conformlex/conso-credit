"""Written rationale for a credit decision.

Two paths coexist, distinguished by `decision.decided_by`:

* `rule_engine` — deterministic template driven by the coded reasons. Covers the
  volume and guarantees text/reason consistency.
* `llm` — written by a language model from the application summary. More natural
  register, but it must be audited: the model you train will imitate that
  register, not banking expertise.

**The rationale text itself is French**, because the artefact is a French credit
decision letter. Only the code around it is English. Three writer personas rotate
so that a thousand rationales do not read identically.

The text is accented French, and that is a data-quality requirement rather than a
typographic preference: this corpus is supervision material, so a model trained
on unaccented clauses would learn to write unaccented French. Amounts carry the
`EUR` code rather than the symbol, which is what a decision letter does.
"""

from __future__ import annotations

import random

# Reason code -> French clause. The placeholders are filled from the file.
CLAUSES = {
    "EXCESSIVE_DTI": "le taux d'endettement après opération atteint {dti:.1f} %, au-delà du seuil de 35 %",
    "COMFORTABLE_DTI": "le taux d'endettement après opération reste contenu à {dti:.1f} %",
    "LOW_RESIDUAL_INCOME": "le reste à vivre s'établit à {residual:.0f} EUR par unité de consommation, insuffisant pour le foyer",
    "AMPLE_RESIDUAL_INCOME": "le reste à vivre atteint {residual:.0f} EUR par unité de consommation",
    "HIGH_PAYMENT_SHOCK": "le saut de charge de {shock:.0f} EUR par mois est important au regard des revenus",
    "INSUFFICIENT_INCOME": "les revenus ne supportent pas le montant sollicité",
    "TOO_MUCH_VARIABLE_PAY": "la part variable des revenus est élevée et fragilise la capacité de remboursement",
    "UNDOCUMENTED_INCOME": "une partie des revenus déclarés n'est pas justifiée",
    "SOLID_INCOME": "les revenus sont stables et intégralement justifiés",
    "PRECARIOUS_CONTRACT": "le contrat de travail est précaire",
    "PROBATION_PERIOD": "l'emprunteur est en période d'essai",
    "SHORT_JOB_TENURE": "l'ancienneté professionnelle est faible ({tenure} mois)",
    "RECENT_MOVE": "l'installation dans le logement est très récente",
    "STABLE_EMPLOYMENT": "la situation professionnelle est stable ({contract}, {tenure} mois d'ancienneté)",
    "PAYMENT_INCIDENTS": "des incidents de paiement ont été relevés sur les douze derniers mois",
    "HEAVY_OVERDRAFT_USE": "le compte est resté débiteur {days} jours sur l'année",
    "LOAN_INCIDENTS": "des incidents ont été constatés sur les crédits en cours",
    "MULTIPLE_REVOLVING": "la détention de plusieurs crédits renouvelables traduit une tension de trésorerie",
    "SOLID_SAVINGS": "l'épargne disponible représente {savings:.1f} mois de charges",
    "CLEAN_HISTORY": "aucun incident n'est à signaler sur la période observée",
    "LONG_RELATIONSHIP": "la relation bancaire remonte à plus de {years} ans",
    "SALARY_DOMICILED": "les revenus sont domiciliés dans l'établissement",
    "LOANS_REPAID_CLEAN": "les crédits précédents ont été soldés sans incident",
    "SOLID_CO_BORROWER": "la présence d'un co-emprunteur renforce le dossier",
    "MEANINGFUL_DOWN_PAYMENT": "l'apport personnel de {down:.0f} EUR réduit l'exposition",
    "NO_SECURITY": "l'opération ne s'accompagne d'aucun apport ni garantie",
    "FICP_FLAG": "l'emprunteur est inscrit au FICP",
    "FCC_FLAG": "l'emprunteur est inscrit au FCC",
    "OVERRIDE_WEALTH": "le patrimoine constitué justifie une dérogation",
    "OVERRIDE_RELATIONSHIP": "l'ancienneté de la relation justifie une dérogation",
    "OVERRIDE_COMMERCIAL": "une dérogation commerciale a été accordée",
}

FAVOURABLE = {
    "COMFORTABLE_DTI", "AMPLE_RESIDUAL_INCOME", "SOLID_INCOME", "STABLE_EMPLOYMENT",
    "SOLID_SAVINGS", "CLEAN_HISTORY", "LONG_RELATIONSHIP", "SALARY_DOMICILED",
    "LOANS_REPAID_CLEAN", "SOLID_CO_BORROWER", "MEANINGFUL_DOWN_PAYMENT",
    "OVERRIDE_WEALTH", "OVERRIDE_RELATIONSHIP", "OVERRIDE_COMMERCIAL",
}

OPENINGS = {
    "underwriter": {
        "approved": "Dossier accordé.",
        "approved_with_conditions": "Accord assorti de conditions.",
        "declined": "Demande rejetée.",
        "deferred": "Décision ajournée dans l'attente de pièces complémentaires.",
    },
    "adviser": {
        "approved": "Nous donnons une suite favorable à cette demande de {purpose}.",
        "approved_with_conditions": "Nous pouvons accompagner ce projet de {purpose}, sous réserve d'aménagements.",
        "declined": "Nous ne pouvons pas donner suite à cette demande de {purpose}.",
        "deferred": "L'instruction de cette demande de {purpose} est suspendue.",
    },
    "committee": {
        "approved": "Le comité retient une position favorable.",
        "approved_with_conditions": "Le comité retient un accord conditionné.",
        "declined": "Le comité retient une position défavorable.",
        "deferred": "Le comité ajourne sa décision.",
    },
}

PURPOSE_FR = {
    "AUTO": "crédit auto", "HOME_IMPROVEMENT": "crédit travaux",
    "PERSONAL_LOAN": "prêt personnel", "REVOLVING": "réserve d'argent",
    "DEBT_CONSOLIDATION": "regroupement de crédits",
    "LEASE_TO_OWN": "location avec option d'achat",
}


def _context(app: dict) -> dict:
    ind = app["indicators"]
    return {
        "dti": ind.dti_after_pct,
        "residual": ind.residual_income_per_cu,
        "shock": ind.payment_shock,
        "savings": ind.savings_months_of_expenses,
        "tenure": app["employment"]["months_in_job"],
        "contract": app["employment"]["contract_code"],
        "years": app["application"]["_relationship_months"] // 12,
        "days": app["behaviour"]["days_overdrawn_12m"],
        "down": app["application"]["down_payment"],
        "purpose": PURPOSE_FR[app["application"]["loan_type_code"]],
        "amount": app["application"]["requested_amount"],
    }


def write(app: dict, rng: random.Random) -> str:
    """Template rationale, consistent with the coded reasons."""
    decision = app["decision"]
    ctx = _context(app)
    persona = rng.choice(["underwriter", "adviser", "committee"])

    codes = [c for c in decision["reasons"] if c in CLAUSES]
    against = [c for c in codes if c not in FAVOURABLE]
    supporting = [c for c in codes if c in FAVOURABLE]
    rng.shuffle(against)
    rng.shuffle(supporting)

    negative_outcome = decision["result"] in ("declined", "deferred")
    parts = [OPENINGS[persona][decision["result"]].format(**ctx)]

    leading = (against if negative_outcome else supporting)[:2]
    trailing = (supporting if negative_outcome else against)[:2]

    if leading:
        body = " et ".join(CLAUSES[c].format(**ctx) for c in leading)
        parts.append(f"En effet, {body}." if persona == "adviser"
                     else f"{body[0].upper()}{body[1:]}.")
    if trailing:
        link = rng.choice(["Le dossier présente toutefois un point d'appui",
                           "À l'inverse", "Il faut noter en sens inverse"]) \
            if negative_outcome else \
            rng.choice(["Le dossier appelle en revanche une réserve",
                        "Un point de vigilance subsiste", "Une réserve demeure"])
        body = " ; ".join(CLAUSES[c].format(**ctx) for c in trailing)
        parts.append(f"{link} : {body}.")

    if decision["result"] == "approved_with_conditions" and decision["conditions"]:
        parts.append(f"L'accord est conditionné : {decision['conditions']}.")
    elif decision["result"] == "approved":
        parts.append(
            f"Le financement est accordé à hauteur de {decision['approved_amount']:.0f} EUR "
            f"sur {decision['approved_term_months']} mois.")
    elif decision["result"] == "declined":
        parts.append(rng.choice([
            "Une demande portant sur un montant inférieur pourrait être réexaminée.",
            "Le dossier pourra être représenté après consolidation de la situation.",
            "Aucune contre-proposition n'est envisageable en l'état.",
        ]))

    return " ".join(parts)
