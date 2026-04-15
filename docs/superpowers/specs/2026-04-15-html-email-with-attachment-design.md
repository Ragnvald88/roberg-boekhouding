# HTML e-mail met PDF-attachment — ontwerp

**Datum**: 2026-04-15
**Status**: brainstorm — wacht op user-keuze tussen opties
**Context**: factuur-verzendflow vanuit Boekhouding-app naar Mail.app

## Probleem

Bij factuur-verzending wordt nu een plain-text e-mail gegenereerd met de
betaallink letterlijk uitgeschreven op een eigen regel:

```
U kunt ook eenvoudig betalen via deze link:
https://betaalverzoek.rabobank.nl/betaalverzoek/?id=Un_PIQcFTW-XCqS0oadocA
```

Wens: `deze link` als clickable hyperlink, geen URL-blok. Dat vereist
een HTML- of rich-text-body samen met de PDF-bijlage.

## Historisch

Vijf commits bloed uit Apr 2026 (`f6def43` → `f44e3cf`) probeerden HTML-body
+ PDF-attachment werkend te krijgen via AppleScript `html content` property
en uiteindelijk ging de rul terug naar plain text. Sinds die tijd staat in
CLAUDE.md dat HTML+attachment "broken" is.

## Smoking gun — empirisch bewijs

Op deze machine (macOS 26.2 Tahoe, build 25C56, Mail.app 16.0) rapporteert
Mail.app's scripting dictionary over `html content`:

```xml
<property name="html content" code="htda" type="text" access="w" hidden="yes"
          description="Does nothing at all (deprecated)"/>
```

Apple heeft de property officieel als **`hidden="yes"`, deprecated, "Does
nothing at all"** gemarkeerd. De `html content`-route is geen
"soms-werkt-het" meer — hij is framework-niveau uitgeschakeld. Geen
volgorde-trucje, geen escape-fix, geen timing-delay brengt 'm terug.

Gevolg: élke route die leunt op AppleScript `html content` (ook via
ScriptingBridge, ook via template-draft met `duplicate`+`set content`) is
**fundamenteel dood** op macOS 14+ en zeker op 26.

## Scope

- Factuur-verzending met clickable "deze link"-hyperlink naar betaallink.
- User moet nog steeds reviewen vóór verzenden (trust-principe blijft).
- PDF-bijlage verplicht (factuur).
- Herinnering-e-mail (`_build_herinnering_body`) valt binnen dezelfde oplossing.

Niet in scope:
- Silent send zonder user-review.
- Outlook / Spark / third-party multi-client support.
- Server-side mail queue.

## Opties

### Optie A — NSSharingService via pyobjc

**Hoe**: Apple's Share-Sheet compose-API aanroepen. Deze API zit NIET op de
Apple Events bus die AppleScript gebruikt; het is de moderne Cocoa-route
die Finder's "Share → Mail", Safari's "Share", en elke andere macOS-app
gebruikt om Mail.app compose-windows te openen.

```python
from AppKit import NSSharingService, NSAttributedString
from Foundation import NSURL, NSData

svc = NSSharingService.sharingServiceNamed_('com.apple.share.Mail.compose')
svc.setRecipients_([to])
svc.setSubject_(subject)

html_bytes = body_html.encode('utf-8')
data = NSData.dataWithBytes_length_(html_bytes, len(html_bytes))
attr_body, _ = NSAttributedString.alloc() \
    .initWithHTML_documentAttributes_(data, None)

pdf_url = NSURL.fileURLWithPath_(str(pdf_path))
svc.performWithItems_([attr_body, pdf_url])
```

pywebview heeft pyobjc al als transitive dependency dus **geen extra deps**.

**Werkt het?** Agent-research (zonder live web-toegang, maar op basis van
stabiele Apple conventies sinds macOS 10.8): ja voor attachments, onzeker
voor HTML-body + attachment gecombineerd op huidige macOS. **Must-test
empirisch** vóór commit.

**Voor**:
- Geen AppleScript, geen dode properties — moderne API.
- Zelfde UX als nu: user ziet Mail compose, reviewt, verstuurt.
- Minder code dan huidige AppleScript-helper.
- Geen credentials, geen config.

**Tegen**:
- Geen harde bewijzen voor HTML+attachment samen op macOS 26.2 in de docs
  die ik kon raadplegen. Vereist lokale test.
