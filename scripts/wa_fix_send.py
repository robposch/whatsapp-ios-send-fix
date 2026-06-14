#!/usr/bin/env python3
"""
wa_fix_send.py — Repair the corrupt MessagingInfraDatabase inside an iOS backup,
so a restore brings back a WhatsApp that can SEND again (with full history).

What it does:
  1. Locates MessagingInfraDB_v2/MessagingInfraDatabase.sqlite in the backup.
  2. Confirms it is malformed (the send bug).
  3. Salvages a clean copy with `sqlite3 .recover` (this DB holds only send
     queues + receipts — no messages, no keys — so a recovered/rebuilt copy is
     safe).
  4. Snapshots the originals, then swaps the clean copy back into the backup:
       - unencrypted backup: replace the file + fix Manifest.db's stored Size.
       - encrypted backup: re-encrypt the file with its own per-file key,
         fix the Size, and re-encrypt Manifest.db (AES-256-CBC, IV=0, PKCS7).

After it runs, RESTORE the edited backup to the iPhone (Finder "Restore
Backup"). For the cleanest result use an ENCRYPTED backup: the Keychain is
preserved, so WhatsApp stays logged in and simply opens the local (now healthy)
data. With an unencrypted backup WhatsApp will re-register: after restore, turn
OFF iCloud for WhatsApp, verify by SMS, and it will adopt the local data.

Safety: dry-run by default. Pass --apply to actually modify the backup. The
originals it touches are copied to <backup>/../wa_fix_snapshot_<id>/ first.

Usage:
    python3 wa_fix_send.py /path/to/backup            # dry run
    python3 wa_fix_send.py /path/to/backup --apply    # do it

Requirements:
    - python3, the `sqlite3` CLI
    - encrypted backups:  pip install iphone_backup_decrypt pycryptodome
"""
import argparse
import os
import plistlib
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile

DOMAIN_LIKE = "%whatsapp%"
INFRA_RELPATH = "MessagingInfraDB_v2/MessagingInfraDatabase.sqlite"


# ---------- small helpers ----------

def is_encrypted(backup_dir):
    with open(os.path.join(backup_dir, "Manifest.plist"), "rb") as f:
        return bool(plistlib.load(f).get("IsEncrypted"))


def quick_check_ok(path):
    con = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
    try:
        q = con.execute("PRAGMA quick_check;").fetchall()
        return len(q) == 1 and q[0][0] == "ok"
    finally:
        con.close()


