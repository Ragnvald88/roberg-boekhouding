"""Mail.app integration via NSSharingService (Cocoa Share-Sheet compose API).

Replaces the earlier AppleScript-based helper. Apple has officially
deprecated Mail.app's AppleScript `html content` property in the current
scripting dictionary:

    <property name="html content" code="htda" type="text" access="w"
              hidden="yes" description="Does nothing at all (deprecated)"/>

So no AppleScript recipe — regardless of attachment-vs-html ordering,
escaping or delays — can produce a clickable hyperlink in the body of a
message that also carries an attachment. NSSharingService uses a
different code-path (same one Finder's "Share → Mail" uses) and does
accept an HTML body + file URL together.

The actual NSSharingService call lives in `mail_compose_helper.py` and
is invoked as a subprocess so the NiceGUI/asyncio server process never
has to touch Cocoa main-thread state itself.
"""

import json
import subprocess
import sys
from pathlib import Path

_HELPER = str(Path(__file__).resolve().parent / 'mail_compose_helper.py')


def open_mail_with_attachment(
    *,
    to: str,
    subject: str,
    body_html: str,
    attachment_path: str,
    timeout: int = 15,
) -> subprocess.CompletedProcess:
    """Open Mail.app with a pre-filled compose window containing the given
    HTML body and a single PDF attachment. User reviews and clicks Send.

    All arguments are keyword-only to prevent positional confusion.
    `body_html` must be valid HTML (parsed by NSAttributedString's
    initWithHTML_documentAttributes_). Plain text works too — it just
    won't have any formatting.

    Returns the completed subprocess so callers can inspect
    `returncode` and `stderr`.
    """
    payload = json.dumps({
        'to': to,
        'subject': subject,
        'body_html': body_html,
        'attachment_path': attachment_path,
    })
    return subprocess.run(
        [sys.executable, _HELPER],
        input=payload.encode('utf-8'),
        capture_output=True,
        timeout=timeout,
    )
