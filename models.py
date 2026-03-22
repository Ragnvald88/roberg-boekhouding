"""Dataclasses voor boekhouding — plain Python, geen ORM."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Bedrijfsgegevens:
    id: int = 1
    bedrijfsnaam: str = ''
    naam: str = ''
    functie: str = ''
    adres: str = ''
    postcode_plaats: str = ''
    kvk: str = ''
    iban: str = ''
    thuisplaats: str = ''


@dataclass
class Klant:
    id: int = 0
    naam: str = ''
    tarief_uur: float = 0.0
    retour_km: float = 0.0
    adres: str = ''
    kvk: str = ''
    actief: bool = True
    email: str = ''


@dataclass
class KlantLocatie:
    id: int
    klant_id: int
    naam: str
    retour_km: float


@dataclass
class Werkdag:
    id: int = 0
    datum: str = ''
    klant_id: int = 0
    klant_naam: str = ''  # joined from klanten
    code: str = ''
    activiteit: str = 'Waarneming dagpraktijk'
    locatie: str = ''
    uren: float = 0.0
    km: float = 0.0
    tarief: float = 0.0
    km_tarief: float = 0.23
    status: str = 'ongefactureerd'
    factuurnummer: str = ''
    opmerking: str = ''
    urennorm: bool = True
    locatie_id: int | None = None


@dataclass
class Factuur:
    id: int = 0
    nummer: str = ''
    klant_id: int = 0
    klant_naam: str = ''  # joined from klanten
    datum: str = ''
    totaal_uren: float = 0.0
    totaal_km: float = 0.0
    totaal_bedrag: float = 0.0
    pdf_pad: str = ''
    status: str = 'concept'
    betaald_datum: str = ''
    type: str = 'factuur'


@dataclass
class Uitgave:
    id: int = 0
    datum: str = ''
    categorie: str = ''
    omschrijving: str = ''
    bedrag: float = 0.0
    pdf_pad: str = ''
    is_investering: bool = False
    restwaarde_pct: float = 10.0
    levensduur_jaren: Optional[int] = None
    aanschaf_bedrag: Optional[float] = None
    zakelijk_pct: float = 100.0


@dataclass
class Banktransactie:
    id: int = 0
    datum: str = ''
    bedrag: float = 0.0
    tegenrekening: str = ''
    tegenpartij: str = ''
    omschrijving: str = ''
    categorie: str = ''
    koppeling_type: str = ''
    koppeling_id: Optional[int] = None
    csv_bestand: str = ''
    betalingskenmerk: str = ''


@dataclass
class FiscaleParams:
    jaar: int = 0
    zelfstandigenaftrek: float = 0.0
    startersaftrek: Optional[float] = None
    mkb_vrijstelling_pct: float = 0.0
    kia_ondergrens: float = 0.0
    kia_bovengrens: float = 0.0
    kia_pct: float = 0.0
    kia_drempel_per_item: float = 450.0
    km_tarief: float = 0.0
    schijf1_grens: float = 0.0
    schijf1_pct: float = 0.0
    schijf2_grens: float = 0.0
    schijf2_pct: float = 0.0
    schijf3_pct: float = 0.0
    ahk_max: float = 0.0
    ahk_afbouw_pct: float = 0.0
    ahk_drempel: float = 0.0
    ak_max: float = 0.0
    zvw_pct: float = 0.0
    zvw_max_grondslag: float = 0.0
    repr_aftrek_pct: float = 80.0
    # Eigen woning / Hillen / urencriterium (per jaar)
    ew_forfait_pct: float = 0.35
    villataks_grens: float = 1_350_000
    wet_hillen_pct: float = 0.0
    urencriterium: float = 1225
    # IB-input velden (per jaar opgeslagen)
    aov_premie: float = 0.0
    woz_waarde: float = 0.0
    hypotheekrente: float = 0.0
    voorlopige_aanslag_betaald: float = 0.0
    # PVV premiegrondslag (2024: 38098, 2025+: = schijf1_grens)
    pvv_premiegrondslag: float = 0.0
    # Eigen woning toerekening
    ew_naar_partner: bool = True  # Default: allocate to partner (Boekhouder practice)
    # Voorlopige aanslag ZVW (apart van IB)
    voorlopige_aanslag_zvw: float = 0.0
    # Partner inkomen (voor verzamelinkomen aangifte)
    partner_bruto_loon: float = 0.0
    partner_loonheffing: float = 0.0
    # Arbeidskorting brackets as JSON (DB-driven, fallback to code constants)
    arbeidskorting_brackets: str = ''
    # PVV component rates (DB-driven, fallback to hardcoded constants)
    pvv_aow_pct: float = 17.90
    pvv_anw_pct: float = 0.10
    pvv_wlz_pct: float = 9.65
    # Box 3 per-year inputs (peildatum 1 jan)
    box3_bank_saldo: float = 0.0
    box3_overige_bezittingen: float = 0.0
    box3_schulden: float = 0.0
    # Box 3 per-year fiscal parameters
    box3_heffingsvrij_vermogen: float = 57000.0
    box3_rendement_bank_pct: float = 1.03
    box3_rendement_overig_pct: float = 6.17
    box3_rendement_schuld_pct: float = 2.46
    box3_tarief_pct: float = 36.0
    box3_drempel_schulden: float = 3700.0
    box3_fiscaal_partner: bool = True
    # ZA/SA toggles (per year — ZA phasing out, SA max 3x in first 5 years)
    za_actief: bool = True
    sa_actief: bool = False
    # Lijfrentepremie (jaarruimte, Box 1 aftrekpost)
    lijfrente_premie: float = 0.0
    # Balance sheet manual inputs (per year)
    balans_bank_saldo: float = 0.0
    balans_crediteuren: float = 0.0
    balans_overige_vorderingen: float = 0.0
    balans_overige_schulden: float = 0.0
    # Jaarafsluiting workflow status
    jaarafsluiting_status: str = 'concept'


@dataclass
class AangifteDocument:
    id: int = 0
    jaar: int = 0
    categorie: str = ''
    documenttype: str = ''
    bestandsnaam: str = ''
    bestandspad: str = ''
    upload_datum: str = ''
    notitie: str = ''
