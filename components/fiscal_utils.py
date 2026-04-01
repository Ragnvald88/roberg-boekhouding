"""Shared fiscal utility functions used by jaarafsluiting and aangifte pages."""

import asyncio
from dataclasses import asdict
from pathlib import Path

from database import (
    get_afschrijving_overrides_batch,
    get_data_counts,
    get_fiscale_params,
    get_investeringen,
    get_investeringen_voor_afschrijving,
    get_km_totaal,
    get_omzet_per_maand,
    get_omzet_totaal,
    get_debiteuren_op_peildatum,
    get_nog_te_factureren,
    get_representatie_totaal,
    get_uitgaven_per_categorie,
    get_uren_totaal,
)
from fiscal.afschrijvingen import bereken_afschrijving


def fiscale_params_to_dict(params) -> dict:
    """Convert FiscaleParams dataclass to dict for bereken_volledig."""
    return asdict(params)


async def fetch_fiscal_data(db_path: Path, jaar: int) -> dict | None:
    """Fetch all fiscal data needed for tax calculation.

    Returns dict with keys: params, params_dict, omzet, kosten_per_cat,
    kosten_excl_inv, representatie, totaal_afschrijvingen, inv_totaal_dit_jaar,
    uren, activastaat, totaal_kosten_alle, aov, woz, hypotheekrente,
    voorlopige_aanslag, voorlopige_aanslag_zvw, ew_naar_partner.

    Returns None if no fiscale_params exist for the year.
    """
    params = await get_fiscale_params(db_path, jaar)
    if params is None:
        return None

    params_dict = fiscale_params_to_dict(params)

    # Run independent DB calls concurrently
    (omzet, kosten_per_cat, representatie, counts, investeringen,
     inv_dit_jaar, uren, km_data) = await asyncio.gather(
        get_omzet_totaal(db_path, jaar),
        get_uitgaven_per_categorie(db_path, jaar),
        get_representatie_totaal(db_path, jaar),
        get_data_counts(db_path, jaar),
        get_investeringen_voor_afschrijving(db_path, tot_jaar=jaar),
        get_investeringen(db_path, jaar=jaar),
        get_uren_totaal(db_path, jaar, urennorm_only=True),
        get_km_totaal(db_path, jaar),
    )
    km_vergoeding = round(km_data['vergoeding'], 2)

    totaal_kosten_alle = sum(r['totaal'] for r in kosten_per_cat)
    inv_dit_jaar_bedrag = sum(
        (u.aanschaf_bedrag or u.bedrag) for u in inv_dit_jaar
    )
    kosten_excl_inv = totaal_kosten_alle - inv_dit_jaar_bedrag + km_vergoeding

    # Fetch depreciation overrides for all investments
    all_overrides = await get_afschrijving_overrides_batch(
        db_path, [u.id for u in investeringen]) if investeringen else {}

    # Afschrijvingen + activastaat
    activastaat = []
    totaal_afschrijvingen = 0.0
    for u in investeringen:
        aanschaf_bedrag_bruto = u.aanschaf_bedrag or u.bedrag
        zakelijk_factor = (u.zakelijk_pct if u.zakelijk_pct is not None else 100) / 100
        aanschaf_bedrag = aanschaf_bedrag_bruto * zakelijk_factor
        levensduur = u.levensduur_jaren or 5
        aanschaf_maand = int(u.datum[5:7])
        aanschaf_jaar = int(u.datum[0:4])
        overrides = all_overrides.get(u.id)
        result = bereken_afschrijving(
            aanschaf_bedrag=aanschaf_bedrag,
            restwaarde_pct=u.restwaarde_pct,
            levensduur=levensduur,
            aanschaf_maand=aanschaf_maand,
            aanschaf_jaar=aanschaf_jaar,
            bereken_jaar=jaar,
            overrides=overrides,
        )
        activastaat.append({
            'omschrijving': u.omschrijving,
            'aanschaf_jaar': aanschaf_jaar,
            'aanschaf_bedrag': aanschaf_bedrag,
            'afschrijving_jaar': result['per_jaar'],
            'afschrijving_dit_jaar': result['afschrijving'],
            'boekwaarde': result['boekwaarde'],
            'has_override': result.get('has_override', False),
        })
        totaal_afschrijvingen += result['afschrijving']

    # KIA basis — only items above per-item threshold qualify
    kia_drempel = params.kia_drempel_per_item or 450
    inv_totaal_dit_jaar = sum(
        z for u in inv_dit_jaar
        if (z := (u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct if u.zakelijk_pct is not None else 100) / 100))
        >= kia_drempel
    )

    return {
        'params': params,
        'params_dict': params_dict,
        'omzet': omzet,
        'kosten_per_cat': kosten_per_cat,
        'kosten_excl_inv': kosten_excl_inv,
        'representatie': representatie,
        'totaal_afschrijvingen': totaal_afschrijvingen,
        'inv_totaal_dit_jaar': inv_totaal_dit_jaar,
        'uren': uren,
        'activastaat': activastaat,
        'totaal_kosten_alle': totaal_kosten_alle,
        'km_vergoeding': km_vergoeding,
        'aov': params.aov_premie or 0,
        'woz': params.woz_waarde or 0,
        'hypotheekrente': params.hypotheekrente or 0,
        'voorlopige_aanslag': params.voorlopige_aanslag_betaald or 0,
        'voorlopige_aanslag_zvw': params.voorlopige_aanslag_zvw or 0,
        'ew_naar_partner': params.ew_naar_partner,
        'lijfrente': params.lijfrente_premie or 0,
        'n_facturen': counts['n_facturen'],
        'n_uitgaven': counts['n_uitgaven'],
        'n_werkdagen': counts['n_werkdagen'],
    }


