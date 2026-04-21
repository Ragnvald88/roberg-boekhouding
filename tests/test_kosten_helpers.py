"""Pure helpers for the kosten page — no DB."""
from components.kosten_helpers import (
    derive_status, match_tokens, tegenpartij_color, initials,
)


def test_derive_status_hidden_when_genegeerd():
    row = {"id_bank": 1, "genegeerd": 1, "id_uitgave": None,
           "categorie": "", "pdf_pad": ""}
    assert derive_status(row) == "hidden"


def test_derive_status_ongecat_when_no_uitgave():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": None,
           "categorie": "", "pdf_pad": ""}
    assert derive_status(row) == "ongecategoriseerd"


def test_derive_status_ongecat_when_empty_categorie():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "", "pdf_pad": ""}
    assert derive_status(row) == "ongecategoriseerd"


def test_derive_status_ontbreekt_when_no_pdf():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "Kantoor", "pdf_pad": ""}
    assert derive_status(row) == "ontbreekt"


def test_derive_status_compleet():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "Kantoor", "pdf_pad": "/tmp/x.pdf"}
    assert derive_status(row) == "compleet"


def test_derive_status_manual_compleet():
    """Manual uitgave: id_bank None, id_uitgave set."""
    row = {"id_bank": None, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "Kantoor", "pdf_pad": "/tmp/x.pdf"}
    assert derive_status(row) == "compleet"


def test_match_tokens_hit_simple():
    assert match_tokens("KPN B.V.", "KPN_maart2026") >= 1


def test_match_tokens_hit_case_and_punct():
    assert match_tokens(
        "Boekhouder Verzekering",
        "boekhouder-verzekering_q2") >= 1


def test_match_tokens_miss():
    assert match_tokens("Shell", "Apple") == 0


def test_match_tokens_ignores_short_tokens():
    """Tokens < 4 chars don't count."""
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
    assert initials("Test Berg") == "RB"


def test_initials_one_word():
    assert initials("KPN") == "KP"


def test_initials_many_words():
    assert initials("SPH Pensioenfonds Nederland") == "SP"


def test_initials_empty():
    assert initials("") == "?"


def test_initials_strips_punct():
    assert initials("Boekhouder Verzekering") == "VS"
