"""Fiscale berekeningen engine.

Volledige fiscale waterval van winst tot netto IB, met Decimal precisie.
Alle tussenwaarden worden bewaard in FiscaalResultaat voor display en tests.

Gebruik: bereken_volledig() voor de complete waterval.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from fiscal.constants import URENCRITERIUM_DEFAULT
from fiscal.heffingskortingen import (
    bereken_algemene_heffingskorting,
    bereken_arbeidskorting,
)


def bereken_eigenwoningforfait(woz: float, ew_forfait_pct: float = 0.35,
                                villataks_grens: float = 1_350_000,
                                villataks_pct: float = 2.35) -> float:
    """Bereken eigenwoningforfait op basis van WOZ-waarde.

    Args:
        woz: WOZ-waarde eigen woning.
        ew_forfait_pct: Forfait percentage (bijv. 0.35 = 0.35%).
        villataks_grens: Boven dit bedrag geldt villataks_pct%.
        villataks_pct: Percentage boven villataks grens (default 2.35%).
    """
    if woz <= 0:
        return 0.0
    pct = ew_forfait_pct / 100
    if woz <= villataks_grens:
        return woz * pct
    return villataks_grens * pct + (woz - villataks_grens) * (villataks_pct / 100)


def D(v) -> Decimal:
    """Convert any numeric value to Decimal via string (avoids float imprecision)."""
    if v is None:
        return Decimal('0')
    return Decimal(str(v))


def euro(v: Decimal) -> float:
    """Round Decimal to 2 decimal places, return as float for display/storage."""
    return float(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


@dataclass
class FiscaalResultaat:
    """Complete fiscal calculation result -- every intermediate value for waterfall display."""
    jaar: int = 0
    # W&V
    omzet: float = 0.0
    kosten: float = 0.0
    afschrijvingen: float = 0.0
    winst: float = 0.0
    # Fiscale correcties
    repr_bijtelling: float = 0.0
    kia: float = 0.0
    fiscale_winst: float = 0.0
    # Ondernemersaftrek
    zelfstandigenaftrek: float = 0.0
    startersaftrek: float = 0.0
    na_ondernemersaftrek: float = 0.0
    mkb_vrijstelling: float = 0.0
    belastbare_winst: float = 0.0
    # Eigen woning
    ew_forfait: float = 0.0
    ew_saldo: float = 0.0
    hillen_aftrek: float = 0.0
    aov: float = 0.0
    lijfrente: float = 0.0
    # IB
    verzamelinkomen: float = 0.0
    tariefsaanpassing: float = 0.0  # beperking aftrekbare posten
    bruto_ib: float = 0.0
    # IB/PVV split (bruto_ib = ib_alleen + pvv)
    ib_alleen: float = 0.0  # IB excluding PVV
    pvv: float = 0.0  # Premies volksverzekeringen total
    pvv_aow: float = 0.0  # AOW component (17.90%)
    pvv_anw: float = 0.0  # Anw component (0.10%)
    pvv_wlz: float = 0.0  # Wlz component (9.65%)
    ahk: float = 0.0
    arbeidskorting: float = 0.0
    partner_ahk: float = 0.0
    netto_ib: float = 0.0
    zvw: float = 0.0
    # Resultaat
    voorlopige_aanslag: float = 0.0
    voorlopige_aanslag_zvw: float = 0.0
    resultaat_ib: float = 0.0  # netto_ib - VA_IB (negatief = teruggave)
    resultaat_zvw: float = 0.0  # zvw - VA_ZVW (positief = bijbetalen)
    resultaat: float = 0.0  # resultaat_ib + resultaat_zvw
    # Controles
    uren_criterium: float = 0.0
    uren_criterium_gehaald: bool = False
    kosten_omzet_ratio: float = 0.0
    # Waarschuwingen
    waarschuwingen: list[str] = field(default_factory=list)


@dataclass
class Box3Resultaat:
    """Result of Box 3 (sparen en beleggen) calculation."""
    bank_saldo: float = 0.0
    overige_bezittingen: float = 0.0
    schulden: float = 0.0
    totaal_bezittingen: float = 0.0
    rendement_bank: float = 0.0
    rendement_overig: float = 0.0
    rendement_schuld: float = 0.0
    totaal_rendement: float = 0.0
    heffingsvrij: float = 0.0
    grondslag: float = 0.0
    belasting: float = 0.0


def bereken_box3(params: dict, fiscaal_partner: bool = True) -> Box3Resultaat:
    """Calculate Box 3 forfaitair rendement (2023+ method).

    Fiscal rate/threshold parameters (rendementen, tarief, heffingsvrij,
    drempel) are loaded from fiscale_params via `params` and MUST be present;
    missing keys raise ValueError, consistent with bereken_volledig. This
    prevents silent-wrong calculations when the DB for a year is incomplete.

    Balance-sheet inputs (bank_saldo, overige_bezittingen, schulden) are
    user data and default to 0 when the user has not entered them.

    Args:
        params: Dict with box3_* keys from fiscale_params.
        fiscaal_partner: If True, double the heffingsvrij vermogen.
    """
    required_keys = [
        'box3_rendement_bank_pct',
        'box3_rendement_overig_pct',
        'box3_rendement_schuld_pct',
        'box3_tarief_pct',
        'box3_heffingsvrij_vermogen',
        'box3_drempel_schulden',
    ]
    missing = [k for k in required_keys if params.get(k) is None]
    if missing:
        raise ValueError(
            f"Box 3 fiscale parameters incompleet voor "
            f"{params.get('jaar', '?')}: ontbrekend: {', '.join(missing)}"
        )

    # User balance-sheet inputs — default to 0 if not entered.
    bank = float(params.get('box3_bank_saldo') or 0)
    overig = float(params.get('box3_overige_bezittingen') or 0)
    schulden_bruto = float(params.get('box3_schulden') or 0)

    rend_bank_pct = float(params['box3_rendement_bank_pct']) / 100
    rend_overig_pct = float(params['box3_rendement_overig_pct']) / 100
    rend_schuld_pct = float(params['box3_rendement_schuld_pct']) / 100
    tarief_pct = float(params['box3_tarief_pct']) / 100
    heffingsvrij_pp = float(params['box3_heffingsvrij_vermogen'])
    drempel_schulden_pp = float(params['box3_drempel_schulden'])

    # Drempel schulden: schulden below threshold are ignored
    drempel = drempel_schulden_pp * (2 if fiscaal_partner else 1)
    schulden = max(0, schulden_bruto - drempel)

    totaal_bezittingen = bank + overig
    rendement_bank = bank * rend_bank_pct
    rendement_overig = overig * rend_overig_pct
    rendement_schuld = schulden * rend_schuld_pct
    totaal_rendement = rendement_bank + rendement_overig - rendement_schuld

    heffingsvrij = heffingsvrij_pp * (2 if fiscaal_partner else 1)
    grondslag = max(0, totaal_bezittingen - schulden - heffingsvrij)

    # Grondslag can't exceed total rendement proportion
    netto_vermogen = totaal_bezittingen - schulden
    if netto_vermogen > 0 and grondslag > 0:
        rendement_ratio = totaal_rendement / netto_vermogen
        voordeel = grondslag * rendement_ratio
    else:
        voordeel = 0

    belasting = round(max(0, voordeel) * tarief_pct, 2)

    return Box3Resultaat(
        bank_saldo=bank,
        overige_bezittingen=overig,
        schulden=schulden_bruto,
        totaal_bezittingen=totaal_bezittingen,
        rendement_bank=round(rendement_bank, 2),
        rendement_overig=round(rendement_overig, 2),
        rendement_schuld=round(rendement_schuld, 2),
        totaal_rendement=round(totaal_rendement, 2),
        heffingsvrij=heffingsvrij,
        grondslag=grondslag,
        belasting=belasting,
    )


def bereken_volledig(omzet: float, kosten: float, afschrijvingen: float,
                     representatie: float, investeringen_totaal: float,
                     uren: float, params: dict, aov: float = 0,
                     lijfrente: float = 0,
                     woz: float = 0, hypotheekrente: float = 0,
                     voorlopige_aanslag: float = 0,
                     voorlopige_aanslag_zvw: float = 0,
                     ew_naar_partner: bool = False,
                     partner_inkomen: float = 0) -> FiscaalResultaat:
    """Complete fiscal waterfall using Decimal precision.

    Args:
        omzet: Total revenue (gefactureerd).
        kosten: Total costs (excl. afschrijvingen, excl. representatie-correctie).
        afschrijvingen: Total depreciation for the year.
        representatie: Total representation costs (80% rule applies).
        investeringen_totaal: Total investments in the year (for KIA calculation).
        uren: Total worked hours (urennorm=1 only, for urencriterium check).
        params: Dict with fiscal parameters for the year (from fiscale_params table).
                Must contain 'jaar' key.
        aov: AOV premium (inkomensvoorziening, reduces verzamelinkomen, NOT winst).
        lijfrente: Lijfrentepremie (jaarruimte, reduces verzamelinkomen).
        woz: WOZ-waarde eigen woning (for eigenwoningforfait).
        hypotheekrente: Aftrekbare hypotheekrente (positive number).
        voorlopige_aanslag: Voorlopige aanslag reeds betaald.

    Returns:
        FiscaalResultaat with all intermediate values.
    """
    r = FiscaalResultaat(jaar=params.get('jaar', 0))
    w: list[str] = []

    # Validate required fiscal params
    required_keys = ['kia_ondergrens', 'kia_bovengrens', 'kia_pct',
                     'zelfstandigenaftrek', 'mkb_vrijstelling_pct',
                     'schijf1_grens', 'schijf1_pct', 'schijf2_grens',
                     'schijf2_pct', 'schijf3_pct',
                     'zvw_max_grondslag', 'zvw_pct',
                     'pvv_aow_pct', 'pvv_anw_pct', 'pvv_wlz_pct',
                     'ew_forfait_pct', 'repr_aftrek_pct']
    missing = [k for k in required_keys if k not in params]
    if missing:
        raise ValueError(
            f"Fiscale parameters incompleet voor {params.get('jaar', '?')}: "
            f"ontbrekend: {', '.join(missing)}")

    # Convert all inputs to Decimal for calculation precision
    d_omzet = D(omzet)
    d_kosten = D(kosten)
    d_afschr = D(afschrijvingen)
    d_repr = D(representatie)
    d_invest = D(investeringen_totaal)
    d_aov = D(aov)
    d_lijfrente = D(lijfrente)
    d_woz = D(woz)
    d_hypotheekrente = D(hypotheekrente)
    d_voorlopige = D(voorlopige_aanslag)

    # 1. Winst & Verlies
    d_winst = d_omzet - d_kosten - d_afschr
    r.omzet = omzet
    r.kosten = kosten
    r.afschrijvingen = afschrijvingen
    r.winst = euro(d_winst)

    # 2. Fiscale correcties
    # Representatie: niet-aftrekbaar deel -> bijtelling
    d_repr_aftrek_pct = D(params['repr_aftrek_pct']) / D('100')
    d_repr_bijtelling = d_repr * (D('1') - d_repr_aftrek_pct)
    r.repr_bijtelling = euro(d_repr_bijtelling)

    # KIA: 28% als totaal investeringen binnen grenzen
    d_kia = D('0')
    d_kia_ondergrens = D(params['kia_ondergrens'])
    d_kia_bovengrens = D(params['kia_bovengrens'])
    if d_kia_ondergrens <= d_invest <= d_kia_bovengrens:
        d_kia = d_invest * D(params['kia_pct']) / D('100')
    r.kia = euro(d_kia)

    # Fiscale winst = W&V winst + repr bijtelling - KIA
    d_fiscale_winst = d_winst + d_repr_bijtelling - d_kia
    r.fiscale_winst = euro(d_fiscale_winst)

    # 3. Ondernemersaftrek (alleen bij urencriterium gehaald + toggle actief)
    uren_drempel = params.get('urencriterium', URENCRITERIUM_DEFAULT)
    za_actief = params.get('za_actief', True)
    sa_actief = params.get('sa_actief', False)
    if uren >= uren_drempel and za_actief:
        d_za = D(params['zelfstandigenaftrek'])
    else:
        d_za = D('0')
    if uren >= uren_drempel and sa_actief:
        d_sa = D(params.get('startersaftrek') or 0)
    else:
        d_sa = D('0')
    r.zelfstandigenaftrek = euro(d_za)
    r.startersaftrek = euro(d_sa)

    d_na_oa = d_fiscale_winst - d_za - d_sa
    r.na_ondernemersaftrek = euro(d_na_oa)

    # 4. MKB-winstvrijstelling
    d_mkb_pct = D(params['mkb_vrijstelling_pct']) / D('100')
    d_mkb = max(D('0'), d_na_oa) * d_mkb_pct
    r.mkb_vrijstelling = euro(d_mkb)

    # Belastbare winst
    d_belastbare_winst = max(D('0'), d_na_oa - d_mkb)
    r.belastbare_winst = euro(d_belastbare_winst)

    # 5. Verzamelinkomen Box 1
    # Eigen woning saldo (forfait - rente, usually negative = aftrekpost)
    jaar = params.get('jaar', 0)
    d_ew_forfait = D('0')
    d_ew_saldo = D('0')
    d_hillen_aftrek = D('0')
    if d_woz > 0:
        d_ew_forfait = D(str(bereken_eigenwoningforfait(
            float(d_woz),
            ew_forfait_pct=params['ew_forfait_pct'],
            villataks_grens=params.get('villataks_grens', 1_350_000),
            villataks_pct=params.get('villataks_pct', 2.35),
        )))
        d_ew_saldo = d_ew_forfait - d_hypotheekrente
        # Wet Hillen: als forfait > rente, verlaag de bijtelling
        if d_ew_saldo > 0:
            hillen_pct = D(str(params.get('wet_hillen_pct', 0))) / D('100')
            d_hillen_aftrek = d_ew_saldo * hillen_pct
            d_ew_saldo = d_ew_saldo - d_hillen_aftrek

    r.ew_forfait = euro(d_ew_forfait)
    r.ew_saldo = euro(d_ew_saldo)
    r.hillen_aftrek = euro(d_hillen_aftrek)
    r.aov = aov
    r.lijfrente = lijfrente

    if ew_naar_partner:
        d_verzamelinkomen = d_belastbare_winst - d_aov - d_lijfrente
    else:
        d_verzamelinkomen = d_belastbare_winst + d_ew_saldo - d_aov - d_lijfrente
    d_verzamelinkomen = max(D('0'), d_verzamelinkomen)
    r.verzamelinkomen = euro(d_verzamelinkomen)

    # 5b. Tariefsaanpassing (beperking aftrekbare posten)
    # Since 2023: deductions (ZA, SA, MKB) are capped at the basistarief.
    # If income without these deductions exceeds the top bracket boundary,
    # the excess benefit is clawed back at (toptarief - basistarief).
    d_deductions = d_za + d_sa + d_mkb

    # Determine the bracket boundary and rate difference
    if D(params['schijf1_grens']) == D(params['schijf2_grens']):
        # 2023-2024: 2 brackets, aftrektarief = schijf1_pct
        d_aftrektarief = D(params['schijf1_pct'])
        d_ta_grens = D(params['schijf1_grens'])
    else:
        # 2025+: 3 brackets, aftrektarief = schijf2_pct
        d_aftrektarief = D(params['schijf2_pct'])
        d_ta_grens = D(params['schijf2_grens'])

    d_toptarief = D(params['schijf3_pct'])
    d_ta_pct = (d_toptarief - d_aftrektarief) / D('100')

    # Income without deductions = what would be taxed without ZA/SA/MKB
    if ew_naar_partner:
        d_income_without = d_fiscale_winst - d_aov - d_lijfrente
    else:
        d_income_without = d_fiscale_winst + d_ew_saldo - d_aov - d_lijfrente
    # Amount that was in the top bracket before deductions
    d_excess = max(D('0'), d_income_without - d_ta_grens)
    d_subject = min(d_deductions, d_excess)

    d_tariefsaanpassing = d_subject * d_ta_pct
    r.tariefsaanpassing = euro(d_tariefsaanpassing)

    # 6. IB Box 1 (schijventarief)
    d_vi = d_verzamelinkomen

    # Schijf 1
    d_s1_grens = D(params['schijf1_grens'])
    d_s1_pct = D(params['schijf1_pct']) / D('100')
    d_s1 = min(d_vi, d_s1_grens)
    d_ib1 = d_s1 * d_s1_pct

    # Schijf 2 (only relevant when schijf2_grens > schijf1_grens, i.e. 2025+)
    d_s2_grens = D(params['schijf2_grens'])
    d_s2_pct = D(params['schijf2_pct']) / D('100')
    d_s2 = min(max(d_vi - d_s1_grens, D('0')), d_s2_grens - d_s1_grens)
    d_ib2 = d_s2 * d_s2_pct

    # Schijf 3
    d_s3_pct = D(params['schijf3_pct']) / D('100')
    d_s3 = max(d_vi - d_s2_grens, D('0'))
    d_ib3 = d_s3 * d_s3_pct

    d_bruto_ib = d_ib1 + d_ib2 + d_ib3 + d_tariefsaanpassing
    r.bruto_ib = euro(d_bruto_ib)

    # 6b. IB/PVV split
    # PVV = 27.65% over min(verzamelinkomen, premiegrondslag)
    # premiegrondslag differs from schijf1_grens in 2023-2024
    d_premie_grondslag = D(params.get('pvv_premiegrondslag', 0))
    if d_premie_grondslag == 0:
        d_premie_grondslag = D(params['schijf1_grens'])  # fallback for older DB
    d_pvv_basis = min(d_vi, d_premie_grondslag)

    # PVV rates from params (DB-driven); required_keys enforces presence
    pvv_aow_pct = D(str(params['pvv_aow_pct']))
    pvv_anw_pct = D(str(params['pvv_anw_pct']))
    pvv_wlz_pct = D(str(params['pvv_wlz_pct']))

    d_pvv_aow = d_pvv_basis * pvv_aow_pct / D('100')
    d_pvv_anw = d_pvv_basis * pvv_anw_pct / D('100')
    d_pvv_wlz = d_pvv_basis * pvv_wlz_pct / D('100')
    d_pvv = d_pvv_aow + d_pvv_anw + d_pvv_wlz

    r.pvv = euro(d_pvv)
    r.pvv_aow = euro(d_pvv_aow)
    r.pvv_anw = euro(d_pvv_anw)
    r.pvv_wlz = euro(d_pvv_wlz)
    r.ib_alleen = euro(d_bruto_ib - d_pvv)

    # 7. Heffingskortingen
    # AHK: afbouw op basis van verzamelinkomen (sinds 2025; voor Box-1-only maakt het niet uit)
    ahk = bereken_algemene_heffingskorting(r.verzamelinkomen, jaar, params)
    r.ahk = ahk

    # Partner AHK: calculate if partner income provided
    if partner_inkomen > 0:
        r.partner_ahk = bereken_algemene_heffingskorting(
            partner_inkomen, jaar, params)
    else:
        r.partner_ahk = 0.0

    # Arbeidskorting: op basis van arbeidsinkomen = fiscale winst
    # (= winst uit onderneming VÓÓR zelfstandigenaftrek, startersaftrek en MKB-vrijstelling)
    ak = bereken_arbeidskorting(r.fiscale_winst, jaar,
                                brackets_json=params.get('arbeidskorting_brackets', ''))
    r.arbeidskorting = ak

    # 8. Netto IB
    d_netto_ib = max(D('0'), d_bruto_ib - D(str(ahk)) - D(str(ak)))
    r.netto_ib = euro(d_netto_ib)

    # 9. ZVW-bijdrage (apart van IB, via aanslag)
    # Grondslag = belastbare winst (bijdrage-inkomen, gecapped op maximum)
    # Boekhouder 2024 confirms: "Inkomen Zvw = 76.776" (= belastbare winst, not verzamelinkomen)
    d_zvw_grondslag = min(d_belastbare_winst, D(params['zvw_max_grondslag']))
    d_zvw = d_zvw_grondslag * D(params['zvw_pct']) / D('100')
    r.zvw = euro(d_zvw)

    # 10. Eindresultaat
    r.voorlopige_aanslag = voorlopige_aanslag
    r.voorlopige_aanslag_zvw = voorlopige_aanslag_zvw

    # IB resultaat: netto_ib - VA_IB (negatief = teruggave)
    d_va_zvw = D(voorlopige_aanslag_zvw)
    d_resultaat_ib = d_netto_ib - d_voorlopige
    r.resultaat_ib = euro(d_resultaat_ib)

    # ZVW resultaat: zvw - VA_ZVW (positief = bijbetalen)
    d_resultaat_zvw = d_zvw - d_va_zvw
    r.resultaat_zvw = euro(d_resultaat_zvw)

    # Total resultaat
    r.resultaat = euro(d_resultaat_ib + d_resultaat_zvw)

    # Controles
    r.uren_criterium = uren
    r.uren_criterium_gehaald = uren >= uren_drempel
    r.kosten_omzet_ratio = round(kosten / omzet * 100, 1) if omzet > 0 else 0

    if not r.uren_criterium_gehaald:
        w.append(f"Urencriterium niet gehaald: {uren:.0f} / {uren_drempel:.0f} uur")
    if r.kosten_omzet_ratio > 30:
        w.append(f"Kosten/omzet ratio hoog: {r.kosten_omzet_ratio}%")
    if (d_za + d_sa) > d_fiscale_winst and d_fiscale_winst > 0:
        w.append("ZA + SA hoger dan fiscale winst: aftrek deels verloren")

    if lijfrente > 0:
        max_reasonable = r.fiscale_winst * 0.30 if r.fiscale_winst > 0 else 15000
        if lijfrente > max_reasonable:
            w.append(f"Lijfrentepremie (€{lijfrente:,.0f}) lijkt hoog — "
                     "controleer of dit binnen uw jaarruimte valt via de "
                     "Belastingdienst jaarruimte rekenhulp.")

    r.waarschuwingen = w
    return r


