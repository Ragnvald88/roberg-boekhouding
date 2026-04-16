"""Mail.app integration via AppleScript.

IMPORTANT: Mail.app silently breaks HTML content + attachments. Body must be
plain text. Betaallinks must be inline URLs (Mail.app auto-links them).
"""

import subprocess


def _escape_applescript(s: str) -> str:
    """Escape backslashes, quotes, and newlines for AppleScript string literals."""
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def open_mail_with_attachment(
    *,
    to: str,
    subject: str,
    body: str,
    attachment_path: str,
    timeout: int = 15,
) -> subprocess.CompletedProcess:
    """Open Mail.app with a pre-filled message containing a single PDF attachment.

    All arguments are keyword-only to prevent positional confusion.
    Body must be plain text — HTML content + attachments is broken in Mail.app.
    Returns the completed subprocess so callers can inspect returncode/stderr.
    """
    s_subject = _escape_applescript(subject)
    s_body = _escape_applescript(body)
    s_to = _escape_applescript(to)
    to_line = (
        f'make new to recipient with properties {{address:"{s_to}"}}'
        if to else ''
    )
    script = (
        'tell application "Mail"\n'
        f'  set newMsg to make new outgoing message with properties '
        f'{{subject:"{s_subject}", content:"{s_body}", visible:true}}\n'
        f'  tell newMsg\n'
        f'    {to_line}\n'
        f'    make new attachment with properties '
        f'{{file name:POSIX file "{attachment_path}"}} '
        f'at after last paragraph of content\n'
        f'  end tell\n'
        f'  activate\n'
        f'end tell'
    )
    return subprocess.run(
        ['osascript', '-e', script],
        capture_output=True,
        timeout=timeout,
    )
