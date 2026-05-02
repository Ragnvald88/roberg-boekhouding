"""Agenda service-layer.

Read + mutation API for the /agenda page. Pure helpers (categorize_werkdag,
derive_werkdag_status_label, parse_weekdays) sit at the top so they can be
imported standalone for testing without DB setup.

UI-free: no nicegui imports. DB-aware: imports from database.py.
Frozen dataclasses for view-objects to keep Swift-port mental model intact.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date as _date, timedelta as _timedelta
from typing import Literal

import aiosqlite

import database
from database import ConflictError, ValidationError
from domain.codes import CODES as _WERKDAG_CODES, ZERO_UREN_CODES as _ZERO_UREN_CODES
from services.holidays import dutch_holidays

# Note: orphan factuurnummer (factuurnummer != '' but factuur_status == '')
# falls through to 'ongefactureerd' here as defensive fallback. UI-laag
# (MonthGrid, Day-Inspector in Sessie 3) kan separately detecteren via
# `factuurnummer != '' and factuur_status == ''` voor een warning-indicator
# zonder dat dit de status-bar-kleur beïnvloedt.


# ---------------------------------------------------------------------------
# Pure helpers (no DB, no UI)
# ---------------------------------------------------------------------------

WerkdagCategory = Literal['dagpraktijk', 'anw', 'overig']

_DAGPRAKTIJK_CODES = frozenset({'WERKDAG', 'WEEKEND_DAG', ''})
_ANW_CODES_PREFIX = 'ANW_'
_ANW_LEGACY_CODES = frozenset({'AVOND', 'NACHT'})


def categorize_werkdag(code: str) -> WerkdagCategory:
    """Categorize a werkdag by code for type-based coloring.

    Returns:
        'dagpraktijk' for WERKDAG/WEEKEND_DAG/empty
        'anw' for ANW_* codes and legacy AVOND/NACHT
        'overig' for all other codes (ACHTERWACHT/CONGRES/OPLEIDING/OVERIG_ZAK/unknown)
    """
    if code in _DAGPRAKTIJK_CODES:
        return 'dagpraktijk'
    if code.startswith(_ANW_CODES_PREFIX) or code in _ANW_LEGACY_CODES:
        return 'anw'
    return 'overig'


WerkdagStatusLabel = Literal[
    'ongefactureerd', 'concept', 'verstuurd', 'verlopen', 'betaald'
]


def derive_werkdag_status_label(werkdag, today: _date) -> WerkdagStatusLabel:
    """Derive UI status label from werkdag + factuur state.

    werkdag must have attributes: factuurnummer, factuur_status, factuur_vervaldatum.

    'verlopen' is a pure-function derivation: factuur is 'verstuurd' AND
    vervaldatum < today. No DB-update needed for this transition.

    Returns 'ongefactureerd' as defensive fallback for unknown status values.
    """
    if not werkdag.factuurnummer:
        return 'ongefactureerd'
    status = werkdag.factuur_status
    if status == 'concept':
        return 'concept'
    if status == 'betaald':
        return 'betaald'
    if status == 'verstuurd':
        verval = werkdag.factuur_vervaldatum
        if verval:
            try:
                if _date.fromisoformat(verval) < today:
                    return 'verlopen'
            except ValueError:
                pass  # invalid datum string — fall through to 'verstuurd'
        return 'verstuurd'
    # Unknown status — defensive fallback
    return 'ongefactureerd'


def parse_weekdays(csv: str) -> list[int]:
    """Parse weekdays CSV ("1,3,5") to sorted unique list of ints 1-7.

    Tolerates whitespace around commas. Raises ValidationError on empty,
    non-numeric, out-of-range (must be 1-7), or duplicates.
    """
    if not csv:
        raise ValidationError("weekdays mag niet leeg zijn")
    try:
        parts = [int(p.strip()) for p in csv.split(',')]
    except ValueError:
        raise ValidationError(f"weekdays bevat niet-numerieke waarde: '{csv}'")
    if any(p < 1 or p > 7 for p in parts):
        raise ValidationError(f"weekdays moeten tussen 1-7 liggen, kreeg: {parts}")
    if len(set(parts)) != len(parts):
        raise ValidationError(f"weekdays bevat duplicaten: {parts}")
    return sorted(parts)


# ---------------------------------------------------------------------------
# Pattern CRUD (service-layer wrappers around database.db_*_pattern helpers)
# ---------------------------------------------------------------------------

# CODES komt uit domain.codes (UI-free) — geen NiceGUI-import via components/werkdag_form.
_VALID_PATTERN_CODES = frozenset(_WERKDAG_CODES.keys())


@dataclass(frozen=True)
class Pattern:
    """User-facing recurring-pattern view. weekdays is parsed tuple[int, ...] (vs DB-CSV)."""
    id: int
    klant_id: int
    weekdays: tuple[int, ...]
    start_minuten: int
    eind_minuten: int
    code: str
    activiteit: str
    valid_from: str
    valid_until: str
    actief: bool


def _validate_pattern_code(code: str) -> None:
    if code not in _VALID_PATTERN_CODES:
        raise ValidationError(
            f"Ongeldige code '{code}'. Toegestaan: {sorted(_VALID_PATTERN_CODES)}"
        )


def _validate_pattern_minuten(start: int, eind: int) -> None:
    if not (0 <= start < 1440):
        raise ValidationError(f"start_minuten {start} buiten 0-1439")
    if not (0 < eind <= 1440):
        raise ValidationError(f"eind_minuten {eind} buiten 1-1440")
    if eind <= start:
        raise ValidationError(f"eind_minuten ({eind}) moet > start_minuten ({start})")


def _validate_pattern_weekdays(weekdays: list[int]) -> None:
    if not weekdays:
        raise ValidationError("weekdays mag niet leeg zijn")
    if any(w < 1 or w > 7 for w in weekdays):
        raise ValidationError(f"weekdays moeten 1-7 zijn, kreeg: {weekdays}")
    if len(set(weekdays)) != len(weekdays):
        raise ValidationError(f"weekdays bevat duplicaten: {weekdays}")


async def add_pattern(db_path, klant_id: int, weekdays: list[int],
                      start_minuten: int, eind_minuten: int,
                      code: str = 'WERKDAG',
                      activiteit: str = 'Waarneming dagpraktijk',
                      valid_from: str = '', valid_until: str = '') -> int:
    """Add new recurring pattern. NIET year-locked (projection-data, not fiscal facts).

    Validates weekdays (1-7, no duplicates, non-empty), minuten range, and code.
    """
    _validate_pattern_weekdays(weekdays)
    _validate_pattern_minuten(start_minuten, eind_minuten)
    _validate_pattern_code(code)
    csv = ','.join(str(w) for w in sorted(set(weekdays)))
    return await database.db_add_pattern(
        db_path, klant_id=klant_id, weekdays=csv,
        start_minuten=start_minuten, eind_minuten=eind_minuten,
        code=code, activiteit=activiteit,
        valid_from=valid_from, valid_until=valid_until,
    )


async def list_patterns_for_klant(db_path, klant_id: int,
                                   include_inactive: bool = False) -> list[Pattern]:
    rows = await database.db_list_patterns_for_klant(
        db_path, klant_id, include_inactive=include_inactive,
    )
    return [
        Pattern(
            id=r.id, klant_id=r.klant_id,
            weekdays=tuple(parse_weekdays(r.weekdays)),
            start_minuten=r.start_minuten, eind_minuten=r.eind_minuten,
            code=r.code, activiteit=r.activiteit,
            valid_from=r.valid_from, valid_until=r.valid_until,
            actief=r.actief,
        ) for r in rows
    ]


async def update_pattern(db_path, pattern_id: int, **fields) -> None:
    """NIET year-locked. Validates known fields if provided.

    Accepts 'weekdays' as list[int] OR CSV-string ("1,3,5"); both are
    validated and canonicalised to CSV before write. Other input types
    raise ValidationError.

    Cross-field validation: if start_minuten or eind_minuten changes, fetch
    existing to verify the resulting (start, eind) pair is valid.

    Validation errors are *collected* — caller gets one ValidationError
    with all problems joined by '; ' (better UX than first-error-wins).
    """
    errors: list[str] = []

    if 'weekdays' in fields:
        wd = fields['weekdays']
        if isinstance(wd, str):
            try:
                wd = parse_weekdays(wd)
            except ValidationError as e:
                errors.append(str(e))
                wd = None
        elif isinstance(wd, tuple):
            # Pattern.weekdays is tuple — accept round-trip without coercion at caller.
            wd = list(wd)
        elif not isinstance(wd, list):
            errors.append(
                f"weekdays moet list[int]/tuple[int,...] of CSV-string zijn, "
                f"kreeg {type(wd).__name__}"
            )
            wd = None
        if wd is not None:
            try:
                _validate_pattern_weekdays(wd)
                fields['weekdays'] = ','.join(str(w) for w in sorted(set(wd)))
            except ValidationError as e:
                errors.append(str(e))

    if 'start_minuten' in fields or 'eind_minuten' in fields:
        existing = await database.db_get_pattern(db_path, pattern_id)
        if existing is None:
            raise ConflictError(f"Pattern {pattern_id} bestaat niet")
        start = fields.get('start_minuten', existing.start_minuten)
        eind = fields.get('eind_minuten', existing.eind_minuten)
        try:
            _validate_pattern_minuten(start, eind)
        except ValidationError as e:
            errors.append(str(e))

    if 'code' in fields:
        try:
            _validate_pattern_code(fields['code'])
        except ValidationError as e:
            errors.append(str(e))

    if errors:
        raise ValidationError('; '.join(errors))

    await database.db_update_pattern(db_path, pattern_id, **fields)


async def delete_pattern(db_path, pattern_id: int) -> None:
    """Soft delete: SET actief=0. NIET year-locked. Idempotent."""
    await database.db_delete_pattern_soft(db_path, pattern_id)


# ---------------------------------------------------------------------------
# Blocker CRUD + holiday-merge
# ---------------------------------------------------------------------------

# 'holiday' is bewust UITGESLOTEN — die wordt computed via dutch_holidays en
# is geen user-toevoegbaar kind. DB CHECK constraint voorkomt het ook, maar
# we faken 'm hier expliciet om een nettere ValidationError te gooien dan een
# IntegrityError uit SQLite.
_VALID_BLOCKER_KINDS = frozenset({'vacation', 'sick', 'training'})


@dataclass(frozen=True)
class Blocker:
    """User-facing blocker view. Includes computed holidays.

    id is None for computed holidays (not in DB). User-blockers have id from DB.
    """
    id: int | None
    datum: _date
    kind: str            # 'vacation' | 'sick' | 'training' | 'holiday'
    label: str


async def add_blocker(db_path, datum: _date, kind: str, label: str = '') -> int:
    """Add user-blocker. Year-locked.

    Raises:
        ValidationError: invalid kind (incl. 'holiday')
        ConflictError:   blocker already exists for datum, OR werkdag exists for datum
        YearLockedError: datum in afgesloten jaar
    """
    if kind not in _VALID_BLOCKER_KINDS:
        raise ValidationError(
            f"Invalid kind '{kind}'. Toegestaan: {sorted(_VALID_BLOCKER_KINDS)}"
        )
    datum_str = datum.isoformat()
    await database.assert_year_writable(db_path, datum_str)
    # Check werkdag conflict
    n = await database.db_count_werkdagen_op_datum(db_path, datum_str)
    if n > 0:
        raise ConflictError(
            f"Werkdag bestaat al op {datum_str} — verwijder de werkdag eerst."
        )
    # Insert (UNIQUE(datum) catches duplicate as IntegrityError)
    try:
        return await database.db_add_blocker(
            db_path, datum=datum_str, kind=kind, label=label,
        )
    except aiosqlite.IntegrityError as e:
        raise ConflictError(f"Datum {datum_str} heeft al een blocker") from e


async def delete_blocker(db_path, blocker_id: int) -> None:
    """Year-locked. Idempotent: silent no-op if blocker_id missing."""
    blocker = await database.db_get_blocker(db_path, blocker_id)
    if not blocker:
        return  # idempotent silent no-op
    await database.assert_year_writable(db_path, blocker.datum)
    await database.db_delete_blocker(db_path, blocker_id)


async def list_blockers(db_path, vanaf: _date, tot: _date) -> list[Blocker]:
    """User-blockers + computed Dutch holidays merged in one list.

    User-blockers and holidays may both be present on the same date —
    UI-laag decides display priority. Sorted by datum, then by kind
    (deterministic). Holidays have id=None.
    """
    user_rows = await database.db_list_blockers(
        db_path, vanaf.isoformat(), tot.isoformat(),
    )
    out: list[Blocker] = [
        Blocker(id=r.id, datum=_date.fromisoformat(r.datum),
                kind=r.kind, label=r.label)
        for r in user_rows
    ]
    # Compute holidays per year covered (1-2 years typical)
    for jaar in range(vanaf.year, tot.year + 1):
        for h in dutch_holidays(jaar):
            if vanaf <= h.datum <= tot:
                out.append(Blocker(id=None, datum=h.datum,
                                   kind='holiday', label=h.label))
    out.sort(key=lambda b: (b.datum, b.kind))
    return out


# ---------------------------------------------------------------------------
# View functions for /agenda
# ---------------------------------------------------------------------------

def _today() -> _date:
    """Indirection voor test-monkeypatch via monkeypatch.setattr(svc, '_today', ...)."""
    return _date.today()


def _iso_weekday(d: _date) -> int:
    """ISO weekday: Monday=1, Sunday=7."""
    return d.isoweekday()


@dataclass(frozen=True)
class WerkdagPill:
    """Bevestigde werkdag + factuur-status + categorie voor MonthGrid rendering."""
    id: int
    klant_id: int
    klant_naam: str
    code: str
    uren: float
    bedrag: float
    factuurnummer: str
    factuur_status: str
    factuur_vervaldatum: str
    status_label: WerkdagStatusLabel
    category: WerkdagCategory


@dataclass(frozen=True)
class ExpectedEntry:
    """Verwachte werkdag uit recurring pattern (NOT in DB; computed on read)."""
    pattern_id: int
    klant_id: int
    klant_naam: str
    start_minuten: int
    eind_minuten: int
    uren: float
    bedrag: float
    code: str
    activiteit: str
    category: WerkdagCategory


@dataclass(frozen=True)
class DagView:
    """Aggregaat voor één dag in /agenda."""
    datum: _date
    werkdagen: tuple[WerkdagPill, ...]
    expected: tuple[ExpectedEntry, ...]
    blocker: 'Blocker | None'


@dataclass(frozen=True)
class MaandView:
    """Aggregaat voor een hele maand."""
    jaar: int
    maand: int
    dagen: tuple[DagView, ...]


def _is_in_pattern_validity(pattern, datum: _date) -> bool:
    """Check pattern.valid_from / valid_until window. Empty string = no bound."""
    if pattern.valid_from:
        try:
            if datum < _date.fromisoformat(pattern.valid_from):
                return False
        except ValueError:
            pass  # invalid date, treat as no lower bound
    if pattern.valid_until:
        try:
            if datum > _date.fromisoformat(pattern.valid_until):
                return False
        except ValueError:
            pass  # invalid date, treat as no upper bound
    return True


def _expected_for_datum(datum: _date,
                         today: _date,
                         patterns_by_klant: dict,
                         klanten_by_id: dict) -> tuple:
    """Compute expected entries for a future date. Pure function — no DB.

    Returns tuple[ExpectedEntry, ...]. Empty tuple for past/today, blocked,
    or no matching pattern.
    """
    if datum <= today:
        return ()
    iso = _iso_weekday(datum)
    out: list[ExpectedEntry] = []
    for klant_id, plist in patterns_by_klant.items():
        klant = klanten_by_id.get(klant_id)
        if not klant:
            continue
        for p in plist:
            if not p.actief:
                continue
            if iso not in p.weekdays:
                continue
            if not _is_in_pattern_validity(p, datum):
                continue
            uren = (p.eind_minuten - p.start_minuten) / 60.0
            # Bedrag-formule moet matchen met confirm_expected → add_werkdag:
            # uren*tarief + retour_km*0.23. Anders onderschat de prognose
            # dagen met km-vergoeding (codex review B2).
            bedrag = uren * (klant.tarief_uur or 0) + (klant.retour_km or 0) * 0.23
            out.append(ExpectedEntry(
                pattern_id=p.id,
                klant_id=klant_id,
                klant_naam=klant.naam,
                start_minuten=p.start_minuten,
                eind_minuten=p.eind_minuten,
                uren=uren,
                bedrag=bedrag,
                code=p.code,
                activiteit=p.activiteit,
                category=categorize_werkdag(p.code),
            ))
    return tuple(out)


async def get_maand(db_path, jaar: int, maand: int,
                     include_expected: bool = True) -> MaandView:
    """Aggregate werkdagen + factuur-status + expected (van patterns) + blockers
    voor één maand.

    Expected entries verschijnen alleen voor toekomstige datums (datum > today),
    en alleen als er geen werkdag of blocker op die datum is.

    Returns MaandView met DagView per dag (1..lastDay).
    """
    today = _today()

    # 1. Werkdagen + factuur-status
    werkdagen_raw = await database.get_werkdagen_met_factuur_status(
        db_path, jaar, maand,
    )
    werkdagen_by_datum: dict[_date, list[WerkdagPill]] = {}
    for w in werkdagen_raw:
        d = _date.fromisoformat(w.datum)
        # km_tarief: ANW codes hebben legitiem km_tarief=0 (reiskosten zit
        # in ANW-tarief), DAGPRAKTIJK heeft default 0.23. WerkdagMetStatus
        # coerced NULL→0.0 al, dus we kunnen NULL niet meer detecteren —
        # gebruik de waarde as-is. (Codex review B3: weeg af, in praktijk
        # is NULL niet voorkomend door schema-default 0.23.)
        bedrag = (w.uren or 0) * (w.tarief or 0) + (w.km or 0) * (w.km_tarief or 0)
        pill = WerkdagPill(
            id=w.id, klant_id=w.klant_id, klant_naam=w.klant_naam,
            code=w.code, uren=w.uren, bedrag=bedrag,
            factuurnummer=w.factuurnummer,
            factuur_status=w.factuur_status,
            factuur_vervaldatum=w.factuur_vervaldatum,
            status_label=derive_werkdag_status_label(w, today),
            category=categorize_werkdag(w.code),
        )
        werkdagen_by_datum.setdefault(d, []).append(pill)

    # 2. Blockers (user + holidays) for full month
    last_day = monthrange(jaar, maand)[1]
    vanaf = _date(jaar, maand, 1)
    tot = _date(jaar, maand, last_day)
    blockers = await list_blockers(db_path, vanaf, tot)
    # Holiday wins over user-blocker for display (per spec)
    blockers_by_datum: dict[_date, 'Blocker'] = {}
    for b in blockers:
        if b.datum in blockers_by_datum:
            # Already have one — prefer 'holiday' if either is holiday
            existing = blockers_by_datum[b.datum]
            if existing.kind != 'holiday' and b.kind == 'holiday':
                blockers_by_datum[b.datum] = b
        else:
            blockers_by_datum[b.datum] = b

    # 3. Patterns + klanten for expected (only if needed)
    patterns_by_klant: dict[int, list] = {}
    klanten_by_id: dict[int, object] = {}
    if include_expected:
        # alleen_actief=True: gedeactiveerde klanten mogen geen expected
        # entries genereren (en daarna via confirm_expected echte werkdagen
        # worden). Codex review B1.
        klanten = await database.get_klanten(db_path, alleen_actief=True)
        for k in klanten:
            klanten_by_id[k.id] = k
            patterns_by_klant[k.id] = await list_patterns_for_klant(
                db_path, k.id, include_inactive=False,
            )

    # 4. Build DagView per day
    dagen: list[DagView] = []
    for day in range(1, last_day + 1):
        d = _date(jaar, maand, day)
        wd_list = tuple(werkdagen_by_datum.get(d, []))
        block = blockers_by_datum.get(d)
        # Expected only when no werkdag, no blocker, and include_expected
        if include_expected and not wd_list and block is None:
            expected = _expected_for_datum(d, today, patterns_by_klant, klanten_by_id)
        else:
            expected = ()
        dagen.append(DagView(
            datum=d, werkdagen=wd_list, expected=expected, blocker=block,
        ))

    return MaandView(jaar=jaar, maand=maand, dagen=tuple(dagen))


async def get_dag(db_path, datum: _date,
                   include_expected: bool = True) -> DagView:
    """Single-day view voor inspector-refresh. Wraps get_maand."""
    view = await get_maand(db_path, datum.year, datum.month, include_expected)
    for d in view.dagen:
        if d.datum == datum:
            return d
    return DagView(datum=datum, werkdagen=(), expected=(), blocker=None)


# ---------------------------------------------------------------------------
# confirm_expected — promote virtual rooster-entry → real werkdag
# ---------------------------------------------------------------------------

async def confirm_expected(
    db_path,
    pattern_id: int,
    datum: _date,
    start_minuten: int | None = None,
    eind_minuten: int | None = None,
    activiteit: str | None = None,
) -> int:
    """Promote virtual expected entry → real werkdag.

    Idempotent: als er al EEN willekeurige werkdag bestaat voor (klant_id, datum) —
    ongeacht of die door dit pattern of handmatig is aangemaakt — return existing.id
    zonder mutatie. Rationale: een echte werkdag op die datum voldoet al aan de
    "verwachte rooster"-constraint, dubbele creation zou semantisch fout zijn.

    Als de bestaande werkdag een andere code heeft dan dit pattern (bv. handmatig
    ANW_AVOND vs pattern WERKDAG), respecteert confirm_expected de bestaande rij —
    de gebruiker kan via /werkdagen handmatig wijzigen indien gewenst.

    Race-protected: pattern_id moet bestaan AND actief=1, anders ConflictError.

    Tijden: start/eind_minuten None = pattern-defaults. Beide moeten valid zijn
    (eind > start, in 0-1440 range) anders ValidationError.

    Klant-data (tarief, retour_km, adres) komt uit klanten-row op moment van
    bevestigen — NIET uit pattern (pattern is rooster-template).
    urennorm: 0 voor ACHTERWACHT/ZERO_UREN_CODES, 1 voor de rest.

    Raises:
        ConflictError: pattern niet bestaat / inactief, blocker bestaat al op datum,
                       of klant verwijderd
        YearLockedError: datum in afgesloten jaar (via add_werkdag delegate)
        ValidationError: invalid tijden
    """
    pattern = await database.db_get_pattern(db_path, pattern_id)
    if pattern is None or not pattern.actief:
        raise ConflictError(
            f"Patroon {pattern_id} is verwijderd of inactief — refresh agenda."
        )

    datum_str = datum.isoformat()

    # Defense-in-depth: weigeren als blocker op deze datum bestaat.
    # UI prevents this click-path but service-layer should be symmetric with add_blocker.
    existing_blocker = await database.db_list_blockers(
        db_path, datum_str, datum_str,
    )
    if existing_blocker:
        raise ConflictError(
            f"Blocker bestaat al op {datum_str} ({existing_blocker[0].kind}) — "
            f"verwijder de blocker eerst."
        )

    # Idempotency check: bestaande werkdag op (klant, datum)?
    async with database.get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT id FROM werkdagen WHERE datum = ? AND klant_id = ? "
            "ORDER BY id LIMIT 1",
            (datum_str, pattern.klant_id),
        )
        existing = await cur.fetchone()
    if existing:
        return existing[0]

    # Resolve fields with optional overrides
    start = start_minuten if start_minuten is not None else pattern.start_minuten
    eind = eind_minuten if eind_minuten is not None else pattern.eind_minuten
    _validate_pattern_minuten(start, eind)
    uren = (eind - start) / 60.0
    act = activiteit if activiteit is not None else pattern.activiteit

    klant = await database.get_klant_by_id(db_path, pattern.klant_id)
    if klant is None:
        raise ConflictError(f"Klant {pattern.klant_id} bestaat niet meer.")

    urennorm = 0 if pattern.code in _ZERO_UREN_CODES or pattern.code == 'ACHTERWACHT' else 1

    # add_werkdag does year-lock validation + INSERT
    return await database.add_werkdag(
        db_path,
        datum=datum_str,
        klant_id=pattern.klant_id,
        code=pattern.code,
        activiteit=act,
        locatie=klant.adres or '',
        locatie_id=None,
        uren=uren,
        km=klant.retour_km or 0,
        tarief=klant.tarief_uur,
        km_tarief=0.23,
        urennorm=urennorm,
        opmerking='',
    )
