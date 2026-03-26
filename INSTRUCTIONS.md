# Deploy Your Own Axiom

This guide walks you through deploying your own instance of Axiom from scratch. By the end you'll have a fully automated pipeline fetching papers, synthesizing ideas, and delivering them to your Telegram daily.

**Prerequisites**: Python 3.11+, Node.js (for Vercel CLI), a Telegram account.

---

## 1. Create a Telegram Bot

1. Open Telegram and message [`@BotFather`](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to name your bot
3. Save the bot token — this becomes your `TELEGRAM_BOT_TOKEN`
4. Message [`@userinfobot`](https://t.me/userinfobot) to find your own `user_id` — you'll need this for `TELEGRAM_CHAT_IDS` and the database seed step below

## 2. Set Up the Database

1. Create a free project at [neon.tech](https://neon.tech)
2. Copy the connection string from Settings > Connection Details — this becomes your `DATABASE_URL`
3. Run the migrations in order (via the Neon SQL Editor or `psql`):

```bash
psql $DATABASE_URL -f migrations/001_initial_schema.sql
psql $DATABASE_URL -f migrations/002_add_pgvector.sql
psql $DATABASE_URL -f migrations/003_add_topic_weights.sql
psql $DATABASE_URL -f migrations/004_update_vector_dimensions.sql
```

4. Seed the default topic weights:

```sql
INSERT INTO topic_weights (topic) VALUES
  ('factor model'), ('momentum'), ('volatility forecasting'),
  ('order book'), ('regime detection'), ('mean reversion'),
  ('cross-sectional'), ('alpha decay'), ('market microstructure'),
  ('alternative data'), ('options pricing'), ('liquidity'),
  ('machine learning'), ('neural network'), ('reinforcement learning');
```

5. Insert yourself as an authorized user:

```sql
INSERT INTO allowed_users (user_id, username, first_name)
VALUES (YOUR_USER_ID, 'yourusername', 'YourName');
```

Replace `YOUR_USER_ID` with the numeric ID from step 1.4.

## 3. Create an OpenRouter Account

1. Sign up at [openrouter.ai](https://openrouter.ai)
2. Generate an API key — this becomes your `OPENROUTER_API_KEY`

The default models (Gemini Flash weekdays, Claude Haiku Fridays) cost fractions of a cent per day. No prepaid credits are needed for low-volume usage.

## 4. Generate Secrets

Generate three random strings for authentication. Each should be 40+ characters:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Run this three times to produce values for:

| Variable | Purpose |
|---|---|
| `TELEGRAM_WEBHOOK_SECRET` | Verifies incoming Telegram webhook requests |
| `BOT_PASSWORD` | Password new users send via `/start` to gain access |
| `CRON_SECRET` | Authenticates cron requests via `Authorization: Bearer` header (Vercel cron) or `?key=` query parameter (manual) |

## 5. Deploy to Vercel

1. Install the Vercel CLI:

```bash
npm i -g vercel
```

2. From the project root, link the project:

```bash
vercel
```

3. Add every environment variable from `.env.example`. You can do this via the Vercel dashboard (Settings > Environment Variables) or the CLI:

```bash
vercel env add TELEGRAM_BOT_TOKEN
vercel env add TELEGRAM_WEBHOOK_SECRET
vercel env add TELEGRAM_CHAT_IDS
vercel env add BOT_PASSWORD
vercel env add DATABASE_URL
vercel env add OPENROUTER_API_KEY
vercel env add DEFAULT_MODEL
vercel env add DEEPDIVE_MODEL
vercel env add DEEPDIVE_DAY
vercel env add CRON_SECRET
vercel env add ARXIV_CATEGORIES
vercel env add ARXIV_MAX_RESULTS
vercel env add ALLOWED_TOPICS
vercel env add RELEVANCE_THRESHOLD
vercel env add QUALITY_GATE_MIN
vercel env add DEDUP_SIMILARITY_MAX
vercel env add MAX_IDEAS_PER_DAY
```

Refer to `.env.example` for descriptions and sensible defaults for each variable.

4. Deploy:

```bash
vercel --prod
```

5. Note your production URL (e.g. `https://axiom-xyz.vercel.app`)

## 6. Register the Telegram Webhook

Point Telegram at your deployed endpoint:

```bash
python scripts/register_webhook.py \
  --bot-token "$TELEGRAM_BOT_TOKEN" \
  --webhook-url "https://your-project.vercel.app/api/telegram" \
  --secret "$TELEGRAM_WEBHOOK_SECRET"
```

Verify it's set correctly:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

You should see your URL in the `url` field and `has_custom_certificate: false`.

## 7. Seed the Relevance Corpus

The embedding similarity filter needs reference papers to score against. Pick 10-20 arXiv paper IDs that represent the kind of quantitative finance research you care about.

First, install dependencies locally:

```bash
pip install -r requirements.txt
```

Then run the seed script:

```bash
python scripts/seed_corpus.py \
  --papers "2305.xxxxx,2401.xxxxx,2312.xxxxx" \
  --database-url "$DATABASE_URL" \
  --openrouter-api-key "$OPENROUTER_API_KEY"
```

Replace the IDs with real arXiv papers. Good candidates: foundational papers on momentum, factor models, volatility, or whatever topics match your `ALLOWED_TOPICS`.

## 8. Cron Jobs

Vercel's built-in cron scheduler handles both daily triggers automatically — see the `crons` section in `vercel.json`. Vercel sends an `Authorization: Bearer <CRON_SECRET>` header on each invocation, so no manual cron service is needed.

| Job | Path | Schedule |
|---|---|---|
| Fetch | `/api/fetch` | `0 6 * * *` (06:00 UTC) |
| Deliver | `/api/deliver` | `0 8 * * *` (08:00 UTC) |

If you prefer an external cron service (e.g. [cron-job.org](https://cron-job.org)), use the `?key=` query parameter instead:

```
https://your-project.vercel.app/api/fetch?key=YOUR_CRON_SECRET
```

## 9. Smoke Test

Trigger the fetch endpoint manually (either method works):

```bash
# Using Bearer header
curl -H "Authorization: Bearer YOUR_CRON_SECRET" "https://your-project.vercel.app/api/fetch"

# Using query parameter
curl "https://your-project.vercel.app/api/fetch?key=YOUR_CRON_SECRET"
```

Check that papers landed in the database:

```sql
SELECT id, title, relevance_score FROM papers ORDER BY fetched_at DESC LIMIT 5;
```

Trigger the deliver endpoint:

```bash
curl -H "Authorization: Bearer YOUR_CRON_SECRET" "https://your-project.vercel.app/api/deliver"
```

Your first idea should arrive in Telegram within 30 seconds.

## 10. View the Dashboard

Axiom includes a public landing page and dashboard to monitor its status:

- **Dashboard**: `https://your-project.vercel.app/`
- **Features**: Live status check, paper/idea counts, a streaming ticker of monitored quant topics, and an expandable recent papers drawer.
- **Papers drawer**: Click the Papers count to reveal the 20 most recent papers with arXiv links, category badges, and relative timestamps. The drawer lazy-loads from `/api/papers` on first open.
- **Customization**: Edit `public/status.js` or `public/style.css` to further personalize the visual experience.

---

## Customization

### Topics

Edit `ALLOWED_TOPICS` and `ARXIV_CATEGORIES` in your environment variables to shift Axiom's focus. The `ALLOWED_TOPICS` list drives keyword pre-filtering, while `ARXIV_CATEGORIES` controls which arXiv feeds are polled. After changing topics, re-seed topic weights in the database and consider updating your seed corpus.

### Models

Change `DEFAULT_MODEL` and `DEEPDIVE_MODEL` to any model available on OpenRouter. `DEEPDIVE_DAY` controls which day of the week uses the deeper model (0=Monday through 6=Sunday, default 4=Friday).

### Thresholds

- `RELEVANCE_THRESHOLD` (default 0.65) — raise to be more selective, lower to see more papers
- `QUALITY_GATE_MIN` (default 13) — minimum combined novelty + feasibility score (out of 20)
- `DEDUP_SIMILARITY_MAX` (default 0.80) — how similar a new idea can be to a previously sent one
- `MAX_IDEAS_PER_DAY` (default 2) — cap on daily idea delivery

### Monitoring

Run these queries against your Neon database to monitor health:

```sql
-- Papers fetched in the last 7 days
SELECT DATE(fetched_at), COUNT(*), AVG(relevance_score)::NUMERIC(4,2)
FROM papers
WHERE fetched_at > NOW() - INTERVAL '7 days'
GROUP BY 1 ORDER BY 1 DESC;

-- Ideas sent in the last 30 days
SELECT COUNT(*), AVG(novelty_score)::NUMERIC(3,1), AVG(feasibility_score)::NUMERIC(3,1)
FROM ideas
WHERE sent_at > NOW() - INTERVAL '30 days';

-- Feedback ratio
SELECT
  SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) AS likes,
  SUM(CASE WHEN feedback = -1 THEN 1 ELSE 0 END) AS dislikes
FROM idea_feedback;
```
