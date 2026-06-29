#!/usr/bin/env python3
"""
wa_send_diagnose.py — Diagnose WhatsApp "receives but won't send after restore".

This integrity-checks every WhatsApp database inside an iOS device backup.
The signature of this specific bug is:

    MessagingInfraDB_v2/MessagingInfraDatabase.sqlite  ->  database disk image is malformed

while ChatStorage.sqlite (your actual messages) is perfectly fine. That one
corrupt database is WhatsApp's outbound send-queue; when it's malformed the app
receives normally but every outgoing message fails with a red "!".

Works with both ENCRYPTED and UNENCRYPTED Finder/iTunes backups. The backup
password (for encrypted backups) is read interactively and never stored.

Usage:
    python3 wa_send_diagnose.py /path/to/backup
    python3 wa_send_diagnose.py            # lists backups in the default macOS location

Requirements:
    - python3, the `sqlite3` CLI
    - encrypted backups only:  pip install iphone_backup_decrypt pycryptodome
"""
import getpass
import os
import plistlib
import sqlite3
import sys
import tempfile

DOMAIN_LIKE = "%whatsapp%"
INFRA_NAME = "MessagingInfraDatabase.sqlite"
DEFAULT_ROOT = os.path.expanduser("~/Library/Application Support/MobileSync/Backup")


def is_encrypted(backup_dir):
    with open(os.path.join(backup_dir, "Manifest.plist"), "rb") as f:
        return bool(plistlib.load(f).get("IsEncrypted"))


def list_backups():
    if not os.path.isdir(DEFAULT_ROOT):
        return []
    out = []
    for name in sorted(os.listdir(DEFAULT_ROOT)):
        p = os.path.join(DEFAULT_ROOT, name)
        if os.path.isfile(os.path.join(p, "Manifest.plist")):
            out.append(p)
    return out


def quick_check(path):
    """Return ('OK'|'MALFORMED'|'TOKENIZER'|'ERROR', detail)."""
    try:
        con = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
        rows = con.execute("PRAGMA quick_check;").fetchall()
        con.close()
        if len(rows) == 1 and rows[0][0] == "ok":
            return "OK", "ok"
        return "MALFORMED", "; ".join(str(r[0]) for r in rows[:2])
    except sqlite3.DatabaseError as e:
        msg = str(e)
        # WhatsApp's full-text-search DBs use custom tokenizers that plain
        # sqlite3 can't load — that's NOT corruption, just an unreadable FTS DB.
        if "tokenizer" in msg:
            return "TOKENIZER", msg
        # Severe corruption makes quick_check raise instead of returning rows;
        # that's still the malformed-DB bug, so classify it accordingly.
        if "malformed" in msg or "not a database" in msg:
            return "MALFORMED", msg
        return "ERROR", msg


def whatsapp_sqlites_unencrypted(backup_dir):
    mdb = os.path.join(backup_dir, "Manifest.db")
    con = sqlite3.connect(f"file:{mdb}?immutable=1", uri=True)
    rows = con.execute(
        "SELECT fileID, relativePath FROM Files "
        "WHERE domain LIKE ? AND relativePath LIKE '%.sqlite' AND flags=1 "
        "ORDER BY relativePath",
        (DOMAIN_LIKE,),
    ).fetchall()
    con.close()
    for fid, rp in rows:
        yield rp, os.path.join(backup_dir, fid[:2], fid)


def whatsapp_sqlites_encrypted(backup_dir, pw, workdir):
    from iphone_backup_decrypt import EncryptedBackup
    bk = EncryptedBackup(backup_directory=backup_dir, passphrase=pw)
    with bk.manifest_db_cursor() as cur:
        rows = cur.execute(
            "SELECT relativePath, domain FROM Files "
            "WHERE domain LIKE ? AND relativePath LIKE '%.sqlite' AND flags=1 "
            "ORDER BY relativePath",
            (DOMAIN_LIKE,),
        ).fetchall()
    for rp, domain in rows:
        out = os.path.join(workdir, rp.replace("/", "__"))
        try:
            bk.extract_file(relative_path=rp, domain_like=domain, output_filename=out)
            yield rp, out
        except Exception as e:  # noqa: BLE001
            print(f"  (could not extract {rp}: {e})")


def main():
    if len(sys.argv) > 1:
        backup_dir = os.path.expanduser(sys.argv[1])
    else:
        backups = list_backups()
        if not backups:
            sys.exit(f"No backups found in {DEFAULT_ROOT}. Pass a backup path explicitly.")
        print("Backups found (newest paths usually have a date suffix):")
        for i, b in enumerate(backups):
            print(f"  [{i}] {os.path.basename(b)}")
        backup_dir = backups[int(input("Pick a backup number: ").strip())]

    if not os.path.isfile(os.path.join(backup_dir, "Manifest.plist")):
        sys.exit(f"Not a backup directory (no Manifest.plist): {backup_dir}")

    enc = is_encrypted(backup_dir)
    print(f"\nBackup: {backup_dir}\nEncrypted: {enc}\n")

    infra_status = None
    chatstorage_status = None
    with tempfile.TemporaryDirectory() as workdir:
        if enc:
            pw = getpass.getpass("Backup password (hidden): ")
            files = whatsapp_sqlites_encrypted(backup_dir, pw, workdir)
        else:
            files = whatsapp_sqlites_unencrypted(backup_dir)

        print(f"{'WhatsApp database':52} status")
        print("-" * 78)
        for rp, path in files:
            if path is None or not os.path.exists(path):
                continue
            status, detail = quick_check(path)
            mark = {"OK": "ok", "MALFORMED": "*** MALFORMED ***",
                    "TOKENIZER": "ok (custom FTS tokenizer)", "ERROR": f"error: {detail}"}[status]
            print(f"{rp:52} {mark}")
            if os.path.basename(rp) == INFRA_NAME:
                infra_status = status
            if os.path.basename(rp) == "ChatStorage.sqlite":
                chatstorage_status = status

    print("\n" + "=" * 78)
    if infra_status == "MALFORMED" and chatstorage_status in ("OK", None):
        print("DIAGNOSIS: This is the bug. MessagingInfraDatabase is malformed while your\n"
              "messages (ChatStorage) are intact. Use wa_fix_send.py to repair it.")
    elif infra_status == "MALFORMED":
        print("MessagingInfraDatabase is malformed (the send bug), but ChatStorage also\n"
              "looks problematic — check it before relying on the messages.")
    elif infra_status == "OK":
        print("MessagingInfraDatabase is OK — this particular bug is NOT your problem.")
    else:
        print("Could not determine MessagingInfraDatabase status — see the table above.")


if __name__ == "__main__":
    main()
