# Search Index Update Mechanism

Threads and messages are searchable through an OpenSearch index. This document
describes how the index stays in sync with the database: when writes are
picked up, how they are batched, and how the index is rebuilt from scratch.

## Overview

The index is kept up to date through three cooperating paths:

1. **Model signals** — `post_save` / `post_delete` on `Thread`, `Message`,
   `MessageRecipient` and `ThreadAccess` schedule an index update.
2. **Coalescing buffer** — Signal-driven updates are pushed to a pending set
   (backed by Redis in prod, or the Django cache in tests / single-process
   deployments) and drained periodically. A burst of writes on the same
   thread collapses into one reindex.
3. **Scoped deferrer** — Bulk flows (IMAP / MBOX / PST / EML imports) wrap
   their work in `ThreadReindexDeferrer.defer()` so all touched threads are
   reindexed in a single bulk task at scope exit.

All index writes happen asynchronously through Celery on the `reindex` queue.
A full reindex is available through a management command for recovery and
index-schema changes.

## Index Model

The index is named `messages` (see
`src/backend/core/services/search/mapping.py`). It uses an OpenSearch
**parent-child join** so a `Thread` document is the parent of its `Message`
children:

- **Thread parent document**: `thread_id`, `subject`, `mailbox_ids`,
  `unread_mailboxes`, `starred_mailboxes`.
- **Message child document**: full message metadata (subject, sender,
  recipients, body text, flags) with `_routing = thread_id` so parent and
  children live on the same shard.

The parent document carries `unread_mailboxes` and `starred_mailboxes` fields
derived from `ThreadAccess` rows. Changing read/starred state triggers a full
thread reindex — partial updates are not used because they do not work
reliably with join-field documents in OpenSearch
(`update_thread_mailbox_flags` uses `es.index` for the same reason).

## Write Path

### Signals

Located in `src/backend/core/signals.py`, all handlers bail out when
`OPENSEARCH_INDEX_THREADS` is disabled.

| Signal | Model | Action |
|--------|-------|--------|
| `post_save` | `Message` | Reindex parent thread |
| `post_save` | `MessageRecipient` | Reindex parent thread (on update only — create is already covered by the `Message` save) |
| `post_save` | `Thread` | Reindex thread |
| `post_save` | `ThreadAccess` | Reindex thread if `read_at` or `starred_at` changed |
| `post_delete` | `Message` | Reindex parent thread (the bulk reindex purges the orphan message document) |
| `post_delete` | `Thread` | Enqueue the thread ID into the delete coalescing buffer |
| `post_delete` | `ThreadAccess` | Reindex thread |

Every enqueue is wrapped in `transaction.on_commit(...)`. A rolled-back
transaction must not push a phantom reindex onto the coalescing buffer or
a delete enqueue for a row that still exists.

### Coalescing buffers (default path)

Outside a `ThreadReindexDeferrer.defer()` scope, signal handlers call
`enqueue_thread_reindex(thread_id)` or `enqueue_thread_delete(thread_id)`
(see `src/backend/core/services/search/coalescer.py`). Two pending sets
are tracked:

- `search:pending_reindex_threads` — thread IDs that need their
  documents rebuilt from the DB.
- `search:pending_delete_threads` — thread IDs whose documents (parent +
  child messages) must be removed from the index.

Storage is chosen at runtime from `CACHES['default']['BACKEND']`:

- **Redis backend** (`django_redis`, the production path) — Uses native
  Redis **sets** via `SADD` for dedup and drains atomically with `SPOP
  count=N` (Redis ≥ 3.2). Concurrent enqueues are race-free across
  workers and hosts;
- **Fallback backend** (LocMem in tests, FileBasedCache, …) — Stores a
  serialized Python `set` under each key via the standard
  `cache.get`/`cache.set` API. Read-modify-write is not atomic: concurrent
  writers may drop IDs. Because reindex is idempotent and fires on every
  save, a later write on the affected thread can repair the stale index;
  otherwise a manual/full reindex may be needed. This path is
  intended for tests and single-process dev deployments; multi-worker
  production should stick to Redis.

Common to both paths:

