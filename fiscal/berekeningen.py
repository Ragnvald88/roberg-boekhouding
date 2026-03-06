"""Fiscale berekeningen engine.

Volledige fiscale waterval van winst tot netto IB, met Decimal precisie.
Alle tussenwaarden worden bewaard in FiscaalResultaat voor display en tests.

Gebruik: bereken_volledig() voor de complete waterval,
         bereken_wv() en bereken_ib() als losse functies.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from fiscal.heffingskortingen import (
    bereken_algemene_heffingskorting,
    bereken_arbeidskorting,
)


def bereken_eigenwoningforfait(woz: float, ew_forfait_pct: float = 0.35,
                                villataks_grens: float = 1_350_000) -> float:
    """Bereken eigenwoningforfait op basis van WOZ-waarde.

    Args:
        woz: WOZ-waarde eigen woning.
        ew_forfait_pct: Forfait percentage (bijv. 0.35 = 0.35%).
        villataks_grens: Boven dit bedrag geldt 2.35%.
    """
    if woz <= 0:
        return 0.0
    pct = ew_forfait_pct / 100
    if woz <= villataks_grens:
        return woz * pct
    return villataks_grens * pct + (woz - villataks_grens) * 0.0235


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
    # IB
    verzamelinkomen: float = 0.0
    bruto_ib: float = 0.0
    ahk: float = 0.0
    arbeidskorting: float = 0.0
    netto_ib: float = 0.0
    zvw: float = 0.0
    # Resultaat
    voorlopige_aanslag: float = 0.0
    resultaat: float = 0.0  # negatief = teruggave, positief = bijbetalen
    # Controles
    uren_criterium: float = 0.0
    uren_criterium_gehaald: bool = False
    kosten_omzet_ratio: float = 0.0
    # Waarschuwingen
    waarschuwingen: list[str] = field(default_factory=list)


def bereken_volledig(omzet: float, kosten: float, afschrijvingen: float,
                     representatie: float, investeringen_totaal: float,
                     uren: float, params: dict, aov: float = 0,
                     woz: float = 0, hypotheekrente: float = 0,
                     voorlopige_aanslag: float = 0) -> FiscaalResultaat:
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
        woz: WOZ-waarde eigen woning (for eigenwoningforfait).
        hypotheekrente: Aftrekbare hypotheekrente (positive number).
        voorlopige_aanslag: Voorlopige aanslag reeds betaald.

    Returns:
        FiscaalResultaat with all intermediate values.
    """
    r = FiscaalResultaat(jaar=params.get('jaar', 0))
    w: list[str] = []

    # Convert all inputs to Decimal for calculation precision
    d_omzet = D(omzet)
    d_kosten = D(kosten)
    d_afschr = D(afschrijvingen)
    d_repr = D(representatie)
    d_invest = D(investeringen_totaal)
    d_aov = D(aov)
    d_woz = D(woz)
    d_hypotheekrente = D(hypotheekrente)
    d_voorlopige = D(voorlopige_aanslag)

    # === 1. Winst & Verlies ===
    d_winst = d_omzet - d_kosten - d_afschr
    r.omzet = omzet
    r.kosten = kosten
    r.afschrijvingen = afschrijvingen
    r.winst = euro(d_winst)

    # === 2. Fiscale correcties ===
    # Representatie: niet-aftrekbaar deel -> bijtelling
    d_repr_aftrek_pct = D(params.get('repr_aftrek_pct', 80)) / D('100')
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

    # === 3. Ondernemersaftrek (alleen bij urencriterium gehaald) ===
    uren_drempel = params.get('urencriterium', 1225)
    if uren >= uren_drempel:
        d_za = D(params['zelfstandigenaftrek'])
        d_sa = D(params.get('startersaftrek') or 0)
    else:
        d_za = D('0')
        d_sa = D('0')
    r.zelfstandigenaftrek = euro(d_za)
    r.startersaftrek = euro(d_sa)

    d_na_oa = d_fiscale_winst - d_za - d_sa
    r.na_ondernemersaftrek = euro(d_na_oa)

    # === 4. MKB-winstvrijstelling ===
    d_mkb_pct = D(params['mkb_vrijstelling_pct']) / D('100')
    d_mkb = max(D('0'), d_na_oa) * d_mkb_pct
    r.mkb_vrijstelling = euro(d_mkb)

    # Belastbare winst
    d_belastbare_winst = max(D('0'), d_na_oa - d_mkb)
    r.belastbare_winst = euro(d_belastbare_winst)

    # === 5. Verzamelinkomen Box 1 ===
    # Eigen woning saldo (forfait - rente, usually negative = aftrekpost)
    jaar = params.get('jaar', 0)
    d_ew_forfait = D('0')
    d_ew_saldo = D('0')
    d_hillen_aftrek = D('0')
    if d_woz > 0:
        d_ew_forfait = D(str(bereken_eigenwoningforfait(
            float(d_woz),
            ew_forfait_pct=params.get('ew_forfait_pct', 0.35),
            villataks_grens=params.get('villataks_grens', 1_350_000),
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

    d_verzamelinkomen = d_belastbare_winst + d_ew_saldo - d_aov
    d_verzamelinkomen = max(D('0'), d_verzamelinkomen)
    r.verzamelinkomen = euro(d_verzamelinkomen)

    # === 6. IB Box 1 (schijventarief) ===
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

    d_bruto_ib = d_ib1 + d_ib2 + d_ib3
    r.bruto_ib = euro(d_bruto_ib)

    # === 7. Heffingskortingen ===
    # AHK: afbouw op basis van verzamelinkomen (sinds 2025; voor Box-1-only maakt het niet uit)
    ahk = bereken_algemene_heffingskorting(r.verzamelinkomen, jaar, params)
    r.ahk = ahk

    # Arbeidskorting: op basis van arbeidsinkomen = fiscale winst
    # (= winst uit onderneming VÓÓR zelfstandigenaftrek, startersaftrek en MKB-vrijstelling)
    ak = bereken_arbeidskorting(r.fiscale_winst, jaar)
    r.arbeidskorting = ak

    # === 8. Netto IB ===
    d_netto_ib = max(D('0'), d_bruto_ib - D(str(ahk)) - D(str(ak)))
    r.netto_ib = euro(d_netto_ib)

    # === 9. ZVW-bijdrage (apart van IB, via aanslag) ===
    # Grondslag = verzamelinkomen (bijdrage-inkomen, gecapped op maximum)
    d_zvw_grondslag = min(d_verzamelinkomen, D(params['zvw_max_grondslag']))
    d_zvw = d_zvw_grondslag * D(params['zvw_pct']) / D('100')
    r.zvw = euro(d_zvw)

    # === 10. Eindresultaat ===
    r.voorlopige_aanslag = voorlopige_aanslag
    # Negatief = teruggave (meer betaald dan verschuldigd)
    d_resultaat = d_netto_ib + d_zvw - d_voorlopige
    r.resultaat = euro(d_resultaat)

    # === Controles ===
    r.uren_criterium = uren
    r.uren_criterium_gehaald = uren >= uren_drempel
    r.kosten_omzet_ratio = round(kosten / omzet * 100, 1) if omzet > 0 else 0

    if not r.uren_criterium_gehaald:
        w.append(f"Urencriterium niet gehaald: {uren:.0f} / {uren_drempel:.0f} uur")
    if r.kosten_omzet_ratio > 30:
        w.append(f"Kosten/omzet ratio hoog: {r.kosten_omzet_ratio}%")

    r.waarschuwingen = w
    return r


def bereken_wv(omzet: float, kosten: float, afschrijvingen: float) -> dict:
    """Winst-en-verliesrekening (simple version).

    Returns:
        Dict with keys: omzet, kosten, afschrijvingen, winst.
    """
    winst = omzet - kosten - afschrijvingen
    return {
        'omzet': omzet,
        'kosten': kosten,
        'afschrijvingen': afschrijvingen,
        'winst': round(winst, 2),
    }


def bereken_ib(verzamelinkomen: float, params: dict) -> dict:
    """IB Box 1 calculation with brackets (uses Decimal internally).

    Args:
        verzamelinkomen: Taxable income Box 1.
        params: Fiscal parameters dict with schijf1/2/3 and heffingskorting params.

    Returns:
        Dict with keys: verzamelinkomen, bruto_ib, ahk, arbeidskorting, netto_ib, zvw.
    """
    d_vi = D(verzamelinkomen)
    jaar = params.get('jaar', 0)

    # Schijf 1
    d_s1_grens = D(params['schijf1_grens'])
    d_s1 = min(d_vi, d_s1_grens)
    d_ib1 = d_s1 * D(params['schijf1_pct']) / D('100')

    # Schijf 2
    d_s2_grens = D(params['schijf2_grens'])
    d_s2 = min(max(d_vi - d_s1_grens, D('0')), d_s2_grens - d_s1_grens)
    d_ib2 = d_s2 * D(params['schijf2_pct']) / D('100')

    # Schijf 3
    d_s3 = max(d_vi - d_s2_grens, D('0'))
    d_ib3 = d_s3 * D(params['schijf3_pct']) / D('100')

    d_bruto = d_ib1 + d_ib2 + d_ib3

    ahk = bereken_algemene_heffingskorting(verzamelinkomen, jaar, params)
    ak = bereken_arbeidskorting(verzamelinkomen, jaar)

    d_netto = max(D('0'), d_bruto - D(str(ahk)) - D(str(ak)))
    d_zvw = min(d_vi, D(params['zvw_max_grondslag'])) * D(params['zvw_pct']) / D('100')

    return {
        'verzamelinkomen': euro(d_vi),
        'bruto_ib': euro(d_bruto),
        'ahk': ahk,
        'arbeidskorting': ak,
        'netto_ib': euro(d_netto),
        'zvw': euro(d_zvw),
    }
