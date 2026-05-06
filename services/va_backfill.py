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
    get_unprocessed_voorlopige_aanslag_documents,
    process_voorlopige_aanslag_upload,
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
        pdf_path = Path(doc['bestandspad']) if doc.get('bestandspad') else None
        if pdf_path is None or not pdf_path.exists():
            failed.append(BackfillResult(
                document_id=doc_id, bestandsnaam=fname,
                status='parse_failed',
                message=f'PDF-bestand niet gevonden op disk: {pdf_path}',
            ))
            continue

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

        action = result.get('action', 'inserted')
        if action == 'skip':
            skipped.append(BackfillResult(
                document_id=doc_id, bestandsnaam=fname,
                status='skipped',
                soort=parsed.soort, bedrag=parsed.bedrag,
                message='Beschikking al verwerkt (duplicate aanslagnummer)',
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
