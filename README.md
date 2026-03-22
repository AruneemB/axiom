<p align="center">
  <img src="favicon.svg" width="80" alt="Axiom logo">
</p>

# Axiom

A serverless pipeline that monitors quantitative finance research, synthesizes actionable trading ideas using LLMs, and delivers them daily via Telegram.

Zero infrastructure. Near-zero cost. High signal.

## Stack

- **Runtime**: Vercel (Python serverless functions)
- **Database**: Neon Postgres + pgvector
- **LLM**: OpenRouter (Gemini Flash / Claude Haiku)
- **Delivery**: Telegram Bot API
- **Cost**: ~$0.04/month

## How it works

1. Fetches new papers from arXiv daily
2. Filters through keyword matching and embedding similarity
3. Synthesizes novel research ideas via LLM
4. Applies quality and deduplication gates
5. Delivers high-signal ideas to authorized users on Telegram
6. Learns from feedback to personalize over time

## Deploy Your Own

See **[INSTRUCTIONS.md](INSTRUCTIONS.md)** for a step-by-step guide to deploying your own instance of Axiom.

---

*Built to find the signal.*
