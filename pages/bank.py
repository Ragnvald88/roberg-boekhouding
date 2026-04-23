"""/bank — soft redirect to /transacties.

Preserves bookmarks one release. Remove this file after the next release
cuts. See docs/superpowers/specs/2026-04-22-bank-kosten-consolidation-design.md
§6 Phase 5.
"""
from nicegui import ui


@ui.page('/bank')
async def bank_redirect():
    ui.navigate.to('/transacties')
