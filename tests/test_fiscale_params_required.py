"""Silent-fallback loophole regression — completes the work from commit 235b76c.

Commit 235b76c made pvv_aow/anw/wlz_pct, repr_aftrek_pct and ew_forfait_pct
required (loud KeyError instead of silent hardcoded defaults). This test
module covers the remaining 11 fiscal parameter fields that still had
silent `kwargs.get(..., <hardcoded_default>)` fallbacks in
`upsert_fiscale_params` — now also required.
"""

import pytest
from database import upsert_fiscale_params


REQUIRED_FIELDS = [
    'villataks_grens', 'wet_hillen_pct', 'urencriterium',
    'pvv_premiegrondslag', 'arbeidskorting_brackets',
    'box3_heffingsvrij_vermogen', 'box3_rendement_bank_pct',
    'box3_rendement_overig_pct', 'box3_rendement_schuld_pct',
    'box3_tarief_pct', 'box3_drempel_schulden',
]


def _valid_kwargs_2027():
    """Full kwargs dict matching current INSERT signature. Update when schema changes."""
    return dict(
        jaar=2027,
        # IB schijven
        schijf1_grens=80000, schijf1_pct=36.97,
        schijf2_grens=115000, schijf2_pct=49.50,
        schijf3_pct=49.50,
        # Heffingskortingen
        ahk_max=3362, ahk_afbouw_pct=6.0, ahk_drempel=24000,
        ak_max=5712,
        # ZVW
        zvw_pct=5.32, zvw_max_grondslag=71625,
        # Fiscale aftrek-percentages (al required sinds 235b76c)
        repr_aftrek_pct=80, ew_forfait_pct=0.35,
        pvv_aow_pct=17.90, pvv_anw_pct=0.10, pvv_wlz_pct=9.65,
        # Nieuw required in deze task:
        villataks_grens=1_350_000, wet_hillen_pct=66.0,
        urencriterium=1225, pvv_premiegrondslag=40000,
        arbeidskorting_brackets='[]',
        box3_heffingsvrij_vermogen=57000,
        box3_rendement_bank_pct=1.44,
        box3_rendement_overig_pct=5.88,
        box3_rendement_schuld_pct=2.61,
        box3_tarief_pct=36,
        box3_drempel_schulden=3700,
        # Overige
        mkb_vrijstelling_pct=12.70, kia_pct=28,
        kia_ondergrens=2801, kia_bovengrens=69765,
        zelfstandigenaftrek=3750, startersaftrek=2123,
        km_tarief=0.23,
    )


@pytest.mark.asyncio
async def test_upsert_accepts_complete_kwargs(db):
    """Sanity: volledige kwargs werkt."""
    await upsert_fiscale_params(db, **_valid_kwargs_2027())


@pytest.mark.asyncio
@pytest.mark.parametrize('missing_field', REQUIRED_FIELDS)
async def test_upsert_fails_loud_on_missing_required_field(db, missing_field):
    """Ontbrekend required-field -> KeyError met veldnaam in message."""
    kwargs = _valid_kwargs_2027()
    del kwargs[missing_field]
    with pytest.raises(KeyError, match=missing_field):
        await upsert_fiscale_params(db, **kwargs)