async def bereken_balans(db_path: Path, jaar: int, activastaat: list[dict],
                          winst: float = 0.0,
                          begin_vermogen: float = 0.0) -> dict:
    """Calculate balance sheet values.

    Combines auto-calculated values (MVA, debiteuren, nog te factureren)
    with manual inputs (bank saldo, crediteuren, overige).

    Args:
        db_path: Database path.
        jaar: Fiscal year.
        activastaat: List of asset dicts (from fetch_fiscal_data).
        winst: W&V result for kapitaalsvergelijking.
        begin_vermogen: Previous year's eigen vermogen.

    Returns dict with all balance sheet values.
    """
    params = await get_fiscale_params(db_path, jaar)

    # Auto-calculated from data
    mva = round(sum(a['boekwaarde'] for a in activastaat), 2)
    # Year-end debiteuren: invoices outstanding as of 31-12-{jaar}
    peildatum = f'{jaar}-12-31'
    debiteuren = await get_debiteuren_op_peildatum(db_path, peildatum)
    nog_te_factureren = await get_nog_te_factureren(db_path, jaar)

    # Manual inputs from fiscale_params
    bank_saldo = params.balans_bank_saldo if params else 0
    crediteuren = params.balans_crediteuren if params else 0
    overige_vorderingen = params.balans_overige_vorderingen if params else 0
    overige_schulden = params.balans_overige_schulden if params else 0

    # Totals
    totaal_activa = round(mva + debiteuren + nog_te_factureren
                          + overige_vorderingen + bank_saldo, 2)
    totaal_schulden = round(crediteuren + overige_schulden, 2)
    eigen_vermogen = round(totaal_activa - totaal_schulden, 2)

    # Kapitaalsvergelijking
    prive_onttrekkingen = round(begin_vermogen + winst - eigen_vermogen, 2)

    return {
        # Activa
        'mva': mva,
        'debiteuren': round(debiteuren, 2),
        'nog_te_factureren': round(nog_te_factureren, 2),
        'overige_vorderingen': overige_vorderingen,
        'bank_saldo': bank_saldo,
        'totaal_activa': totaal_activa,
        # Passiva
        'crediteuren': crediteuren,
        'overige_schulden': overige_schulden,
        'totaal_schulden': totaal_schulden,
        'eigen_vermogen': eigen_vermogen,
        # Kapitaalsvergelijking
        'begin_vermogen': begin_vermogen,
        'winst': winst,
        'prive_onttrekkingen': prive_onttrekkingen,
    }


