# Case study: "WhatsApp receives but won't send after a restore"

This is the long-form story behind the fix in this repo — the symptom, the dead
ends, the systematic investigation, and the root cause. If you just want to fix
your phone, see the [README](README.md). If you want to understand *why* nothing
else worked, read on.

## The symptom

An iPhone went through a clean-start cycle — Erase All Content and Settings,
then a restore from an encrypted Finder backup. Afterwards WhatsApp could
**receive** messages but **could not send** a single one: a red ❗ on every
outgoing message, in every chat. It only happened after restoring a backup, and
it survived everything thrown at it.

## The dead ends (and why each was a dead end)

Almost everything you'd try — and everything support suggests — fails here,
because none of it touches the actual problem:

- **Reinstalling WhatsApp** — no effect. The corruption lives in the app's data
  container, not the app binary.
- **Re-verifying the number** — no effect, and oddly painful: verification codes
  were routed to the existing (broken) WhatsApp session on the same phone
  instead of arriving by SMS, so each attempt just re-blessed the broken install.
- **Removing account auth methods** (passkeys, email) — no effect. Account-level
  settings can't fix a corrupt file on the device.
- **Turning off WhatsApp's iCloud-backup end-to-end encryption** — no effect on
  sending (it only made the backup decryptable for later analysis).
- **Restoring from the WhatsApp iCloud backup** — actively re-broke sending,
  because that backup had been uploaded by the already-broken install and
  carried the corruption with it.
- **A fresh phone + restore** — still broken, for the same reason.
- **A WhatsApp device-to-device chat transfer** — the transfer copied, then the
  importer **aborted** ("try without chats"): WhatsApp's own validator rejected
  the data.
- **Contacting support** — the ticket was closed without comment. Even insiders
  said "this can't happen, restore should always work."

Theories that got ruled out along the way: an account ban (a linked companion
device could send — so the account was healthy), a network/DNS block (receiving
worked), a "ghost" registration session (real, but a symptom), server-side
breakage (a no-restore install could send), and the device's Keychain identity
key (a genuinely fresh phone still failed once it restored the data).

The one clue that mattered: **a linked companion (Web/Desktop/another phone)
could send.** That proves the account and number are fine — the breakage is
local to this device's send path.

## The investigation

The breakthrough came from stopping the guess-and-restore loop and **inspecting
the actual data** in the backup:

1. **Decrypt the messages database** (`ChatStorage.sqlite`) and integrity-check
   it → perfectly fine, full history intact. *The messages were never the
   problem.* That single fact inverted the whole theory.
2. **Integrity-check every WhatsApp database** in the container. All clean except
   one: `MessagingInfraDB_v2/MessagingInfraDatabase.sqlite` → *database disk
   image is malformed* (genuine B-tree corruption — pages referencing
   non-existent pages, not a decryption artifact).
3. **Look inside it.** Salvaged with `sqlite3 .recover`, it holds only send
   queues (`chat_queue`, `e2ee_queue`, `unordered_queue`, `message_status` — all
   empty) and receipt tracking, plus schema bookkeeping. **No messages, no
   contacts, no identity keys, no Signal sessions.** Pure send-pipeline plumbing.
4. **Pin the timeline** across several dated backups: clean in the oldest,
   malformed from the day of the erase-and-restore onward.

That maps exactly onto the symptom: messages intact → receiving works; send
queues corrupt → every send fails and the importer aborts.

## Root cause and how it spreads

The corruption was a **one-time event** during a backup/restore cycle: the
send-queue database got written malformed. From then on it was **carried in
every backup** — Finder *and* iCloud — and faithfully re-installed on each
restore. The restore process does **not** regenerate the corruption: a healthy
copy, once restored, stays healthy (this repo's fix proves it). WhatsApp's launch
path simply **doesn't validate or rebuild** a malformed `MessagingInfraDatabase`
— it fails to send instead of self-healing.

This is also why it felt unkillable: once the broken phone had uploaded a
WhatsApp iCloud chat backup, **both** the local backups and the cloud backup
were poisoned, so every recovery path reintroduced the same file.

## The fix

Because the file holds nothing irreplaceable, the fix is to give WhatsApp a
**healthy** copy of it while keeping the intact `ChatStorage`:

1. Recover a clean `MessagingInfraDatabase` with `sqlite3 .recover`.
2. Swap it back into the device backup (re-encrypting it for an encrypted
   backup — iOS uses AES-256-CBC, zero IV, PKCS7, and the per-file key can be
   reused as-is).
3. Restore the edited backup. With an **encrypted** backup the Keychain is
   preserved, so WhatsApp stays logged in and just opens the local, healthy data.
4. Delete any poisoned WhatsApp iCloud backup and make a fresh one, so a later
   iCloud restore can't re-introduce the corruption.

Messages and a working send pipeline, decoupled — surgically.

## Lessons

- "Receive but not send" on one device, surviving reinstalls, after a restore →
  suspect **local data corruption**, not the account, network, or servers.
- A working **companion device** is the fastest way to prove the account is fine.
- The fastest real diagnostic isn't more restores — it's
  `PRAGMA integrity_check` on the databases in the backup.
- A restore "working" doesn't mean the **restored data** is healthy.
