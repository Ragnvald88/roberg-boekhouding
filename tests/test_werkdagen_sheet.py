"""Tests voor Werkdagen-sheet port (chip-mapping, segment-filter, subtitle).

Spec: docs/superpowers/specs/2026-04-17-werkdagen-sheet-port-design.md

Pure helpers worden direct getest; integratie-gedrag (subtitle, summary)
via DB-fixture + de werkdagen-databasefuncties die de pagina aanroept.
"""

import pytest
from types import SimpleNamespace

from pages.werkdagen import (
    _chip_class_for, _segment_matches, _CODE_LABELS,
    SEG_ALL, SEG_UNINVOICED, SEG_ANW,
)
from database import add_klant, add_werkdag, get_werkdagen


# ---------- Pure helper: _chip_class_for ----------

class TestChipClass:
    """Chip-kleur-mapping volgt de spec:
    urennorm=True → pos; ANW_* → info; ACHTERWACHT → neutral; rest → warn.
    """

    def test_urennorm_true_yields_pos(self):
        # Patient-care codes — telt voor urencriterium
        for code in ('WERKDAG', 'WEEKEND_DAG', 'AVOND', 'NACHT'):
            assert _chip_class_for(code, urennorm=True) == 'pos'

    def test_anw_codes_yield_info(self):
        for code in ('ANW_AVOND', 'ANW_NACHT', 'ANW_WEEKEND'):
            assert _chip_class_for(code, urennorm=False) == 'info'

    def test_achterwacht_yields_neutral(self):
        assert _chip_class_for('ACHTERWACHT', urennorm=False) == 'neutral'

    def test_other_non_urennorm_yields_warn(self):
        for code in ('CONGRES', 'OPLEIDING', 'OVERIG_ZAK'):
            assert _chip_class_for(code, urennorm=False) == 'warn'

    def test_urennorm_overrides_code(self):
        # Defensief: zelfs als een ANW-code per ongeluk urennorm=True heeft,
        # dan telt 'm voor urencriterium en moet hij pos kleuren.
        assert _chip_class_for('ANW_AVOND', urennorm=True) == 'pos'


# ---------- Pure helper: _segment_matches ----------

def _wd(factuurnummer='', code='WERKDAG'):
    """Mini-werkdag-namespace voor segment-tests."""
    return SimpleNamespace(factuurnummer=factuurnummer, code=code)


class TestSegmentMatches:

    def test_seg_all_matches_everything(self):
        assert _segment_matches(_wd(), SEG_ALL) is True
        assert _segment_matches(_wd(factuurnummer='2026-001'), SEG_ALL) is True
        assert _segment_matches(_wd(code='ANW_NACHT'), SEG_ALL) is True

    def test_uninvoiced_only_matches_empty_factuurnummer(self):
        assert _segment_matches(_wd(factuurnummer=''), SEG_UNINVOICED) is True
        assert _segment_matches(_wd(factuurnummer='2026-001'), SEG_UNINVOICED) is False
        # None ook als ongefactureerd behandelen
        assert _segment_matches(_wd(factuurnummer=None), SEG_UNINVOICED) is True

    def test_anw_matches_all_anw_variants(self):
        for code in ('ANW_AVOND', 'ANW_NACHT', 'ANW_WEEKEND'):
            assert _segment_matches(_wd(code=code), SEG_ANW) is True, \
                f'{code} moet matchen op SEG_ANW'

    def test_anw_does_not_match_non_anw(self):
        for code in ('WERKDAG', 'ACHTERWACHT', 'CONGRES', ''):
            assert _segment_matches(_wd(code=code), SEG_ANW) is False, \
                f'{code} mag NIET matchen op SEG_ANW'


# ---------- Code-labels mapping ----------

class TestCodeLabels:

    def test_all_known_codes_have_label(self):
        # Codes uit components.werkdag_form.CODES — moeten allemaal een label hebben
        from components.werkdag_form import CODES
        missing = [c for c in CODES if c not in _CODE_LABELS]
        assert not missing, f'Codes zonder chip-label: {missing}'

    def test_labels_are_short(self):
        # Chip is smal — labels max 7 chars
        for code, label in _CODE_LABELS.items():
            assert len(label) <= 7, f'{code}={label!r} is te lang voor chip'


# ---------- Subtitle berekening (via DB) ----------

@pytest.fixture
async def seeded_db(db):
    """DB met 1 klant — geen werkdagen vooraf."""
    await add_klant(db, naam='Praktijk Test', tarief_uur=85.0, retour_km=20)
    return db