def sqlite_recover(src_bytes, out_path):
    """Salvage a (possibly malformed) sqlite db into a clean file via .recover."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        tf.write(src_bytes)
        src_path = tf.name
    try:
        rec = subprocess.run(["sqlite3", src_path, ".recover"],
                             capture_output=True, text=True)
        if not rec.stdout.strip():
            raise RuntimeError(f".recover produced no output: {rec.stderr[:200]}")
        if os.path.exists(out_path):
            os.remove(out_path)
        subprocess.run(["sqlite3", out_path], input=rec.stdout, text=True, check=True)
    finally:
        os.remove(src_path)
    if not quick_check_ok(out_path):
        raise RuntimeError("recovered database still fails quick_check")


def manifest_blob_with_size(blob, new_size):
    pl = plistlib.loads(blob)
    mb = pl["$objects"][pl["$top"]["root"].data]
    mb["Size"] = new_size
    return plistlib.dumps(pl, fmt=plistlib.FMT_BINARY)


def pkcs7(d, bs=16):
    n = bs - (len(d) % bs)
    return d + bytes([n or bs]) * (n or bs)


def aes_cbc_encrypt(plaintext, key):
    from Crypto.Cipher import AES
    return AES.new(key, AES.MODE_CBC, iv=b"\x00" * 16).encrypt(pkcs7(plaintext))


def snapshot(paths, backup_dir):
    snap = os.path.join(os.path.dirname(os.path.abspath(backup_dir)),
                        "wa_fix_snapshot_" + os.path.basename(backup_dir.rstrip("/")))
    os.makedirs(snap, exist_ok=True)
    for p in paths:
        shutil.copy2(p, os.path.join(snap, os.path.basename(p)))
    return snap


# ---------- unencrypted path ----------

def fix_unencrypted(backup_dir, apply):
    mdb = os.path.join(backup_dir, "Manifest.db")
    con = sqlite3.connect(f"file:{mdb}?immutable=1", uri=True)
    row = con.execute(
        "SELECT fileID FROM Files WHERE relativePath=? AND domain LIKE ? AND flags=1",
        (INFRA_RELPATH, DOMAIN_LIKE)).fetchone()
    con.close()
    if not row:
        sys.exit("MessagingInfraDatabase not found in this backup.")
    fid = row[0]
    blob = os.path.join(backup_dir, fid[:2], fid)
    malformed = open(blob, "rb").read()
    if quick_check_ok(blob):
        sys.exit("MessagingInfraDatabase is already OK — nothing to fix (maybe not this bug).")
    print(f"  malformed infra DB: {blob}  ({len(malformed):,} bytes)")

    fixed_path = os.path.join(tempfile.gettempdir(), "wa_infra_fixed.sqlite")
    sqlite_recover(malformed, fixed_path)
    fixed = open(fixed_path, "rb").read()
    print(f"  recovered clean DB: {len(fixed):,} bytes  (quick_check ok)")

    if not apply:
        print("  [dry run] would replace the blob and set Manifest Size -> "
              f"{len(fixed):,}. Re-run with --apply.")
        return
    snap = snapshot([blob, mdb], backup_dir)
    print(f"  snapshot saved: {snap}")
    open(blob, "wb").write(fixed)
    con = sqlite3.connect(mdb)
    con.execute("PRAGMA journal_mode=DELETE;")
    b = con.execute("SELECT file FROM Files WHERE fileID=?", (fid,)).fetchone()[0]
    con.execute("UPDATE Files SET file=? WHERE fileID=?",
                (manifest_blob_with_size(b, len(fixed)), fid))
    con.commit()
    con.close()
    assert quick_check_ok(blob)
    print("  DONE — backup patched.")


# ---------- encrypted path ----------

def fix_encrypted(backup_dir, apply):
    from iphone_backup_decrypt import EncryptedBackup, utils
    import getpass
    pw = getpass.getpass("Backup password (hidden): ")
    bk = EncryptedBackup(backup_directory=backup_dir, passphrase=pw)
    bk.test_decryption()
    with bk.manifest_db_cursor() as cur:
        res = cur.execute(
            "SELECT fileID, file FROM Files WHERE relativePath=? AND domain LIKE ? AND flags=1",
            (INFRA_RELPATH, DOMAIN_LIKE)).fetchone()
    if not res:
        sys.exit("MessagingInfraDatabase not found in this backup.")
    fid, file_bplist = res
    fp = utils.FilePlist(file_bplist)
    inner_key = bk._keybag.unwrapKeyForClass(fp.protection_class, fp.encryption_key)
    malformed = bk.extract_file_as_bytes(INFRA_RELPATH, domain_like=DOMAIN_LIKE)
    print(f"  infra fileID {fid}  (plaintext {len(malformed):,} bytes)")

    tmp_mal = os.path.join(tempfile.gettempdir(), "wa_infra_malformed.sqlite")
    open(tmp_mal, "wb").write(malformed)
    if quick_check_ok(tmp_mal):
        sys.exit("MessagingInfraDatabase is already OK — nothing to fix (maybe not this bug).")
    fixed_path = os.path.join(tempfile.gettempdir(), "wa_infra_fixed.sqlite")
    sqlite_recover(malformed, fixed_path)
    fixed = open(fixed_path, "rb").read()
    print(f"  recovered clean DB: {len(fixed):,} bytes  (quick_check ok)")

    if not apply:
        print("  [dry run] would re-encrypt the file + Manifest.db. Re-run with --apply.")
        return

    blob = os.path.join(backup_dir, fid[:2], fid)
    mdb = os.path.join(backup_dir, "Manifest.db")
    snap = snapshot([blob, mdb], backup_dir)
    print(f"  snapshot saved: {snap}")

    # 1) re-encrypt the fixed db with the file's own key
    open(blob, "wb").write(aes_cbc_encrypt(fixed, inner_key))
    # 2) edit + re-encrypt Manifest.db
    dec_manifest = os.path.join(tempfile.gettempdir(), "wa_manifest_dec.db")
    bk.save_manifest_file(dec_manifest)
    con = sqlite3.connect(dec_manifest)
    con.execute("PRAGMA journal_mode=DELETE;")
    b = con.execute("SELECT file FROM Files WHERE fileID=?", (fid,)).fetchone()[0]
    con.execute("UPDATE Files SET file=? WHERE fileID=?",
                (manifest_blob_with_size(b, len(fixed)), fid))
    con.commit()
    con.close()
    mk_class = struct.unpack("<l", bk._manifest_plist["ManifestKey"][:4])[0]
    mk = bk._keybag.unwrapKeyForClass(mk_class, bk._manifest_plist["ManifestKey"][4:])
    open(mdb, "wb").write(aes_cbc_encrypt(open(dec_manifest, "rb").read(), mk))
    os.remove(dec_manifest)

    # 3) verify with a fresh decrypt
    bk2 = EncryptedBackup(backup_directory=backup_dir, passphrase=pw)
    check = os.path.join(tempfile.gettempdir(), "wa_infra_verify.sqlite")
    bk2.extract_file(relative_path=INFRA_RELPATH, domain_like=DOMAIN_LIKE, output_filename=check)
    assert quick_check_ok(check), "verification failed"
    print("  DONE — encrypted backup patched and verified.")


def main():
    ap = argparse.ArgumentParser(description="Repair WhatsApp send bug in an iOS backup.")
    ap.add_argument("backup_dir")
    ap.add_argument("--apply", action="store_true", help="actually modify the backup (default: dry run)")
    args = ap.parse_args()
    backup_dir = os.path.expanduser(args.backup_dir)
    if not os.path.isfile(os.path.join(backup_dir, "Manifest.plist")):
        sys.exit(f"Not a backup directory: {backup_dir}")
    enc = is_encrypted(backup_dir)
    print(f"Backup: {backup_dir}\nEncrypted: {enc}\nMode: {'APPLY' if args.apply else 'dry run'}\n")
    (fix_encrypted if enc else fix_unencrypted)(backup_dir, args.apply)
    if args.apply:
        print("\nNext: restore this backup to the iPhone (Finder > Restore Backup), Find My off.\n"
              "Encrypted backup -> WhatsApp stays logged in and just works.\n"
              "Unencrypted -> after restore, turn off iCloud for WhatsApp, verify by SMS,\n"
              "and it will adopt the local (fixed) data. Also delete any old WhatsApp\n"
              "iCloud backup so a later iCloud restore can't re-introduce the corruption.")


if __name__ == "__main__":
    main()