- Als Mail.app hier ook iets stilletjes dropt, zitten we weer vast.
- `performWithItems_` is synchroon (blocking) — moet in `asyncio.to_thread`.

**Kans op werkend resultaat**: ~75% (op basis van third-party meldingen +
het feit dat Finder "Share → Mail" deze codepath gebruikt en dat
empirisch werkt met HTML-tekst + file-attachment).

### Optie B — Clipboard rich-text paste via UI-scripting

**Hoe**: bestaande AppleScript-flow ongewijzigd (opent compose-window met
plain body + PDF-attachment — dat werkt vandaag al). Directe toevoeging:

1. Python zet RTF-bytes op `NSPasteboard.generalPasteboard()` via pyobjc
   (type `public.rtf`). RTF bevat de hyperlink.
2. AppleScript: `delay 0.4`, dan `tell application "System Events"` →
   `keystroke "a" using command down` (selecteert body) →
   `keystroke "v" using command down` (plakt RTF).

Mail.app's compose-window is een `NSTextView` in rich-text mode → RTF
wordt native gerendered, inclusief clickable `NSLinkAttributeName`.

**Voor**:
- Kleinste diff (~40 regels Python + 5 regels extra AppleScript).
- Geen architecturale wijziging — user-flow blijft identiek.
- Geen nieuwe API-afhankelijkheid die stuk kan gaan.

**Tegen**:
- **Vereist Accessibility-permissie** in System Settings → Privacy &
  Security → Accessibility voor Boekhouding (of Python/Terminal). Eerste
  run: TCC-dialog. Zonder grant: silent no-op — dit is een duidelijke
  failure-mode die we moeten detecteren en melden.
- Race-condities: paste kan naar verkeerd venster gaan als Mail niet op
  tijd frontmost is. Mitigatie: explicit `activate` + `frontmost`-check +
  `delay`.
- User ziet de paste gebeuren (korte flits). Niet elegant.
- `Cmd-A` selecteert in sommige Mail.app-versies ook de attachment-icon
  in de body-view. Workaround: attachment toevoegen NA paste, niet vóór.

**Kans op werkend resultaat**: ~90% (pasteboard RTF + System Events is
een al-meer-dan-10-jaar-stabiele techniek; de risico's zijn ergonomisch,
niet technisch).

### Optie C — SMTP direct vanuit Python, in-app compose-review

**Hoe**: Mail.app volledig verlaten. Python's `smtplib` + `EmailMessage`
met `multipart/alternative` (plain + HTML) + PDF-attachment. Python pakt
de gebruikers-SMTP-credentials uit macOS Keychain (eenmalig via
Instellingen-pagina ingegeven). In-app toont een NiceGUI-dialog met
HTML-preview vóór send; gebruiker klikt "Verstuur". IMAP APPEND op Sent-
folder zodat verzonden bericht ook in Mail.app's Sent-mailbox verschijnt.

**Voor**:
- Geen afhankelijkheid van Mail.app-bugs, AppleScript, pasteboard,
  Accessibility, of pyobjc-glue.
- HTML rendering gegarandeerd (standaard RFC 5322 multipart).
- Unittestbaar met `aiosmtpd`.
- Werkt identiek op elke macOS-versie (en Linux, als dat ooit relevant
  wordt).
- Clickable links werken bij ontvanger ongeacht client.

**Tegen**:
- **Eenmalige setup**: user moet SMTP-host/port/user/app-password invoeren
  in Instellingen. Voor KPN/Ziggo/iCloud/Gmail-basic is dat één keer
  inloggen + app-password genereren. Voor Microsoft 365 is Basic SMTP AUTH
  sinds sept 2022 uitgeschakeld — OAuth2-flow nodig (complex).
- User-review-flow verandert: niet meer de Mail.app compose-window,
  maar een NiceGUI-dialog met preview. Minder "Mac-native" gevoel.
- IMAP APPEND voor "Sent"-folder: werkt, maar folder-naam-detectie is
  per-provider anders (`Sent`, `[Gmail]/Sent Mail`, `Sent Items`, `Sent Messages`).
- Meer code (~150 regels) + Keychain-integratie.

**Kans op werkend resultaat**: ~99% (stdlib smtplib + IMAP, bekende
technologie). Feature-complete-kans afhankelijk van hoe moeilijk
user-onboarding voor SMTP setup wordt.

