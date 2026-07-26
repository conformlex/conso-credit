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
"""

from __future__ import annotations

import random

# Reason code -> French clause. The placeholders are filled from the file.
CLAUSES = {
    "EXCESSIVE_DTI": "le taux d'endettement apres operation atteint {dti:.1f} %, au-dela du seuil de 35 %",
    "COMFORTABLE_DTI": "le taux d'endettement apres operation reste contenu a {dti:.1f} %",
    "LOW_RESIDUAL_INCOME": "le reste a vivre s'etablit a {residual:.0f} EUR par unite de consommation, insuffisant pour le foyer",
    "AMPLE_RESIDUAL_INCOME": "le reste a vivre atteint {residual:.0f} EUR par unite de consommation",
    "HIGH_PAYMENT_SHOCK": "le saut de charge de {shock:.0f} EUR par mois est important au regard des revenus",
    "INSUFFICIENT_INCOME": "les revenus ne supportent pas le montant sollicite",
    "TOO_MUCH_VARIABLE_PAY": "la part variable des revenus est elevee et fragilise la capacite de remboursement",
    "UNDOCUMENTED_INCOME": "une partie des revenus declares n'est pas justifiee",
    "SOLID_INCOME": "les revenus sont stables et integralement justifies",
    "PRECARIOUS_CONTRACT": "le contrat de travail est precaire",
    "PROBATION_PERIOD": "l'emprunteur est en periode d'essai",
    "SHORT_JOB_TENURE": "l'anciennete professionnelle est faible ({tenure} mois)",
    "RECENT_MOVE": "l'installation dans le logement est tres recente",
    "STABLE_EMPLOYMENT": "la situation professionnelle est stable ({contract}, {tenure} mois d'anciennete)",
    "PAYMENT_INCIDENTS": "des incidents de paiement ont ete releves sur les douze derniers mois",
    "HEAVY_OVERDRAFT_USE": "le compte est reste debiteur {days} jours sur l'annee",
    "LOAN_INCIDENTS": "des incidents ont ete constates sur les credits en cours",
    "MULTIPLE_REVOLVING": "la detention de plusieurs credits renouvelables traduit une tension de tresorerie",
    "SOLID_SAVINGS": "l'epargne disponible represente {savings:.1f} mois de charges",
    "CLEAN_HISTORY": "aucun incident n'est a signaler sur la periode observee",
    "LONG_RELATIONSHIP": "la relation bancaire remonte a plus de {years} ans",
    "SALARY_DOMICILED": "les revenus sont domicilies dans l'etablissement",
    "LOANS_REPAID_CLEAN": "les credits precedents ont ete soldes sans incident",
    "SOLID_CO_BORROWER": "la presence d'un co-emprunteur renforce le dossier",
    "MEANINGFUL_DOWN_PAYMENT": "l'apport personnel de {down:.0f} EUR reduit l'exposition",
    "NO_SECURITY": "l'operation ne s'accompagne d'aucun apport ni garantie",
    "FICP_FLAG": "l'emprunteur est inscrit au FICP",
    "FCC_FLAG": "l'emprunteur est inscrit au FCC",
    "OVERRIDE_WEALTH": "le patrimoine constitue justifie une derogation",
    "OVERRIDE_RELATIONSHIP": "l'anciennete de la relation justifie une derogation",
    "OVERRIDE_COMMERCIAL": "une derogation commerciale a ete accordee",
}

FAVOURABLE = {
    "COMFORTABLE_DTI", "AMPLE_RESIDUAL_INCOME", "SOLID_INCOME", "STABLE_EMPLOYMENT",
    "SOLID_SAVINGS", "CLEAN_HISTORY", "LONG_RELATIONSHIP", "SALARY_DOMICILED",
    "LOANS_REPAID_CLEAN", "SOLID_CO_BORROWER", "MEANINGFUL_DOWN_PAYMENT",
    "OVERRIDE_WEALTH", "OVERRIDE_RELATIONSHIP", "OVERRIDE_COMMERCIAL",
}

OPENINGS = {
    "underwriter": {
        "approved": "Dossier accorde.",
        "approved_with_conditions": "Accord assorti de conditions.",
        "declined": "Demande rejetee.",
        "deferred": "Decision ajournee dans l'attente de pieces complementaires.",
    },
    "adviser": {
        "approved": "Nous donnons une suite favorable a cette demande de {purpose}.",
        "approved_with_conditions": "Nous pouvons accompagner ce projet de {purpose}, sous reserve d'amenagements.",
        "declined": "Nous ne pouvons pas donner suite a cette demande de {purpose}.",
        "deferred": "L'instruction de cette demande de {purpose} est suspendue.",
    },
    "committee": {
        "approved": "Le comite retient une position favorable.",
        "approved_with_conditions": "Le comite retient un accord conditionne.",
        "declined": "Le comite retient une position defavorable.",
        "deferred": "Le comite ajourne sa decision.",
    },
}

PURPOSE_FR = {
    "AUTO": "credit auto", "HOME_IMPROVEMENT": "credit travaux",
    "PERSONAL_LOAN": "pret personnel", "REVOLVING": "reserve d'argent",
    "DEBT_CONSOLIDATION": "regroupement de credits",
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
        link = rng.choice(["Le dossier presente toutefois un point d'appui",
                           "A l'inverse", "Il faut noter en sens inverse"]) \
            if negative_outcome else \
            rng.choice(["Le dossier appelle en revanche une reserve",
                        "Un point de vigilance subsiste", "Une reserve demeure"])
        body = " ; ".join(CLAUSES[c].format(**ctx) for c in trailing)
        parts.append(f"{link} : {body}.")

    if decision["result"] == "approved_with_conditions" and decision["conditions"]:
        parts.append(f"L'accord est conditionne : {decision['conditions']}.")
    elif decision["result"] == "approved":
        parts.append(
            f"Le financement est accorde a hauteur de {decision['approved_amount']:.0f} EUR "
            f"sur {decision['approved_term_months']} mois.")
    elif decision["result"] == "declined":
        parts.append(rng.choice([
            "Une demande portant sur un montant inferieur pourrait etre reexaminee.",
            "Le dossier pourra etre represente apres consolidation de la situation.",
            "Aucune contre-proposition n'est envisageable en l'etat.",
        ]))

    return " ".join(parts)
