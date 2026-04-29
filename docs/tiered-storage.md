# Tiered blob storage

Blobs (raw RFC822 email bodies and attachments) live in PostgreSQL by
default. Once a blob is older than `TIERED_STORAGE_OFFLOAD_AFTER_DAYS`,
a periodic celery task moves its bytes to S3 and clears the PG row's
`raw_content`. Reads transparently fetch from whichever location the
row points at — application code only ever calls `blob.get_content()`.

## Architecture

- **Storage path**: `blobs/{key_id}/{sha[:3]}/{sha}`. The leading
  `key_id` segment lets blobs encrypted with different keys coexist
  (essential for crash-safe online key rotation). The 3-char sha
  prefix shards each key into 4096 sub-prefixes for S3 request-rate
  balance.
- **Deduplication**: blobs sharing the same SHA-256 share the same S3
  object. The DB is the source of truth; the existence check on S3 is
  a defensive guard against external deletions.
- **Concurrency**: a Postgres transaction-scoped advisory lock keyed
  on the first 8 bytes of sha256 serializes offload, cleanup, and
  re-encrypt for any one content. Different shas run in parallel.
- **Encryption**: optional AES-256-GCM. Configured keys are arbitrary
  high-entropy strings, hashed to 32 bytes via SHA-256 (same pattern
  as `encrypted-fields`'s `SALT_KEY`). Storage layout per object:
  `nonce(12) || ciphertext+tag(16)`. Total overhead: 28 bytes,
  no base64.

## Enabling offload

By default everything runs in PostgreSQL with `raw_content` populated.
To start moving cold blobs to S3:

1. Provision a bucket and credentials.
2. Set the `STORAGE_MESSAGE_BLOBS_*` env vars (see [env.md](env.md)).
3. `make create-buckets` (or the production equivalent).
4. Set `TIERED_STORAGE_OFFLOAD_ENABLED=True`.

The next celery beat tick (default hourly) starts queuing eligible
blobs. Each blob is offloaded by a single worker holding its
per-sha advisory lock; the operation is atomic at the row level.

## Encryption

To enable encryption-at-rest for blobs:

1. Generate a random secret string (≥ 32 chars):
   ```sh
   openssl rand -base64 32
   ```
2. Add it to `MESSAGES_BLOB_ENCRYPTION_KEYS` as a JSON dict:
   ```sh
   MESSAGES_BLOB_ENCRYPTION_KEYS='{"1": "<the secret>"}'
   MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=1
   ```
3. Restart. New blobs are encrypted; existing unencrypted blobs
   (`encryption_key_id=0`) keep working until they're rotated.

`manage.py check` validates the config at startup and refuses to
boot if the active key isn't in the dict.

**Lose the key dict, lose the data.** Back it up alongside your DB.

## Key rotation runbook

To rotate from key 1 to key 2:

1. Add the new key alongside the old one, set it active:
   ```sh
   MESSAGES_BLOB_ENCRYPTION_KEYS='{"1": "<old>", "2": "<new>"}'
   MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=2
   ```
   New blobs encrypt under key 2 immediately; existing blobs stay on
   key 1.
2. **Pause offload to avoid a race**:
   ```sh
   TIERED_STORAGE_OFFLOAD_ENABLED=False
   ```
   Wait for in-flight tasks to drain.
3. Run the rotation:
   ```sh
   python manage.py verify_tiered_storage --re-encrypt
   ```
   For each blob with `encryption_key_id != 2`, the command
   - writes the new ciphertext to `blobs/2/...` (atomic S3),
   - flips the dedup cohort's `encryption_key_id` to 2 (atomic DB),
   - best-effort deletes the old `blobs/1/...` path.

   Each step is independently atomic, so a crash at any point leaves
   the blob readable from one consistent path.
4. Confirm key 1's prefix is empty:
   ```sh
   aws s3 ls s3://msg-blobs/blobs/1/
   ```
   If anything remains, re-run the command (it's idempotent) or use
   `verify_tiered_storage --mode=storage-to-db` to list orphans for
   manual cleanup.
5. Re-enable offload, then drop key 1 from the dict in a follow-up
   deploy:
   ```sh
   TIERED_STORAGE_OFFLOAD_ENABLED=True
   MESSAGES_BLOB_ENCRYPTION_KEYS='{"2": "<new>"}'
   ```

## Verification

`python manage.py verify_tiered_storage` runs three read-only checks:

- **`--mode=db-to-storage`** — every blob row marked `OBJECT_STORAGE`
  has its expected S3 object (HEAD per row).
- **`--mode=storage-to-db`** — every S3 object under `blobs/` has a
  matching DB row (LIST + DB lookup per object).
- **`--verify-hashes`** — additionally downloads each object,
  decrypts, decompresses, and recomputes SHA-256. Slow; use after
  storage incidents.

The command never deletes; it only reports. Use the output to drive
manual recovery (re-upload a missing blob from PG if `raw_content`
still exists, or `aws s3 rm` an orphan after confirming nothing
references it).

## Recovery scenarios

| Symptom | Detection | Fix |
|---|---|---|
| DB row says `OBJECT_STORAGE` but S3 object missing | `verify --mode=db-to-storage` reports `MISSING` | If another row with the same sha is `POSTGRES`, dedup will repair on next offload. Otherwise the blob is lost — restore from backup. |
| S3 object with no DB row | `verify --mode=storage-to-db` reports `ORPHAN` | After confirming, `aws s3 rm` the object. |
| Hash mismatch | `verify --verify-hashes` reports `HASH MISMATCH` | The S3 object is corrupted. Treat as data loss; restore from backup. |
| Old key_id prefix non-empty after rotation | `aws s3 ls blobs/<old>/` | Re-run `--re-encrypt`; it's idempotent. |

## Operational notes

- **Initial rollout** on a populated DB will queue one celery task per
  eligible blob in a single beat tick. To avoid a queue burst, ramp
  `TIERED_STORAGE_OFFLOAD_AFTER_DAYS` down gradually (e.g. 365 → 90 →
  30 → 3 across multiple cycles).
- **Reading offloaded blobs** triggers a synchronous S3 GET in the
  request path. Old messages are rarely re-opened, so this is
  generally invisible — but expect 50–500 ms latency when it does
  happen.
- **Bulk deletes** (e.g. mailbox cascade) fire one cleanup task per
  blob via `transaction.on_commit`. For very large mailboxes this is
  a queue spike, not a hot-path problem.
