"""Byte-level PII scanner for test fixtures.

The fix only touches MessagingInfraDatabase.sqlite, whose `receipt_device` table
carries `chat_jid`/`user_jid` — WhatsApp JIDs derived from phone numbers, i.e. a
user's contact graph. Fixtures must never carry that. This scanner reads a
file's RAW bytes (so it catches data hiding in freed pages / slack too) and
fails loudly on anything that looks like a JID or a phone number.

It is the enforcement mechanism behind "how do I know the PII is gone?": the
regression test runs it on every fixture (and its .recover output) on every run.
"""
import re

# WhatsApp JID suffixes (substring match on raw bytes).
_JID_MARKERS = [
    b"@s.whatsapp.net",
    b"@c.us",
    b"@g.us",
    b"@lid",
    b"@broadcast",
]
# A run of 7+ ASCII digits — long enough to be a phone number, not a timestamp
# field name or small integer. Synthetic fixture rows must avoid this.
_DIGIT_RUN = re.compile(rb"\d{7,}")

_MAX_HITS = 20


def scan(path):
    """Return a list of human-readable PII hits found in `path`. Empty == clean."""
    with open(path, "rb") as f:
        data = f.read()
    hits = []
    for marker in _JID_MARKERS:
        start = data.find(marker)
        if start != -1:
            hits.append(f"JID marker {marker!r} at byte {start}")
    for m in _DIGIT_RUN.finditer(data):
        hits.append(f"digit run {m.group()!r} at byte {m.start()}")
        if len(hits) >= _MAX_HITS:
            break
    return hits[:_MAX_HITS]
