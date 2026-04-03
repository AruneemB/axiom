# Topic Weights Auto-Sync Feature

## Problem

The topic weights feedback system was silently failing because:

1. Papers store `keyword_hits` based on topics from `ALLOWED_TOPICS` env var
2. Feedback updates match keywords against `topic_weights.topic` column
3. If these don't match, the UPDATE query affects 0 rows silently
4. User feedback is recorded but weights never change from default 1.00

## Root Cause

- **ALLOWED_TOPICS** had: "neural sde", "diffusion models", "stochastic control", etc.
- **topic_weights** only had: "factor model", "momentum", "machine learning", etc.
- Almost no overlap = feedback never updated weights

## Solution

Implemented automatic syncing of `topic_weights` with `ALLOWED_TOPICS`:

### Files Created

1. **scripts/sync_topics.py** - Standalone script and reusable function
   - Ensures all topics from ALLOWED_TOPICS exist in topic_weights
   - Uses `INSERT ... ON CONFLICT DO NOTHING` for idempotency
   - Lowercases and strips topics to match filter behavior
   - Returns stats: inserted count and total count

2. **tests/test_sync_topics.py** - Comprehensive test coverage
   - Tests insertion, lowercasing, conflict handling, commits
   - 6 test cases, all passing

3. **scripts/sync_topic_weights.sql** - SQL script for manual sync
   - Pre-populates all current ALLOWED_TOPICS values
   - Can be run with: `psql $DATABASE_URL -f scripts/sync_topic_weights.sql`

4. **scripts/diagnose_topic_weights.sql** - Diagnostic queries
   - Check feedback counts, keyword_hits population
   - Identify mismatches between keywords and topic_weights

### Files Modified

1. **api/fetch.py**
   - Added import: `from scripts.sync_topics import sync_topic_weights`
   - Added call before processing papers: `sync_topic_weights(conn, cfg.allowed_topics)`
   - Now auto-syncs on every fetch run

2. **api/spark.py**
   - Added import: `from scripts.sync_topics import sync_topic_weights`
   - Added call after connection: `sync_topic_weights(conn, cfg.allowed_topics)`
   - Now auto-syncs when /spark command is used

3. **INSTRUCTIONS.md**
   - Updated step 4 to explain auto-sync behavior
   - Noted that manual seeding is now optional
   - Documented how to run sync_topics.py standalone

4. **MEMORY.md**
   - Added Topic Weights System section
   - Documented the exact-match requirement
   - Noted auto-sync implementation

## How It Works

```
┌─────────────────┐
│ ALLOWED_TOPICS  │ (env var)
│ e.g., "neural   │
│ sde,diffusion   │
│ models,..."     │
└────────┬────────┘
         │
         ├─> RelevanceFilter lowercases topics
         │
         ├─> Matches against paper abstracts
         │
         └─> Populates papers.keyword_hits
                    │
                    │
    ┌───────────────▼────────────────┐
    │ sync_topic_weights()           │
    │ Ensures topic_weights has all  │
    │ topics from ALLOWED_TOPICS     │
    └───────────────┬────────────────┘
                    │
                    ▼
         ┌──────────────────┐
         │ topic_weights    │
         │ table            │
         │ - All topics     │
         │   from config    │
         │ - Weights start  │
         │   at 1.00        │
         └──────┬───────────┘
                │
                │ Feedback UPDATE
                │ matches keyword_hits
                │ against topic column
                ▼
    Weights change based on
    user thumbs up/down!
```

## Usage

### Automatic (Recommended)

Just use the system normally:
- Fetch cron runs → topics auto-sync → papers processed
- /spark command → topics auto-sync → idea generated
- No manual intervention needed

### Manual Sync

If you want to pre-populate before first fetch:

```bash
python scripts/sync_topics.py
```

Or run the SQL directly:

```bash
psql $DATABASE_URL -f scripts/sync_topic_weights.sql
```

### Diagnostics

If weights still aren't updating, run diagnostics:

```bash
psql $DATABASE_URL -f scripts/diagnose_topic_weights.sql
```

Check:
- Query 1: Is feedback being recorded?
- Query 2: Are keyword_hits populated on papers?
- Query 5: Do keywords match topic_weights entries?

## Testing

Run the test suite:

```bash
python -m pytest tests/test_sync_topics.py -v
```

All 6 tests should pass.

## Future Maintenance

If you change `ALLOWED_TOPICS`:
- The system will auto-sync on next fetch/spark
- Old topics remain in topic_weights (weights preserved)
- New topics are added with weight=1.00
- No action required!

## Related Issues

- Fixed: #3 (MarkdownV2 escaping in /topics command)
- Fixed: Topic weights not updating from feedback (this feature)
