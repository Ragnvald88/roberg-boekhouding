# Documenten Page Redesign — Design Spec

**Goal:** Replace the flat checklist with a document-centric page inspired by Yuki/Moneybird — documents are primary objects with visual presence, not checkmarks.

**Key paradigm shift:** Current page = "here are 13 slots to fill." New page = "here are your documents, organized by category, and here's what's still missing."

## Design

### Layout (top to bottom)

1. **Header**: Title + year selector + compact progress badge ("7/13")
2. **Upload zone**: Prominent drag-and-drop area. Drop a file → categorization dialog opens.
3. **Category cards**: One card per category (6 cards). Each shows:
   - Category name + completion count (e.g., "Eigen woning — 1/2")
   - Uploaded documents as file rows (PDF icon, filename, upload date, download/preview/delete)
   - Missing types as subtle dashed rows with upload button
   - Auto-generated types link to Jaarafsluiting

### Upload-first flow

When user drops/uploads a file via the top zone:
1. Dialog opens with filename displayed
2. User picks category (dropdown) → document type (filtered dropdown)
3. Click save → file stored, page refreshes

### Document preview

Serve `data/aangifte/` as static files via `app.add_static_files`.
- PDFs: iframe in a dialog
- Images: `ui.image` in a dialog

### Per-type inline upload

Each missing document type row also has its own upload button (existing behavior, improved styling).

## Out of scope
- Notes field (exists in DB, defer to future)
- Multi-year overview grid
- OCR/scan recognition
- Document-to-entity linking
