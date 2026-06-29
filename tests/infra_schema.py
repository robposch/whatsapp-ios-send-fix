"""Schema (DDL only) for MessagingInfraDatabase.sqlite.

This is the *structure* of WhatsApp's send-queue database — table and column
names extracted from a real recovered copy. It contains NO rows, no JIDs, no
message content. Test fixtures are built from this string so the fixture files
never contain personal data (see tests/build_fixture.py and tests/pii_scan.py).

`sqlite_sequence` is intentionally omitted: SQLite creates it automatically for
the AUTOINCREMENT tables below.
"""

INFRA_SCHEMA_DDL = """
CREATE TABLE CQLMessagingInfraDatabaseSchemaUpgrader_cql_schema_facets( facet TEXT NOT NULL PRIMARY KEY, version LONG_INT NOT NULL );

CREATE TABLE chat_queue( row_id INTEGER PRIMARY KEY AUTOINCREMENT, stanza_key BLOB UNIQUE NOT NULL, stanza_id TEXT NOT NULL, stanza_class INTEGER NOT NULL, stanza_type INTEGER NOT NULL, stanza_payload BLOB NOT NULL, protobuf BLOB, chat_type INTEGER, chat_jid TEXT, sender_jid TEXT, ts LONG_INT NOT NULL, process_count INTEGER NOT NULL, receive_time LONG_INT NOT NULL, processed_by_nse BOOL NOT NULL DEFAULT 0, sort_id INTEGER NOT NULL );

CREATE TABLE e2ee_queue( row_id INTEGER PRIMARY KEY AUTOINCREMENT, stanza_key BLOB UNIQUE NOT NULL, stanza_id TEXT NOT NULL, stanza_class INTEGER NOT NULL, stanza_type INTEGER NOT NULL, stanza_payload BLOB NOT NULL, chat_type INTEGER, chat_jid TEXT, sender_jid TEXT, ts LONG_INT NOT NULL, process_count INTEGER NOT NULL, receive_time LONG_INT NOT NULL, processed_by_nse BOOL NOT NULL DEFAULT 0, sort_id INTEGER NOT NULL, offline_count INTEGER, e2e_retry_count INTEGER NOT NULL DEFAULT 0, has_pkmsg BOOL NOT NULL DEFAULT 0, has_skmsg BOOL NOT NULL DEFAULT 0 );

CREATE TABLE message_status( message_unique_key TEXT NOT NULL PRIMARY KEY CHECK(length(message_unique_key) > 0) , current_status INTEGER, pending_status INTEGER, expected_count INTEGER, updated_at LONG_INT NOT NULL );

CREATE TABLE receipt_device( _id INTEGER PRIMARY KEY AUTOINCREMENT, stanza_id TEXT NOT NULL CHECK(length(stanza_id) > 0) , chat_jid TEXT NOT NULL CHECK(length(chat_jid) > 0) , user_jid TEXT NOT NULL CHECK(length(user_jid) > 0) , device_id INTEGER NOT NULL, send_timestamp LONG_INT, delivered_timestamp LONG_INT, read_timestamp LONG_INT, played_timestamp LONG_INT, device_version INTEGER );

CREATE TABLE unordered_queue( row_id INTEGER PRIMARY KEY AUTOINCREMENT, stanza_key BLOB UNIQUE NOT NULL, stanza_id TEXT NOT NULL, stanza_class INTEGER NOT NULL, stanza_type INTEGER NOT NULL, stanza_payload BLOB NOT NULL, protobuf BLOB, decrypt_metadata BLOB, chat_type INTEGER, chat_jid TEXT, sender_jid TEXT, ts LONG_INT NOT NULL, process_count INTEGER NOT NULL , receive_time LONG_INT NOT NULL DEFAULT 0, processed_by_nse BOOL NOT NULL DEFAULT 0);

CREATE INDEX chat_idx_chat_jid ON chat_queue (chat_jid);
CREATE INDEX chat_idx_processed_by_nse ON chat_queue (processed_by_nse, sort_id);
CREATE INDEX chat_idx_sort_id ON chat_queue (sort_id);
CREATE INDEX e2ee_idx_chat_jid ON e2ee_queue (chat_jid);
CREATE INDEX e2ee_idx_processed_by_nse ON e2ee_queue (processed_by_nse, sort_id);
CREATE INDEX e2ee_idx_sort_id ON e2ee_queue (sort_id);
CREATE INDEX idx_chat_jid ON unordered_queue (chat_jid);
CREATE INDEX idx_message_status_pending ON message_status (pending_status);
CREATE INDEX idx_processed_by_nse ON unordered_queue (stanza_key, processed_by_nse);
CREATE INDEX idx_stanza_class_type ON unordered_queue (stanza_class, stanza_type, ts);
CREATE INDEX idx_stanza_class_type_chat_jid ON unordered_queue (stanza_class, stanza_type, chat_jid);
CREATE INDEX idx_stanza_key ON unordered_queue (stanza_key);
CREATE INDEX idx_stanza_lookup ON unordered_queue (stanza_id, stanza_class, sender_jid, chat_jid);
CREATE UNIQUE INDEX receipt_device_unique_index ON receipt_device (stanza_id, chat_jid, user_jid, device_id);
"""