- Drained by `process_pending_reindex_task`, scheduled every
  `SEARCH_REINDEX_TASKS_INTERVAL` seconds by Celery Beat.
- The task drains the delete set first and hands IDs to
  `bulk_delete_threads_task`. It then drains the reindex set, filters out
  any ID already picked up by the delete pass (the delete wins), and
  hands the rest to `bulk_reindex_threads_task`. Filtering the reindex
  batch is what absorbs the cascade on thread deletes: a child `Message`
  `post_delete` still schedules a reindex of its parent, but when the
  parent is also being removed that reindex is dropped before enqueuing.
- Drained IDs are pushed back to their pending set if the Celery broker
  rejects either bulk task, so a transient broker outage cannot silently
  desync the index.

Each drain pulls up to `DEFAULT_FLUSH_BATCH_SIZE` (`10_000`) IDs and
enqueues one bulk task per chunk, so a single beat tick clears the whole
backlog instead of spreading it across several
`SEARCH_REINDEX_TASKS_INTERVAL` cycles. A safety cap
(`DEFAULT_FLUSH_MAX_BATCHES`, `10`) bounds how many bulk tasks a single
cycle can enqueue in total (shared across delete and reindex handoffs) so
beat never spends too long on one tick if the backlog ballooned (e.g. a
long broker outage); any overflow drains on the next tick.

### Scoped deferrer (bulk flows)

Importers open a `ThreadReindexDeferrer.defer()` context (see
`src/backend/core/utils.py`). Inside the scope, signal handlers collect
thread IDs in a `ContextVar`-backed set instead of pushing to the pending
set. On the outermost scope exit, a single `bulk_reindex_threads_task` is
enqueued for all collected threads.

Used by:
- `core/services/importer/mbox_tasks.py`
- `core/services/importer/eml_tasks.py`
- `core/services/importer/imap_tasks.py`
- `core/services/importer/pst_tasks.py`

This bypasses the pending-set round-trip and avoids Celery saturation when
delivering thousands of inbound messages in a single job. It composes with
`ThreadStatsUpdateDeferrer`, which batches `Thread.update_stats()` calls on
the same principle.

### Deletes

Deletes reuse the coalescing/beat cycle rather than scheduling a task per
row:

- `post_delete` on `Thread` calls `enqueue_thread_delete(thread_id)`,
  which `SADD`s into `search:pending_delete_threads`.
- `post_delete` on `Message` calls `_schedule_thread_reindex(thread_id)`.
  A reindex pass upserts every message still in the DB and a
  `delete_by_query` with `must_not.ids` sweeps the orphans left behind
  (see `_purge_orphan_docs` in `index.py`).
- `process_pending_reindex_task` drains the delete set first, hands the
  IDs to `bulk_delete_threads_task` (which issues a single
  `delete_by_query` on `terms: {thread_id: [...]}` to sweep the thread
  parent and its message children in one request), then drains the
  reindex set while skipping any ID already queued for deletion in the
  same cycle.

Both bulk tasks retry transient OpenSearch connection failures with
exponential backoff (`retry_backoff`, `retry_backoff_max=600`,
`max_retries=5`).

## Bulk Indexation

`reindex_bulk_threads(threads_qs, progress_callback=None)` in
`src/backend/core/services/search/index.py` is the shared implementation used
by the scheduled drains, the management command, and the deferrer:

- Prefetches `accesses`, `messages → sender`, and `messages → recipients →
  contact` in one pass to avoid N+1 queries.
- Iterates threads with `iterator(chunk_size=BULK_CHUNK_SIZE)`
  (`BULK_CHUNK_SIZE = 100`) to cap memory usage on large result sets.
- Hands actions to `opensearchpy.helpers.bulk` with
  `request_timeout=OPENSEARCH_BULK_TIMEOUT`,
  `max_chunk_bytes=OPENSEARCH_BULK_MAX_BYTES`, `max_retries=3`,
  `initial_backoff=2`, and `raise_on_error=False` (errors are collected and
  logged but do not abort the whole reindex).
