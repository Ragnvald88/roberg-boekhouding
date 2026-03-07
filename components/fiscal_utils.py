"""Shared fiscal utility functions used by jaarafsluiting and aangifte pages."""

from pathlib import Path

from database import (
    get_data_counts,
    get_fiscale_params,
    get_investeringen,
    get_investeringen_voor_afschrijving,
    get_omzet_totaal,
    get_openstaande_debiteuren,
    get_nog_te_factureren,
    get_representatie_totaal,
    get_uitgaven_per_categorie,
    get_uren_totaal,
)
from fiscal.afschrijvingen import bereken_afschrijving


def fiscale_params_to_dict(params) -> dict:
    """Convert FiscaleParams dataclass to dict for bereken_volledig."""
    return {
        'jaar': params.jaar,
        'zelfstandigenaftrek': params.zelfstandigenaftrek,
        'startersaftrek': params.startersaftrek,
        'mkb_vrijstelling_pct': params.mkb_vrijstelling_pct,
        'kia_ondergrens': params.kia_ondergrens,
        'kia_bovengrens': params.kia_bovengrens,
        'kia_pct': params.kia_pct,
        'km_tarief': params.km_tarief,
        'schijf1_grens': params.schijf1_grens,
        'schijf1_pct': params.schijf1_pct,
        'schijf2_grens': params.schijf2_grens,
        'schijf2_pct': params.schijf2_pct,
        'schijf3_pct': params.schijf3_pct,
        'ahk_max': params.ahk_max,
        'ahk_afbouw_pct': params.ahk_afbouw_pct,
        'ahk_drempel': params.ahk_drempel,
        'ak_max': params.ak_max,
        'zvw_pct': params.zvw_pct,
        'zvw_max_grondslag': params.zvw_max_grondslag,
        'repr_aftrek_pct': params.repr_aftrek_pct,
        'ew_forfait_pct': params.ew_forfait_pct,
        'villataks_grens': params.villataks_grens,
        'wet_hillen_pct': params.wet_hillen_pct,
        'urencriterium': params.urencriterium,
        'pvv_premiegrondslag': params.pvv_premiegrondslag,
        'pvv_aow_pct': params.pvv_aow_pct,
        'pvv_anw_pct': params.pvv_anw_pct,
        'pvv_wlz_pct': params.pvv_wlz_pct,
        'arbeidskorting_brackets': params.arbeidskorting_brackets,
        # Box 3 params (for bereken_box3)
        'box3_bank_saldo': params.box3_bank_saldo,
        'box3_overige_bezittingen': params.box3_overige_bezittingen,
        'box3_schulden': params.box3_schulden,
        'box3_heffingsvrij_vermogen': params.box3_heffingsvrij_vermogen,
        'box3_rendement_bank_pct': params.box3_rendement_bank_pct,
        'box3_rendement_overig_pct': params.box3_rendement_overig_pct,
        'box3_rendement_schuld_pct': params.box3_rendement_schuld_pct,
        'box3_tarief_pct': params.box3_tarief_pct,
        'box3_drempel_schulden': params.box3_drempel_schulden,
        'za_actief': params.za_actief,
        'sa_actief': params.sa_actief,
    }


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

    omzet = await get_omzet_totaal(db_path, jaar)
    kosten_per_cat = await get_uitgaven_per_categorie(db_path, jaar)
    representatie = await get_representatie_totaal(db_path, jaar)
    counts = await get_data_counts(db_path, jaar)
    investeringen = await get_investeringen_voor_afschrijving(
        db_path, tot_jaar=jaar)
    inv_dit_jaar = await get_investeringen(db_path, jaar=jaar)
    uren = await get_uren_totaal(db_path, jaar, urennorm_only=True)

    totaal_kosten_alle = sum(r['totaal'] for r in kosten_per_cat)
    inv_dit_jaar_bedrag = sum(
        (u.aanschaf_bedrag or u.bedrag) for u in inv_dit_jaar
    )
    kosten_excl_inv = totaal_kosten_alle - inv_dit_jaar_bedrag

    # Afschrijvingen + activastaat
    activastaat = []
    totaal_afschrijvingen = 0.0
    for u in investeringen:
        aanschaf_bedrag_bruto = u.aanschaf_bedrag or u.bedrag
        zakelijk_factor = (u.zakelijk_pct or 100) / 100
        aanschaf_bedrag = aanschaf_bedrag_bruto * zakelijk_factor
        levensduur = u.levensduur_jaren or 5
        aanschaf_maand = int(u.datum[5:7])
        aanschaf_jaar = int(u.datum[0:4])
        result = bereken_afschrijving(
            aanschaf_bedrag=aanschaf_bedrag,
            restwaarde_pct=u.restwaarde_pct,
            levensduur=levensduur,
            aanschaf_maand=aanschaf_maand,
            aanschaf_jaar=aanschaf_jaar,
            bereken_jaar=jaar,
        )
        activastaat.append({
            'omschrijving': u.omschrijving,
            'aanschaf_jaar': aanschaf_jaar,
            'aanschaf_bedrag': aanschaf_bedrag,
            'afschrijving_jaar': result['per_jaar'],
            'afschrijving_dit_jaar': result['afschrijving'],
            'boekwaarde': result['boekwaarde'],
        })
        totaal_afschrijvingen += result['afschrijving']

    # KIA basis
    inv_totaal_dit_jaar = sum(
        (u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct or 100) / 100)
        for u in inv_dit_jaar
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
    debiteuren = await get_openstaande_debiteuren(db_path, jaar)
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
