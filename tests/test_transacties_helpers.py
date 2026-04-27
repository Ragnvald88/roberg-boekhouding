"""Pure helpers for the kosten page — no DB."""
from components.transacties_helpers import (
    derive_status, match_tokens, tegenpartij_color, initials,
)


def test_derive_status_hidden_when_genegeerd():
    row = {"id_bank": 1, "genegeerd": 1, "id_uitgave": None,
           "categorie": "", "pdf_pad": "", "bedrag": -10.0}
    assert derive_status(row) == "prive_verborgen"


def test_derive_status_ongecat_when_no_uitgave():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": None,
           "categorie": "", "pdf_pad": "", "bedrag": -10.0}
    assert derive_status(row) == "ongecategoriseerd"


def test_derive_status_ongecat_when_empty_categorie():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "", "pdf_pad": "", "bedrag": -10.0}
    assert derive_status(row) == "ongecategoriseerd"


def test_derive_status_ontbreekt_when_no_pdf():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "Kantoor", "pdf_pad": "", "bedrag": -10.0}
    assert derive_status(row) == "ontbreekt_bon"


def test_derive_status_compleet():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "Kantoor", "pdf_pad": "/tmp/x.pdf",
           "bedrag": -10.0}
    assert derive_status(row) == "compleet"


def test_derive_status_manual_compleet():
    """Manual uitgave: id_bank None, id_uitgave set."""
    row = {"id_bank": None, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "Kantoor", "pdf_pad": "/tmp/x.pdf",
           "bedrag": -10.0}
    assert derive_status(row) == "compleet"


def test_derive_status_prive_verborgen_wins():
    row = {"id_bank": 1, "id_uitgave": 5, "genegeerd": 1,
           "categorie": "Telefoon/KPN", "pdf_pad": "/p.pdf",
           "bedrag": -10.0, "koppeling_type": None}
    from components.transacties_helpers import derive_status
    assert derive_status(row) == "prive_verborgen"


def test_derive_status_gekoppeld_factuur_for_positive_with_match():
    row = {"id_bank": 1, "id_uitgave": None, "genegeerd": 0,
           "categorie": "", "pdf_pad": "",
           "bedrag": 100.0, "koppeling_type": "factuur", "koppeling_id": 42}
    from components.transacties_helpers import derive_status
    assert derive_status(row) == "gekoppeld_factuur"


def test_derive_status_gecategoriseerd_positive():
    row = {"id_bank": 1, "id_uitgave": None, "genegeerd": 0,
           "categorie": "Omzet", "pdf_pad": "",
           "bedrag": 200.0, "koppeling_type": None}
    from components.transacties_helpers import derive_status
    assert derive_status(row) == "gecategoriseerd"


def test_derive_status_ongecategoriseerd_positive():
    row = {"id_bank": 2, "id_uitgave": None, "genegeerd": 0,
           "categorie": "", "pdf_pad": "",
           "bedrag": 300.0, "koppeling_type": None}
    from components.transacties_helpers import derive_status
    assert derive_status(row) == "ongecategoriseerd"


def test_derive_status_debit_ontbreekt_bon():
    row = {"id_bank": 3, "id_uitgave": 9, "genegeerd": 0,
           "categorie": "Kleine aankopen", "pdf_pad": "",
           "bedrag": -50.0, "koppeling_type": None}
    from components.transacties_helpers import derive_status
    assert derive_status(row) == "ontbreekt_bon"


def test_derive_status_debit_compleet():
    row = {"id_bank": 4, "id_uitgave": 11, "genegeerd": 0,
           "categorie": "Kleine aankopen", "pdf_pad": "/tmp/x.pdf",
           "bedrag": -50.0, "koppeling_type": None}
    from components.transacties_helpers import derive_status
    assert derive_status(row) == "compleet"


def test_derive_status_debit_ongecategoriseerd_no_uitgave():
    row = {"id_bank": 5, "id_uitgave": None, "genegeerd": 0,
           "categorie": "", "pdf_pad": "",
           "bedrag": -10.0, "koppeling_type": None}
    from components.transacties_helpers import derive_status
    assert derive_status(row) == "ongecategoriseerd"


def test_derive_status_debit_ongecategoriseerd_empty_cat():
    row = {"id_bank": 6, "id_uitgave": 13, "genegeerd": 0,
           "categorie": "", "pdf_pad": "",
           "bedrag": -10.0, "koppeling_type": None}
    from components.transacties_helpers import derive_status
    assert derive_status(row) == "ongecategoriseerd"


def test_match_tokens_hit_simple():
    assert match_tokens("KPN B.V.", "KPN_maart2026") >= 1


def test_match_tokens_hit_case_and_punct():
    assert match_tokens(
        "Boekhouder Verzekering",
        "boekhouder-verzekering_q2") >= 1


def test_match_tokens_miss():
    assert match_tokens("Shell", "Apple") == 0


def test_match_tokens_ignores_short_tokens():
    """Tokens < 3 chars don't count."""
    # 'BV' is 2 chars, 'NL' is 2 chars — both ignored.
    assert match_tokens("BV NL", "BV NL other") == 0


def test_match_tokens_multi_hit():
    assert match_tokens(
        "Microsoft Ireland",
        "microsoft365-ireland_2026") >= 1


def test_tegenpartij_color_deterministic():
    assert tegenpartij_color("KPN B.V.") == tegenpartij_color("KPN B.V.")
    assert tegenpartij_color("A") != tegenpartij_color("B")


def test_tegenpartij_color_is_hsl():
    color = tegenpartij_color("KPN B.V.")
    assert color.startswith("hsl(")


def test_initials_two_word():
    assert initials("Test Berg") == "TB"


def test_initials_one_word():
    assert initials("KPN") == "KP"


def test_initials_many_words():
    assert initials("SPH Pensioenfonds Nederland") == "SP"


def test_initials_empty():
    assert initials("") == "?"


def test_initials_strips_punct():
    assert initials("Boekhouder Verzekering") == "BV"


def test_bulk_set_cat_iterates_snapshot_not_live_selection():
    """A15 regression: source-pin guard.

    The /transacties bulk-categorie handler captures
    ``selected = list(table_ref['table'].selected or [])`` at handler
    entry. The inner ``apply_bulk_cat`` loop must iterate that snapshot,
    NOT ``table_ref['table'].selected`` (live ref) — otherwise a stray
    click between iterations widens the bulk's scope mid-loop, the same
    anti-pattern previously fixed for ``bulk_negeren`` and
    ``bulk_delete``.

    Behaviour lives inside an async NiceGUI dialog handler that needs a
    UI runtime to exercise. Source-pin keeps the contract enforced.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / 'pages' / 'transacties.py'
    text = src.read_text()

    # Match the apply_bulk_cat block — must iterate the captured snapshot.
    match = re.search(
        r'async\s+def\s+apply_bulk_cat\s*\(\s*\)\s*:\s*'
        r'(?P<body>.*?)(?=\n\s{24}ui\.button)',
        text,
        re.DOTALL,
    )
    assert match, "apply_bulk_cat handler not found in pages/transacties.py"
    body = match.group('body')

    assert 'for r in selected:' in body, (
        "apply_bulk_cat must iterate the `selected` snapshot, not "
        "table_ref['table'].selected (A15 regression — see bulk_negeren "
        "and bulk_delete for the same pattern)."
    )
    assert "table_ref['table'].selected" not in body, (
        "apply_bulk_cat must not read live selection inside the loop "
        "(A15 regression)."
    )
