from components.mail_helper import _escape_applescript


def test_escape_quotes():
    assert _escape_applescript('Say "hi"') == 'Say \\"hi\\"'


def test_escape_backslash():
    assert _escape_applescript('a\\b') == 'a\\\\b'


def test_escape_newlines():
    assert _escape_applescript('line1\nline2') == 'line1\\nline2'


def test_escape_combined():
    s = 'He said "hi"\nLine2\\Tab'
    assert _escape_applescript(s) == 'He said \\"hi\\"\\nLine2\\\\Tab'
