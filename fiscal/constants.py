"""Fiscal defaults: last-resort fallbacks when fiscale_params lacks a field.

Prefer reading from fiscale_params; these constants exist for display paths
that need a sensible default when the DB row is missing a value.
"""

URENCRITERIUM_DEFAULT = 1225

# Villataks-percentage voor eigenwoningforfait boven villataks_grens.
#
# Belastingdienst houdt dit op 2.35% sinds 2017 zonder geplande wijziging
# voor 2026 (bron: Belastingdienst Wet IB 2001 art. 3.112 lid 2,
# bevestigd via belastingdienst.nl koopwoning eigenwoningforfait-tabel
# 2026: "boven € 1.350.000: € 4.725 + 2,35% over het bedrag boven die
# grens"). Als dit ooit jaar-afhankelijk wordt, verplaats naar
# fiscale_params (migratie + dataclass + validator + /instellingen UI).
#
# B3 review fix (CODE_REVIEW_2026-04-30): eerder leefde dit als magic
# fallback `params.get('villataks_pct', 2.35)` in fiscal/berekeningen.py
# — een silent-hardcoded waarde die de CLAUDE.md regel "alle jaar-
# afhankelijke fiscale waarden uit DB" schond zonder echte DB-backing.
# Naar named constant met expliciet bronbesluit gemaakt.
VILLATAKS_PCT_DEFAULT = 2.35