### Optie D — Swift CLI-helper rond NSSharingService

**Hoe**: als A maar dan in Swift gecompileerd als kleine binary die met
de app meegeshipt wordt. Python shellt uit naar `./bin/mailcompose`.

**Voor**:
- Zelfde API-codepath als A (NSSharingService).
- Beter debugbaar dan pyobjc (native types, geen runtime-glue).
- `Console.app` logging werkt direct.

**Tegen**:
- Build-step: `swiftc mailcompose.swift -o mailcompose` bij setup. Vereist
  Xcode command-line tools op de dev-machine (niet op eindgebruiker
  want de binary wordt meegeshipt).
- Extra bestandstype in het project dat onderhouden moet worden.
- Meer overhead dan A voor dezelfde functionaliteit.

**Kans op werkend resultaat**: gelijk aan A (zelfde onderliggende API)
maar met betere diagnostic-affordances.

## Opties die afvallen

- **AppleScript `html content`-retry**: `Does nothing at all (deprecated)`
  — Apple heeft het uitgeschakeld. Dead end.
- **ScriptingBridge / appscript**: zelfde Apple Events bus → zelfde dode
  property. 0% kans.
- **URL-schemes (`mailto:`, `message:`)**: geen attachment support, by
  RFC 6068 design. Dead end.
- **`MFMailComposeViewController`**: iOS-only, bestaat niet op macOS.
- **.eml/.emlx drop in Drafts-folder**: `~/Library/Mail/` is sinds macOS
  10.14 TCC-protected. Python krijgt daar GEEN write-access zonder Full
  Disk Access grant. Bovendien: Envelope Index (SQLite) moet ook worden
  gemuteerd, breekt elke macOS-update. Dead end.
- **`open -a Mail foo.eml`**: opent als read-only view, geen compose. Dead
  end.
- **Automator / Shortcuts "New Mail"**: gebruiken dezelfde AppleScript-
  brug eronder → zelfde bug. Dead end.
- **Template draft + `duplicate` + `set content`**: `set content` triggert
  dezelfde code-path die de HTML naar plain degradeert. Dead end.

## Aanbeveling

**Optie A (NSSharingService via pyobjc) met B als fallback** en C als
strategische reserve.

Rationale:
- A is de meest Apple-native oplossing. Geen AppleScript-brug, geen
  deprecated properties, geen UI-scripting, geen TCC-Accessibility-prompt.
  Code is compact en geen extra dependencies.
- **Kritische voorwaarde**: A moet empirisch worden getest — Apple's
  Share-Sheet compose zou HTML+attachment moeten kunnen, maar in het
  research-rapport is er geen harde 2024-2026 bron dat bevestigt op
  macOS 26. Vóór commit dus: 30 minuten exploratie-sessie waarin we een
  minimale pyobjc test-script schrijven, Mail.app compose-window
  openen, en visueel verifiëren dat hyperlink + bijlage beide
  overblijven.
- Als A in de test faalt (HTML body wordt dropped zoals bij AppleScript):
  fallback naar B. De bestaande AppleScript-flow blijft intact, we voegen
  alleen een RTF-paste-step toe. Technisch solide (10+ jaar stabiele
  pasteboard-API), TCC-Accessibility is de enige hobbel.
- C (SMTP direct) is engineering-superieur maar vereist een user-facing
  setup-stap die we in een single-user eenmanszaak-app willen vermijden
  tenzij A én B allebei stuk gaan. Bewaar als noodplan.

## Beslispunten voor user

Voordat een plan geschreven wordt, kiezen:

1. **Primair pad**: A (NSSharingService), B (clipboard-paste), of C (SMTP)?
2. **Fallback**: wel/niet meerdere paden met automatische degradatie, of
   kies één en rol die uit?
3. **Scope van eerste iteratie**: alleen factuur-mail, of ook
   herinnering-mail in dezelfde release?
4. **Test-budget**: 30 minuten empirische exploratie van A toestaan vóór
   commit tot implementatie-plan?

## Implementatie-plan volgt na keuze

Zodra user bovenstaande keuzes heeft gemaakt, schrijf ik via
`superpowers:writing-plans` een concreet implementatie-plan met
bestands-niveau taken, test-strategie, rollback-pad en commit-structuur.