- After each bulk chunk, `_purge_orphan_docs` runs one `delete_by_query`
  scoped to `terms: {thread_id: [batch]}` + `must_not.ids: [indexed]` to
  sweep any message document still in the index whose DB row is gone.
  On a clean reindex the query matches zero docs and returns in a few ms.
  This is what lets message deletes skip a dedicated delete task: the
  next reindex of the parent thread tidies up.

The `max_chunk_bytes` threshold is a **batching** threshold, not a per-document
cap: `opensearch-py` flushes the accumulated payload once it exceeds the
threshold. A single oversized document is still sent as its own sub-chunk,
which is why the server-side `http.max_content_length` must stay well above
this value.

### Unitary helpers

`index_message`, `index_thread` and `update_thread_mailbox_flags` use the
non-bulk `es.index` API. They are used by the per-thread management command
path and some fallback code paths but are **not** on the hot write path —
signal-driven updates always go through the bulk task.

## Operational Commands

All commands live under `src/backend/core/management/commands/` and run via
`python manage.py <command>` inside the backend container.

| Command | Purpose |
|---------|---------|
| `search_index_create` | Create the index if it does not exist. Idempotent. |
| `search_index_delete [--force]` | Delete the index. Prompts for confirmation unless `--force` is given. |
| `search_reindex --all [--async] [--recreate-index]` | Reindex every thread. Streams progress by chunk when run synchronously. |
| `search_reindex --mailbox <uuid> [--async]` | Reindex all threads visible to one mailbox. |
| `search_reindex --thread <uuid> [--async]` | Reindex a single thread and its messages. |

`--async` dispatches the work to Celery and returns the task ID; without it,
the command runs inline in the backend container and prints progress.

`--recreate-index` deletes and re-creates the index before reindexing. Use it
when the mapping in `mapping.py` has changed.

Makefile shortcut:

```bash
# Drop the index, recreate it with the current mapping, and reindex
# everything synchronously in the backend container.
make search-index
```

## Celery Queue and Scheduling

All search tasks are routed to the `reindex` queue (see
`docs/worker.md`). The `reindex` queue has the **lowest priority**: it never
competes with inbound/outbound email processing.

| Task | Trigger | Queue |
|------|---------|-------|
| `process_pending_reindex_task` | Celery Beat every `SEARCH_REINDEX_TASKS_INTERVAL` seconds | `reindex` (scheduled) |
| `bulk_reindex_threads_task` | Deferrer scope exit or beat drain | `reindex` |
| `bulk_delete_threads_task` | Beat drain of the delete set | `reindex` |
| `index_message_task`, `reindex_thread_task`, `reindex_mailbox_task`, `reindex_all` | Management command (`--async`) | `reindex` |
| `update_threads_mailbox_flags_task` | Legacy callers (see note below) | `reindex` |
| `reset_search_index` | Manual invocation | `reindex` |

## Failure Modes

### Redis outage

The coalescing buffer and the Celery broker both rely on Redis (typically
the same instance). A Redis outage has the following effects:

- **Signal-driven enqueues** — `enqueue_thread_reindex` /
  `enqueue_thread_delete` catch `redis.exceptions.RedisError` and log
  `Redis unavailable while enqueuing thread …` at `ERROR`, then drop the
  ID. The originating DB write still commits: the enqueue runs in a
  `transaction.on_commit` hook with broad error handling so it never
  fails the request. **The dropped ID is not retried automatically.**
- **Beat drain** — `process_pending_reindex_task` cannot fire while the
  broker is unavailable. When Beat resumes, IDs already present in the
  Redis sets before the outage drain normally — provided Redis was
  configured with persistence (AOF/RDB). Without it, a Redis restart
  empties the pending sets.
- **`_drain_batch` failure mid-cycle** — A Redis error during `SPOP` logs
  `Redis unavailable while draining pending set …` and aborts the cycle
  early. IDs still in the set are preserved and retried on the next tick.
- **Scoped deferrer flush** — `ThreadReindexDeferrer._flush` falls back to
  `enqueue_thread_reindex` when `bulk_reindex_threads_task.delay()`
  raises. When Redis backs both the cache and the broker, both paths
  fail: IDs collected during the import are lost.

### Recovery

Once Redis is back up, the index is stale for any thread modified during
the outage that was not re-saved afterwards. Two options, in order of
cost:

