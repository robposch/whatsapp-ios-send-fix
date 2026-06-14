# WhatsApp on iOS: "receives but won't send after a restore" — diagnosis & fix

If you restored your iPhone from a backup and now **WhatsApp receives messages
but every outgoing message fails with a red ❗**, this repo explains why and how
to fix it — and gives you scripts to do it.

The cause is almost always a **single corrupt database** inside WhatsApp's
container: `MessagingInfraDB_v2/MessagingInfraDatabase.sqlite`. It's the
outbound **send-queue** plumbing. When it's malformed, incoming messages still
land (they go into `ChatStorage.sqlite`, which is fine), but nothing can be
sent. Reinstalling WhatsApp, re-verifying your number, removing passkeys/email,
toggling backup encryption — none of it helps, because none of it touches that
file. And every restore just re-installs the same corrupt copy.

> ⚠️ **Disclaimer:** this edits iOS backups on your own machine. It worked for
> the author, but it is provided as-is with no warranty. Keep a copy of your
> backup, and don't run it on data you can't afford to lose. Editing backups is
> for **your own device and data** only.

---

## Is this you? (the symptom)

- WhatsApp **receives** fine, but **every** outgoing message shows a red ❗, in
  every chat.
- It started **only after restoring** a device backup (Finder/iTunes or iCloud).
- It **survives** reinstalling the app and re-verifying your number.
- A **fresh install with no restore** can send — but has no history.
- A linked **companion** (WhatsApp Web / Desktop / a linked phone) **can send** —
  proof your account and number are healthy; only this device's send-path is broken.

If that matches, run the diagnostic below.

---

## Requirements

- macOS (or any machine with your iOS backup), Python 3, and the `sqlite3` CLI.
- For **encrypted** backups (recommended): `pip install iphone_backup_decrypt pycryptodome`
- An iOS device backup made by Finder/iTunes (encrypted strongly preferred — see below).

---

## Step 1 — Diagnose

```bash
python3 scripts/wa_send_diagnose.py /path/to/MobileSync/Backup/<backup-id>
# or, with no argument, it lists the backups it can find
```

It decrypts (if needed) and runs `PRAGMA quick_check` on every WhatsApp
database. The smoking gun:

```
MessagingInfraDB_v2/MessagingInfraDatabase.sqlite   *** MALFORMED ***
ChatStorage.sqlite                                  ok
```

(Two databases — `emoji.sqlite` and the chat-search index — may show an
"unknown tokenizer" note. That's **not** corruption; WhatsApp uses custom
full-text-search tokenizers that plain `sqlite3` can't load. The script labels
them accordingly.)

---

## Step 2 — Fix the backup

```bash
python3 scripts/wa_fix_send.py /path/to/Backup/<backup-id>            # dry run
python3 scripts/wa_fix_send.py /path/to/Backup/<backup-id> --apply    # do it
```

It salvages a clean `MessagingInfraDatabase` with `sqlite3 .recover` (the file
holds only **empty send queues + receipt rows + schema bookkeeping — no
messages, no keys**, so a rebuilt copy is safe), then swaps it into the backup:

- **Unencrypted backup:** replaces the file and fixes the stored size in `Manifest.db`.
- **Encrypted backup:** re-encrypts the file with its own per-file key and
  re-encrypts `Manifest.db` (iOS uses AES-256-CBC, zero IV, PKCS7 padding;
  the per-file key is reused, not re-wrapped).

Originals it touches are snapshotted to `wa_fix_snapshot_<id>/` next to the
backup, so you can revert.

---

## Step 3 — Restore to the iPhone

Finder → select the iPhone → **Restore Backup…** → pick the edited backup.
(Find My must be off. Be patient — the restore can look stuck for a while
before completing.)

**Encrypted backup (recommended):** the Keychain is restored, so WhatsApp stays
**logged in** and just opens the local, now-healthy data. Sending works, history
intact, no re-verification.

**Unencrypted backup:** the Keychain is *not* in the backup, so WhatsApp
re-registers. After the restore, **before opening WhatsApp**:
1. Turn **off** iCloud for WhatsApp (Settings → iCloud → WhatsApp → Off), so it
   can't pull a (possibly still-poisoned) iCloud backup.
2. Open WhatsApp, **verify by SMS**.
3. It adopts the **local** restored data → sending works, history intact.

---

## Step 4 — Don't let iCloud re-poison it

If your broken phone ever uploaded a WhatsApp **iCloud chat backup**, that
backup carries the corruption too — restoring from it later will re-break
sending. Once the phone is healthy:

1. Delete the old WhatsApp iCloud chat backup
   (WhatsApp → Settings → Chats → Chat Backup, and/or iCloud storage management).
2. Make a **fresh** chat backup from the now-healthy phone.

Now both the device and the cloud are clean.

---

## Why this happens

The corruption is a **one-time event** during a backup/restore cycle — the
send-queue database gets written malformed. From then on it's **carried in every
backup** (Finder *and* iCloud) and faithfully re-installed on each restore. The
restore process itself does **not** regenerate the corruption: a healthy copy
restored stays healthy. WhatsApp's launch path simply **doesn't validate or
rebuild** a malformed `MessagingInfraDatabase` — it fails to send instead of
self-healing.

### Suggested upstream fix (for WhatsApp)

On launch/import, integrity-check `MessagingInfraDatabase` and **rebuild it if
malformed** (it's regenerable plumbing). That one defensive check would
eliminate this entire "receive-but-not-send after restore" class of failure.

---

## Files

| File | Purpose |
|---|---|
| `scripts/wa_send_diagnose.py` | Integrity-check every WhatsApp DB in a backup; flag the malformed one. |
| `scripts/wa_fix_send.py` | Recover the DB and patch it back into the backup (encrypted or unencrypted). |

Passwords are read interactively (`getpass`) and never stored or logged.
