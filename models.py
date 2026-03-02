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
    betaald: bool = False
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


@dataclass
class FiscaleParams:
    jaar: int = 0
    zelfstandigenaftrek: float = 0.0
    startersaftrek: Optional[float] = None
    mkb_vrijstelling_pct: float = 0.0
    kia_ondergrens: float = 0.0
    kia_bovengrens: float = 0.0
    kia_pct: float = 0.0
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
