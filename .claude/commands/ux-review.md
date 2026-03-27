Doe een UX/product-level review van deze codebase. Dit is GEEN code-correctheid review — het gaat over of de app zich gedraagt zoals de gebruiker verwacht.

## Context
- Lees `PRODUCT_FLOWS.md` voor de verwachte gebruikersinteracties
- De gebruiker is een huisartswaarnemer die maandelijks boekhoudt
- Minimale klikken, consistente patronen, geen verrassingen

## Wat te doen

### 1. Flow-verificatie
Lees `PRODUCT_FLOWS.md` en traceer elke beschreven flow door de code:
- Klopt de trigger (welke button/event start de flow)?
- Opent het juiste component (builder vs dialog vs navigatie)?
- Worden de juiste parameters doorgegeven?
- Is de data correct pre-filled?

### 2. Consistentie-check
Vergelijk patronen tussen pagina's:
- Gebruiken alle pagina's dezelfde edit-aanpak voor vergelijkbare acties?
- Zijn bulk-acties consistent (selectie → bevestiging → actie)?
- Zijn alle destructieve acties achter een bevestigingsdialog?
- Zijn alle datumvelden consistent (DD-MM-YYYY display)?

### 3. Ontbrekende flows
Zoek naar:
- Buttons/events in de code die NIET in `PRODUCT_FLOWS.md` staan
- Flows in `PRODUCT_FLOWS.md` die NIET in de code bestaan
- Dode code: functies die nergens worden aangeroepen

### 4. Gebruikersperspectief
Denk als de eindgebruiker:
- Zijn er acties die te veel klikken vereisen?
- Zijn er verwarrende keuzes (twee manieren om hetzelfde te doen)?
- Mist er feedback (notificaties, loading states)?
- Kan de gebruiker per ongeluk data verliezen?

## Output formaat

### MISMATCH (Flow wijkt af van spec)
Per item: welke flow, wat de spec zegt, wat de code doet

### ONTBREKEND (Flow niet geïmplementeerd)
Per item: welke flow ontbreekt en waarom dat ertoe doet

### INCONSISTENTIE (Patronen verschillen tussen pagina's)
Per item: welke pagina's, wat verschilt

### RISICO (Gebruiker kan data verliezen of verward raken)
Per item: scenario, impact

### OK (Flows die correct matchen)
Korte lijst ter bevestiging

Gebruik subagents (opus model) om bestanden parallel te lezen waar nodig.
