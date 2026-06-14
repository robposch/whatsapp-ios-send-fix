# Bug report — WhatsApp iOS fails to send (never recovers) when a restored backup contains a malformed MessagingInfraDatabase

**Component:** WhatsApp for iOS — messaging infrastructure / startup
**Type:** Data-integrity resilience gap (no self-heal of a regenerable DB)
**Severity:** High for affected users — total, persistent loss of *send* (receive
still works); not user-recoverable through any in-app path.

## Summary

After restoring an iPhone from a device backup (Finder/iTunes or iCloud),
WhatsApp can **receive but cannot send** — a red ❗ on every outgoing message, in
every chat. The cause is a **malformed**
`AppDomainGroup-group.net.whatsapp.WhatsApp.shared :
MessagingInfraDB_v2/MessagingInfraDatabase.sqlite`. The app opens this database
on launch but **does not validate or rebuild it when it is corrupt** — it
silently fails to send instead of regenerating the (regenerable) database.

Because the corrupt file is included in every subsequent device backup *and* in
the WhatsApp iCloud chat backup uploaded by the broken install, **every restore
re-installs it**, making the failure appear permanent and "impossible."

## Impact / why it's hard for users

- `ChatStorage.sqlite` (messages) is intact → receiving works → users don't
  suspect data corruption.
- App reinstall, number re-verification, removing passkeys/email, toggling
  iCloud-backup encryption — none help (none touch this file).
- Restoring from the WhatsApp iCloud backup re-breaks it (the backup carries the
  corrupt state).
- A linked companion (Web/Desktop/linked phone) sends fine — confirming the
  account/number are healthy and isolating the fault to this device's send path.
- Support has no path for this; the symptom ("can't send") is indistinguishable
  from many unrelated issues without inspecting the database.

## Reproduction / evidence

On a backup from an affected device, integrity-checking the WhatsApp databases
shows exactly one malformed file:

```
ChatStorage.sqlite                                    PRAGMA quick_check -> ok
MessagingInfraDB_v2/MessagingInfraDatabase.sqlite     -> database disk image is malformed
```

`PRAGMA integrity_check` on the malformed DB reports B-tree damage (cells
referencing page numbers beyond the file, duplicate page references) — i.e. a
genuinely corrupt on-disk image, not a truncation/decrypt artifact (the file is
complete length per its own header).

The malformed DB, recovered via `sqlite3 .recover`, contains only:
`chat_queue`, `e2ee_queue`, `unordered_queue`, `message_status` (send/ack
queues, typically empty), `receipt_device` (delivery-receipt tracking), and the
schema-version table. **No messages, no contacts, no identity/Signal key
material.** It is transient, regenerable infrastructure state.

## Root cause (observed)

The corruption originates as a one-time event during a backup/restore cycle;
the database is written malformed. The restore mechanism then faithfully copies
it on every subsequent restore (verified: substituting a healthy copy and
restoring yields a working send path — so the restore does not *generate* the
corruption, it propagates it). On launch, WhatsApp opens the malformed DB and
the send pipeline is dead, with no detection or rebuild.

## Suggested fix

On launch/import, run an integrity check on `MessagingInfraDatabase` and, if it
is malformed/unopenable, **rebuild it from scratch** (it holds only regenerable
queue/receipt state). Optionally also exclude it from chat-backup payloads, or
validate-and-rebuild on restore/import. This single defensive step would
eliminate the entire "receive-but-not-send after restore" failure class.

## Known workaround (user side)

Recover the database with `sqlite3 .recover`, swap it back into the device
backup (re-encrypting the single file for encrypted backups: AES-256-CBC, zero
IV, PKCS7, per-file key reused), and restore. Scripts and full instructions:
see this repository's README.
