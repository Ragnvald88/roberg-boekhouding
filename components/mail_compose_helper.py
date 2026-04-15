"""Standalone helper: open Mail.app compose-window via NSSharingService.

Invoked as a subprocess by `components.mail_helper.open_mail_with_attachment`.
Reads a JSON payload from stdin with keys:

    {"to": "...", "subject": "...", "body_html": "<p>…</p>",
     "attachment_path": "/abs/path/to.pdf"}

Writes status to stderr and exits 0 on success, non-zero on failure.

Why this lives in a subprocess: the NiceGUI server process is uvicorn
on asyncio with worker threads. NSSharingService requires Cocoa main-
thread affordances (an NSApplication singleton + a main run-loop) that
are inconvenient to arrange mid-server. A 10-line subprocess that spins
its own NSApplication is deterministic, isolated, and fails loudly when
it fails.

Why NSSharingService and not AppleScript: Mail.app's AppleScript
`html content` property is officially deprecated with description
"Does nothing at all" — see `sdef /System/Applications/Mail.app` on
macOS 14+. Any recipe that tries to combine AppleScript HTML-body with
an attachment is fighting a property Apple has disabled at the
framework level.
"""
import json
import sys

from AppKit import NSApplication, NSSharingService
from Foundation import NSURL, NSData, NSRunLoop, NSDate

try:
    from AppKit import NSAttributedString
except ImportError:  # pragma: no cover — macOS SDK layout variations
    from Foundation import NSAttributedString


def _eprint(*args):
    print(*args, file=sys.stderr, flush=True)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception as ex:
        _eprint(f'mail_compose_helper: invalid JSON stdin: {ex}')
        return 2

    to = payload.get('to') or ''
    subject = payload.get('subject') or ''
    body_html = payload.get('body_html') or ''
    attachment_path = payload.get('attachment_path') or ''

    if not body_html:
        _eprint('mail_compose_helper: body_html is required')
        return 2
    if not attachment_path:
        _eprint('mail_compose_helper: attachment_path is required')
        return 2

    NSApplication.sharedApplication()

    html_bytes = body_html.encode('utf-8')
    html_data = NSData.dataWithBytes_length_(html_bytes, len(html_bytes))
    attr_body, _ = NSAttributedString.alloc() \
        .initWithHTML_documentAttributes_(html_data, None)
    if attr_body is None:
        _eprint('mail_compose_helper: failed to parse HTML body')
        return 3

    pdf_url = NSURL.fileURLWithPath_(attachment_path)

    svc = NSSharingService.sharingServiceNamed_(
        'com.apple.share.Mail.compose')
    if svc is None:
        _eprint('mail_compose_helper: Mail compose sharing service '
                'is not available')
        return 4

    if to:
        svc.setRecipients_([to])
    svc.setSubject_(subject)

    items = [attr_body, pdf_url]
    if not svc.canPerformWithItems_(items):
        _eprint('mail_compose_helper: share service rejects items '
                '(Mail.app may not be configured)')
        return 5

    svc.performWithItems_(items)

    # Spin the Cocoa run-loop briefly so Mail.app can dispatch the
    # compose-window. 3 seconds is empirically enough on macOS 26.2;
    # any longer only delays this helper's exit with no user benefit.
    NSRunLoop.currentRunLoop().runUntilDate_(
        NSDate.dateWithTimeIntervalSinceNow_(3.0))

    _eprint('mail_compose_helper: compose window opened')
    return 0


if __name__ == '__main__':
    sys.exit(main())
