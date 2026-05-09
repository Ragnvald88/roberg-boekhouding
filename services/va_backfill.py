"""VA-document backfill — Sprint J post-redesign.

Voor PDFs die geüpload zijn vóór Sprint J T1.3 (parse-on-upload), of
waar de parse-flow is gefaald: detect ongekoppelde aangifte_documenten
en parse + insert ze retro-actief naar voorlopige_aanslagen.

Aangeroepen vanuit /va-tracker via expliciete user-CTA "PDFs verwerken"
(Codex-design-keuze: read-page mag niet stilletjes muteren bij render).

Auto-overwrite policy bij mismatch met handmatige fp: PDF wint en notify
toont oude vs nieuwe waarde. Reden: user uploadde de PDF zelf — implicit
intent dat PDF de canonical bron is. Per-doc confirm-dialog zou voor
fix-up flow extra wrijving zijn (kan Sprint K toegevoegd indien nodig).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from database import (
    DB_PATH,
    YearLockedError,
    delete_aangifte_document_with_va_cleanup,
    get_unprocessed_voorlopige_aanslag_documents,
    process_voorlopige_aanslag_upload,
    resolve_aangifte_document_path,
    update_aangifte_document_pad,
)
from services.va_parser import VAParseError, parse_va_beschikking

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillResult:
    """Per-doc resultaat van backfill — zichtbaar in /va-tracker UI."""
    document_id: int
    bestandsnaam: str
    status: str              # 'inserted'|'replaced'|'skipped'|'parse_failed'|'locked'
    soort: str | None = None # 'ib'/'zvw' (na parse) of None (parse_failed)
    bedrag: float | None = None
    message: str = ''        # human-readable status (Dutch)


@dataclass(frozen=True)
class BackfillSummary:
    """Aggregaat-resultaat van een backfill-call."""
    processed: list[BackfillResult]   # action='inserted'|'replaced'
    skipped: list[BackfillResult]     # duplicate aanslagnummer
    failed: list[BackfillResult]      # parse_failed
    locked: list[BackfillResult]      # YearLockedError

    @property
    def total(self) -> int:
        return (len(self.processed) + len(self.skipped)
                + len(self.failed) + len(self.locked))


async def ensure_va_backfill(
    db_path: Path = DB_PATH, jaar: int = 0,
) -> BackfillSummary:
    """Public alias voor backfill_voorlopige_aanslag_documents.

    Bedoeld als de single entry-point voor pages die page-load auto-process
    willen triggeren. /documenten en /va-tracker roepen beide deze helper —
    één functie, één naam, één gedrag.

    Idempotent: bij geen ongekoppelde docs is dit een goedkope LEFT-JOIN
    + early return.
    """
    return await backfill_voorlopige_aanslag_documents(db_path, jaar)


async def backfill_voorlopige_aanslag_documents(
    db_path: Path = DB_PATH, jaar: int = 0,
) -> BackfillSummary:
    """Detect + parse + insert ongekoppelde VA-documenten voor één jaar.

    Per document:
      1. parse_va_beschikking via asyncio.to_thread (blocking pdftotext)
      2. process_voorlopige_aanslag_upload (atomic insert + fp-sync)
      3. Capture per-doc resultaat in BackfillResult

    Faal-soft per doc — één corrupte PDF blokkeert niet de andere.
    Year-locked: process_*_upload weigert; result.status='locked'.
    Idempotent: 2× draaien geeft 2e-call result.status='skipped' voor
    al-verwerkte docs (UNIQUE(aanslagnummer) check).

    Returns BackfillSummary met 4 lijsten voor UI-rendering.
    """
    docs = await get_unprocessed_voorlopige_aanslag_documents(db_path, jaar)
    processed: list[BackfillResult] = []
    skipped: list[BackfillResult] = []
    failed: list[BackfillResult] = []
    locked: list[BackfillResult] = []

    for doc in docs:
        doc_id = int(doc['id'])
        fname = doc.get('bestandsnaam', '?')
        stored_pad = doc.get('bestandspad') or ''
        doc_jaar = doc.get('jaar')
        # Path-resolver: stored absolute pad eerst, dan basename-fallback in
        # canonical AANGIFTE_DIR. Lost legacy-bug op (DB-pad heeft non-existing
        # prefix terwijl het bestand wel onder ~/Library/Application Support
        # /Boekhouding/data/aangifte staat).
        resolved = resolve_aangifte_document_path(
            stored_pad, jaar=doc_jaar)
        if resolved is None:
            failed.append(BackfillResult(
                document_id=doc_id, bestandsnaam=fname,
                status='parse_failed',
                message=(
                    f'PDF-bestand niet gevonden op disk (gezocht onder '
                    f'AANGIFTE_DIR), of meerdere basename-matches '
                    f'(ambiguous). Stored pad: {stored_pad}'
                ),
            ))
            continue
        pdf_path = resolved

        # Parse PDF (blocking subprocess → to_thread)
        try:
            parsed = await asyncio.to_thread(parse_va_beschikking, pdf_path)
        except VAParseError as err:
            failed.append(BackfillResult(
                document_id=doc_id, bestandsnaam=fname,
                status='parse_failed',
                message=f'PDF kon niet gelezen worden: {err}',
            ))
            continue
        except Exception as err:  # pragma: no cover — defense
            log.exception('Onverwachte parse-error voor doc %s', doc_id)
            failed.append(BackfillResult(
                document_id=doc_id, bestandsnaam=fname,
                status='parse_failed',
                message=f'Onverwachte fout: {err}',
            ))
            continue

        # Insert + sync fp via atomic helper
        try:
            result = await process_voorlopige_aanslag_upload(
                db_path=db_path, document_id=doc_id, parsed=parsed,
            )
        except YearLockedError as err:
            locked.append(BackfillResult(
                document_id=doc_id, bestandsnaam=fname,
                status='locked',
                soort=parsed.soort, bedrag=parsed.bedrag,
                message=str(err),
            ))
            continue
        except ValueError as err:
            # process_*_upload's interne validatie (jaar/categorie mismatch
            # — zou niet moeten gebeuren in backfill maar defensive)
            failed.append(BackfillResult(
                document_id=doc_id, bestandsnaam=fname,
                status='parse_failed',
                soort=parsed.soort, bedrag=parsed.bedrag,
                message=f'DB-validatie afgewezen: {err}',
            ))
            continue

        # Self-heal stored pad NA succesvolle process_*_upload — anders
        # zouden we DB-pad herschrijven op basis van een toevallige
        # basename-match waar parse vervolgens kon falen op inhoud.
        if str(pdf_path) != stored_pad:
            try:
                await update_aangifte_document_pad(
                    db_path=db_path, document_id=doc_id,
                    new_bestandspad=str(pdf_path),
                )
            except Exception:  # pragma: no cover — defense
                log.exception(
                    'Pad self-heal faalde voor doc %s', doc_id)

        action = result.get('action', 'inserted')
        if action == 'skip':
            # Codex round-1 fix: na skip ruim de duplicate aangifte_doc op
            # zodat de doc niet eeuwig in get_unprocessed_* blijft staan.
            # Codex audit fix #2 (race): parallel backfills van zelfde
            # doc kunnen call B het door call A net-gemaakte doc opruimen
            # (CASCADE op aangifte_documenten zou dan ook A's net-gemaakte
            # VA-row mee-deleten). Skip cleanup als existing_document_id ==
            # current doc_id — dat is een "self-skip", VA-row hoort bij ons.
            existing_doc_id = result.get('existing_document_id')
            cleanup_msg = ''
            if existing_doc_id == doc_id:
                # Self-skip: A heeft net onze VA-row gemaakt, B detecteert
                # via aanslagnummer-UNIQUE. Onze doc is correct gekoppeld —
                # niet verwijderen. Volgende get_unprocessed-query ziet de
                # doc niet meer (LEFT JOIN matched), dus geen herhaalde skip.
                cleanup_msg = ' (al gekoppeld aan deze upload)'
            else:
                cleanup_msg = ' (duplicate document opgeruimd)'
                try:
                    await delete_aangifte_document_with_va_cleanup(
                        db_path=db_path, doc_id=doc_id)
                except YearLockedError:
                    cleanup_msg = (' (duplicate doc kon niet worden opgeruimd: '
                                   'jaar afgesloten)')
                except Exception:  # pragma: no cover — defense
                    log.exception(
                        'Skip-cleanup faalde voor doc %s', doc_id)
                    cleanup_msg = ' (duplicate-cleanup faalde — zie logs)'
            skipped.append(BackfillResult(
                document_id=doc_id, bestandsnaam=fname,
                status='skipped',
                soort=parsed.soort, bedrag=parsed.bedrag,
                message=(f'Beschikking al verwerkt (duplicate aanslagnummer)'
                         f'{cleanup_msg}'),
            ))
        else:
            soort_upper = parsed.soort.upper()
            processed.append(BackfillResult(
                document_id=doc_id, bestandsnaam=fname,
                status=action,  # 'inserted'|'replaced'
                soort=parsed.soort, bedrag=parsed.bedrag,
                message=(f'VA {soort_upper} verwerkt: '
                         f'€{parsed.bedrag:.0f}, '
                         f'{parsed.termijnen} termijnen'),
            ))

    return BackfillSummary(
        processed=processed, skipped=skipped,
        failed=failed, locked=locked,
    )