async def extrapoleer_jaaromzet(db_path: Path, jaar: int) -> dict:
    """Extrapolate annual revenue from YTD data.

    Returns dict with ytd_omzet, extrapolated_omzet, method, confidence, basis_maanden.
    Past years return actual data with confidence='high'.
    Current year extrapolates linearly, weighted with prior-year pattern if available.
    """
    from datetime import date as _d
    huidig_jaar = _d.today().year

    ytd_omzet = await get_omzet_totaal(db_path, jaar)

    if jaar != huidig_jaar:
        return {
            'ytd_omzet': ytd_omzet,
            'extrapolated_omzet': ytd_omzet,
            'method': 'actual',
            'confidence': 'high',
            'basis_maanden': 12,
        }

    month = _d.today().month
    complete_months = month if _d.today().day >= 15 else max(month - 1, 1)

    if complete_months == 0 or ytd_omzet == 0:
        return {
            'ytd_omzet': 0,
            'extrapolated_omzet': 0,
            'method': 'ytd_linear',
            'confidence': 'low',
            'basis_maanden': 0,
        }

    linear = ytd_omzet * (12 / complete_months)

    # Weight with prior-year monthly pattern if available
    # NOTE: get_omzet_per_maand returns list[float] (index 0=Jan .. 11=Dec)
    prior_maanden = await get_omzet_per_maand(db_path, jaar - 1)
    prior_total = sum(prior_maanden)

    if prior_total > 0 and complete_months >= 3:
        prior_ytd = sum(prior_maanden[:complete_months])
        prior_fraction = prior_ytd / prior_total if prior_total > 0 else (complete_months / 12)
        if prior_fraction > 0.05:
            pattern = ytd_omzet / prior_fraction
            extrapolated = round(0.7 * linear + 0.3 * pattern, 2)
        else:
            extrapolated = round(linear, 2)
    else:
        extrapolated = round(linear, 2)

    if complete_months <= 2:
        confidence = 'low'
    elif complete_months <= 5:
        confidence = 'medium'
    else:
        confidence = 'high'

    return {
        'ytd_omzet': ytd_omzet,
        'extrapolated_omzet': extrapolated,
        'method': 'weighted' if (prior_total > 0 and complete_months >= 3) else 'ytd_linear',
        'confidence': confidence,
        'basis_maanden': complete_months,
    }


def get_personal_data_with_fallback(params_current, params_prior) -> tuple[dict, list[str]]:
    """Use current-year data if available, fall back to prior year.

    Returns (result_dict, fallbacks_used_list).
    result_dict maps short keys to {'value': float, 'source': 'current'|'prior'|'none'}.
    """
    fields = {
        'woz_waarde': 'woz',
        'hypotheekrente': 'hypotheekrente',
        'aov_premie': 'aov',
        'partner_bruto_loon': 'partner_loon',
        'partner_loonheffing': 'partner_lh',
        'box3_bank_saldo': 'box3_bank',
        'box3_overige_bezittingen': 'box3_overig',
        'box3_schulden': 'box3_schulden',
    }

    result = {}
    fallbacks = []

    for attr, key in fields.items():
        current_val = getattr(params_current, attr, 0) or 0
        if current_val > 0:
            result[key] = {'value': current_val, 'source': 'current'}
        elif params_prior:
            prior_val = getattr(params_prior, attr, 0) or 0
            if prior_val > 0:
                result[key] = {'value': prior_val, 'source': 'prior'}
                fallbacks.append(attr)
            else:
                result[key] = {'value': 0, 'source': 'none'}
        else:
            result[key] = {'value': 0, 'source': 'none'}

    return result, fallbacks
