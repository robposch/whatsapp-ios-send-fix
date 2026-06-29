"""Build synthetic MessagingInfraDatabase fixtures for the regression tests.

Fixtures are generated from `INFRA_SCHEMA_DDL` (names only) plus a handful of
obviously-fake rows. They never contain real JIDs, phone numbers, or message
content — `tests/pii_scan.py` enforces this on every test run.

`build_malformed` reproduces the real bug's condition (SQLite raising "database
disk image is malformed" rather than returning rows) and is *self-verifying*: it
only emits a fixture that both raises a "malformed" error AND is salvageable by
`sqlite3 .recover`, matching what the repair tool relies on.
"""
import os
import sqlite3
import subprocess
import tempfile

from infra_schema import INFRA_SCHEMA_DDL

# Synthetic rows: no '@...' JID suffixes, no 7+ digit runs (see pii_scan).
_SYNTHETIC_RECEIPTS = [
    ("tid-a", "test-chat", "test-user", 0, 1000, 2000, None, None, 0),
    ("tid-b", "test-chat", "test-user", 1, 1001, None, None, None, 0),
    ("tid-c", "other-chat", "other-user", 0, 1002, 2002, 3002, None, 1),
]


def build_valid(path):
    """Create a structurally-valid, PII-free infra DB at `path`."""
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    try:
        con.executescript(INFRA_SCHEMA_DDL)
        con.executemany(
            "INSERT INTO receipt_device(stanza_id, chat_jid, user_jid, device_id, "
            "send_timestamp, delivered_timestamp, read_timestamp, played_timestamp, "
            "device_version) VALUES (?,?,?,?,?,?,?,?,?)",
            _SYNTHETIC_RECEIPTS,
        )
        con.execute(
            "INSERT INTO CQLMessagingInfraDatabaseSchemaUpgrader_cql_schema_facets"
            "(facet, version) VALUES (?, ?)",
            ("schema_version", 1),
        )
        con.commit()
    finally:
        con.close()
    return path


def _raises_malformed(path):
    """True if opening `path` raises a DatabaseError mentioning 'malformed'."""
    try:
        con = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
        try:
            con.execute("PRAGMA quick_check;").fetchall()
        finally:
            con.close()
        return False  # opened cleanly or returned rows — not what we want
    except sqlite3.DatabaseError as e:
        return "malformed" in str(e)


def _recoverable(path):
    """True if `sqlite3 .recover` salvages `path` into a quick_check-ok database."""
    rec = subprocess.run(["sqlite3", path, ".recover"], capture_output=True, text=True)
    if not rec.stdout.strip():
        return False
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        out = tf.name
    try:
        subprocess.run(["sqlite3", out], input=rec.stdout, text=True, check=True)
        con = sqlite3.connect(f"file:{out}?immutable=1", uri=True)
        try:
            q = con.execute("PRAGMA quick_check;").fetchall()
            return len(q) == 1 and q[0][0] == "ok"
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False
    finally:
        os.remove(out)


def build_malformed(path):
    """Create a fixture that SQLite reports as 'database disk image is malformed'.

    Keeps the 100-byte file header (incl. the 'SQLite format 3\\x00' magic) intact
    so the file is still recognised as a database, but breaks the schema b-tree on
    page 1 so loading the schema raises SQLITE_CORRUPT. Self-verifying: only emits
    a fixture that both raises 'malformed' and stays recoverable.
    """
    valid_tmp = path + ".valid"
    build_valid(valid_tmp)
    with open(valid_tmp, "rb") as f:
        base = bytearray(f.read())
    os.remove(valid_tmp)

    page_size = int.from_bytes(base[16:18], "big") or 4096
    # (offset, patch) candidates, most faithful first.
    candidates = [
        (100, b"\x01"),               # invalid b-tree page-type byte on page 1
        (103, b"\xff\xff"),           # absurd cell count in page-1 b-tree header
        (page_size, b"\x01"),         # invalid page-type byte on page 2 (fallback)
    ]
    for off, patch in candidates:
        cand = bytearray(base)
        cand[off:off + len(patch)] = patch
        with open(path, "wb") as f:
            f.write(cand)
        if _raises_malformed(path) and _recoverable(path):
            return path
    raise RuntimeError("could not build a malformed-but-recoverable infra fixture")


if __name__ == "__main__":  # quick manual check
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    print("valid     ->", build_valid(os.path.join(d, "infra_valid.sqlite")))
    print("malformed ->", build_malformed(os.path.join(d, "infra_malformed.sqlite")))