class TestSubtitleCalculation:
    """Subtitle = '{N dagen in jaar} · {urencrit-uren} uur telt voor urencriterium'.

    Berekening: alle werkdagen van het jaar (year-wide, niet filter-afhankelijk),
    en uren-som over rijen met urennorm=True.
    """

    @pytest.mark.asyncio
    async def test_only_urennorm_counts_for_subtitle(self, seeded_db):
        from database import get_klanten
        kid = (await get_klanten(seeded_db))[0].id

        # Reguliere werkdag (telt mee)
        await add_werkdag(seeded_db, datum='2026-02-01', klant_id=kid,
                          uren=8, tarief=85.0, code='WERKDAG', urennorm=1)
        # ANW (telt NIET mee)
        await add_werkdag(seeded_db, datum='2026-02-02', klant_id=kid,
                          uren=12, tarief=95.0, code='ANW_NACHT', urennorm=0)
        # Achterwacht (telt NIET mee)
        await add_werkdag(seeded_db, datum='2026-02-03', klant_id=kid,
                          uren=10, tarief=85.0, code='ACHTERWACHT', urennorm=0)

        all_year = await get_werkdagen(seeded_db, jaar=2026)
        assert len(all_year) == 3
        urencrit_uren = sum(w.uren for w in all_year if w.urennorm)
        assert urencrit_uren == 8.0  # alleen de WERKDAG-row telt

    @pytest.mark.asyncio
    async def test_subtitle_unaffected_by_segment_filter(self, seeded_db):
        """Subtitle is year-wide; segment-filter mag het cijfer niet veranderen."""
        from database import get_klanten
        kid = (await get_klanten(seeded_db))[0].id

        await add_werkdag(seeded_db, datum='2026-01-15', klant_id=kid,
                          uren=8, tarief=85.0, factuurnummer='2026-001',
                          urennorm=1)
        await add_werkdag(seeded_db, datum='2026-02-15', klant_id=kid,
                          uren=8, tarief=85.0, urennorm=1)

        # Subtitle-bron: get_werkdagen(jaar=...) zonder verdere filters
        all_year = await get_werkdagen(seeded_db, jaar=2026)
        urencrit_uren = sum(w.uren for w in all_year if w.urennorm)

        # Apply segment-filter ongefactureerd in Python (zoals page doet)
        ongefact = [w for w in all_year if _segment_matches(w, SEG_UNINVOICED)]

        # Filter raakt subtitle NIET
        assert urencrit_uren == 16.0, 'subtitle moet alle uren over jaar zien'
        assert len(ongefact) == 1, 'segment-filter beperkt rij-set'
        # Subtitle berekening leunt op all_year, niet op ongefact
        ongefact_uren = sum(w.uren for w in ongefact if w.urennorm)
        assert ongefact_uren == 8.0
        assert urencrit_uren != ongefact_uren  # bewijst onafhankelijkheid


# ---------- Multi-klant grouping ----------

class TestMultiKlantGrouping:
    """De page groepeert geselecteerde rows per klant en sorteert op
    aantal dagen DESC voor de picker. Hier getest via dezelfde algoritmiek
    op pure dicts (de page doet hetzelfde inline).
    """

    def _group(self, rows):
        """Replica van de logica in update_bulk_bar / _build_multi_menu."""
        groups = {}
        for r in rows:
            kid = r['klant_id']
            groups.setdefault(kid, {'naam': r['klant_naam'], 'rows': []})
            groups[kid]['rows'].append(r)
        return sorted(groups.items(), key=lambda kv: -len(kv[1]['rows']))

    def test_groups_by_klant_id(self):
        rows = [
            {'klant_id': 1, 'klant_naam': 'A', 'uren': 8, 'id': 10},
            {'klant_id': 2, 'klant_naam': 'B', 'uren': 8, 'id': 11},
            {'klant_id': 1, 'klant_naam': 'A', 'uren': 4, 'id': 12},
        ]
        result = self._group(rows)
        assert len(result) == 2
        # Klant 1 heeft 2 rijen → eerst
        assert result[0][0] == 1
        assert len(result[0][1]['rows']) == 2
        assert result[1][0] == 2
        assert len(result[1][1]['rows']) == 1

    def test_single_klant_yields_one_group(self):
        rows = [{'klant_id': 1, 'klant_naam': 'A', 'uren': 8, 'id': 1}]
        assert len(self._group(rows)) == 1

    def test_empty_yields_empty(self):
        assert self._group([]) == []

    def test_three_klanten_sorted_by_count_desc(self):
        rows = [
            {'klant_id': 1, 'klant_naam': 'A', 'uren': 8, 'id': 1},
            {'klant_id': 2, 'klant_naam': 'B', 'uren': 8, 'id': 2},
            {'klant_id': 2, 'klant_naam': 'B', 'uren': 8, 'id': 3},
            {'klant_id': 3, 'klant_naam': 'C', 'uren': 8, 'id': 4},
            {'klant_id': 3, 'klant_naam': 'C', 'uren': 8, 'id': 5},
            {'klant_id': 3, 'klant_naam': 'C', 'uren': 8, 'id': 6},
        ]
        result = self._group(rows)
        # Volgorde: C (3 rijen), B (2 rijen), A (1 rij)
        assert [kid for kid, _ in result] == [3, 2, 1]


# ---------- Summary counter calculation ----------

class TestSummaryCounter:
    """Summary toont {rows} · ∑ {uren}u · {km}km · €{bedrag} over filtered rows.

    Dit is dezelfde berekening die refresh_table doet in pages/werkdagen.py.
    """

    @pytest.mark.asyncio
    async def test_summary_reflects_filter(self, seeded_db):
        from database import get_klanten
        kid = (await get_klanten(seeded_db))[0].id

        await add_werkdag(seeded_db, datum='2026-01-15', klant_id=kid,
                          uren=8, km=20, tarief=85.0, km_tarief=0.23,
                          factuurnummer='2026-001')
        await add_werkdag(seeded_db, datum='2026-02-15', klant_id=kid,
                          uren=10, km=30, tarief=85.0, km_tarief=0.23)

        all_year = await get_werkdagen(seeded_db, jaar=2026)
        # SEG_ALL — alle rijen
        rows_all = [w for w in all_year if _segment_matches(w, SEG_ALL)]
        assert sum(w.uren for w in rows_all) == 18.0
        assert sum(w.km for w in rows_all) == 50.0

        # SEG_UNINVOICED — alleen 2e rij
        rows_uninv = [w for w in all_year if _segment_matches(w, SEG_UNINVOICED)]
        assert len(rows_uninv) == 1
        assert sum(w.uren for w in rows_uninv) == 10.0
        assert sum(w.km for w in rows_uninv) == 30.0