```bash
# Targeted — reindex one mailbox (cheaper if the impact scope is known).
python manage.py search_reindex --mailbox <mailbox-uuid> --async

# Full — rebuild the whole index (use after a long outage or when the
# scope of stale threads is unknown).
python manage.py search_reindex --all --async
```

The `Redis unavailable while …` log lines emitted between the start of
the outage and Beat's first successful tick after recovery identify the
thread IDs that need replaying. Plumbing them through Grafana via
`prometheus-client` is on the roadmap; until then, log search is the
authoritative trail.

## Configuration

All settings live in `src/backend/messages/settings.py` (`Base` class) and
are sourced from environment variables. See `docs/env.md` for the full
table; the indexation-specific variables are:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENSEARCH_URL` | `["http://opensearch:9200"]` | OpenSearch hosts list. |
| `OPENSEARCH_TIMEOUT` | `20` | Timeout (seconds) for unitary requests. |
| `OPENSEARCH_BULK_TIMEOUT` | `60` | Timeout (seconds) for bulk calls. Raise it if full reindex hits timeouts on large payloads. |
| `OPENSEARCH_BULK_MAX_BYTES` | `52428800` (50 MiB) | Flush threshold (bytes) for bulk payloads. Keep well under the server `http.max_content_length`. |
| `OPENSEARCH_INDEX_THREADS` | `True` | Master switch. When `False`, all signal handlers, bulk tasks and delete tasks short-circuit. |
| `OPENSEARCH_CA_CERTS` | `None` | Path to a CA bundle for TLS verification. |
| `SEARCH_REINDEX_TASKS_INTERVAL` | `30` | Seconds between Celery Beat runs of `process_pending_reindex_task`. |

Tuning guidance:

- **Staleness vs. load** — Lowering `SEARCH_REINDEX_TASKS_INTERVAL` makes
  search results reflect recent writes faster but triggers more
  `bulk_reindex_threads_task` and `bulk_delete_threads_task` runs. Raising
  it is cheap if users tolerate a few minutes of lag for freshly changed
  threads.
- **Large payloads** — If `helpers.bulk` fails on full reindex, lower
  `OPENSEARCH_BULK_MAX_BYTES` before raising `OPENSEARCH_BULK_TIMEOUT`:
  smaller chunks fail less often than longer timeouts on a hot server.

## Data Flow Summary

```text
     post_save / post_delete
              │
              ▼
  ┌──────────────────────────┐      ┌────────────────────────────┐
  │  defer() scope active?   │──yes→│ ThreadReindexDeferrer.set  │
  └──────────────────────────┘      └────────────┬───────────────┘
              │ no                               │ on scope exit
              ▼                                  ▼
   transaction.on_commit                bulk_reindex_threads_task
              │                                  │
              ▼                                  ▼
  enqueue_thread_reindex / _delete      ┌───────────────────────┐
    (SADD on Redis, or                  │ reindex_bulk_threads │
     cache.set on fallback)             │  upsert + purge       │
              │                         │  orphan docs          │
              │ every N seconds         └───────────┬───────────┘
              ▼                                     │
   process_pending_reindex_task                     ▼
      (Celery Beat)                            OpenSearch index
              │                                (messages)
              ▼                                     ▲
      drain delete set → bulk_delete_threads_task   │
      drain reindex set (minus delete IDs)          │
        → bulk_reindex_threads_task ────────────────┘
```

## Related Files

- `src/backend/core/services/search/index.py` — Bulk reindex, unitary index helpers, client singleton.
- `src/backend/core/services/search/tasks.py` — Celery task wrappers.
- `src/backend/core/services/search/coalescer.py` — Coalescing buffer (Redis SADD/SPOP or Django-cache fallback) and flush.
- `src/backend/core/services/search/mapping.py` — Index name and mapping.
- `src/backend/core/signals.py` — All `post_save` / `post_delete` handlers.
- `src/backend/core/utils.py` — `ThreadReindexDeferrer`, `ThreadStatsUpdateDeferrer`, `BatchingDeferrer` base class.
- `src/backend/core/management/commands/search_reindex.py` — Reindex CLI.
- `src/backend/messages/celery_app.py` — Beat schedule entry.
