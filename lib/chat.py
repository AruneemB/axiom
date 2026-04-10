"""
Chat session management and LLM integration for conversational features.
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx


def get_or_create_session(user_id: int, paper_id: str | None, idea_id: int | None,
                         conn) -> int:
    """
    Find active session for user+paper+idea, or create new one.
    If paper_id/idea_id not provided, use most recent delivered idea.
    Returns session_id.
    """
    with conn.cursor() as cur:
        # If no paper/idea specified, get most recent delivered idea
        if paper_id is None or idea_id is None:
            cur.execute("""
                SELECT i.id, i.paper_id
                FROM ideas i
                JOIN deliveries d ON d.idea_id = i.id
                WHERE d.user_id = %s
                ORDER BY d.delivered_at DESC
                LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
            if row:
                idea_id = row["id"]
                paper_id = row["paper_id"]
            else:
                # No ideas delivered yet, cannot create session
                raise ValueError("No ideas available for chat")

        # Check for active session with same paper/idea
        cur.execute("""
            SELECT id
            FROM conversation_sessions
            WHERE user_id = %s
              AND paper_id = %s
              AND idea_id = %s
              AND expires_at > NOW()
            ORDER BY updated_at DESC
            LIMIT 1
        """, (user_id, paper_id, idea_id))

        row = cur.fetchone()
        if row:
            return row["id"]

        # Create new session
        cur.execute("""
            INSERT INTO conversation_sessions (user_id, paper_id, idea_id)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (user_id, paper_id, idea_id))
        conn.commit()
        return cur.fetchone()["id"]


def get_conversation_context(session_id: int, limit: int, conn) -> dict:
    """
    Retrieve paper metadata, idea details, and last N messages.
    Returns dict ready for LLM prompt formatting.
    """
    with conn.cursor() as cur:
        # Get session details with paper and idea
        cur.execute("""
            SELECT
                cs.id, cs.paper_id, cs.idea_id,
                p.title, p.abstract,
                i.hypothesis, i.method, i.dataset,
                i.novelty_score, i.feasibility_score
            FROM conversation_sessions cs
            JOIN papers p ON p.id = cs.paper_id
            JOIN ideas i ON i.id = cs.idea_id
            WHERE cs.id = %s
        """, (session_id,))

        session = cur.fetchone()
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Get last N messages
        cur.execute("""
            SELECT role, content
            FROM conversation_messages
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (session_id, limit))

        messages = cur.fetchall()
        # Reverse to chronological order
        messages.reverse()

    return {
        "session_id": session["id"],
        "paper_id": session["paper_id"],
        "idea_id": session["idea_id"],
        "title": session["title"],
        "abstract": session["abstract"],
        "hypothesis": session["hypothesis"],
        "method": session["method"],
        "dataset": session["dataset"],
        "novelty_score": session["novelty_score"],
        "feasibility_score": session["feasibility_score"],
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages]
    }


def store_message(session_id: int, role: str, content: str,
                 tokens_used: int, conn) -> int:
    """
    Persist message to database, update session timestamps and counts.
    Returns message_id.
    """
    with conn.cursor() as cur:
        # Insert message
        cur.execute("""
            INSERT INTO conversation_messages (session_id, role, content, tokens_used)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (session_id, role, content, tokens_used))

        message_id = cur.fetchone()["id"]

        # Update session
        cur.execute("""
            UPDATE conversation_sessions
            SET message_count = message_count + 1,
                updated_at = NOW(),
                expires_at = NOW() + INTERVAL '2 hours'
            WHERE id = %s
        """, (session_id,))

        conn.commit()
        return message_id


def generate_chat_response(context: dict, user_message: str,
                          model: str, api_key: str, timeout: int) -> tuple[str, int]:
    """
    Call OpenRouter API with context + new user message.
    Returns (response_text, tokens_used).
    """
    # Load system prompt template
    with open("prompts/chat_system.txt", "r", encoding="utf-8") as f:
        system_template = f.read()

    # Format system prompt
    system_prompt = system_template.format(
        title=context["title"],
        abstract=context["abstract"],
        hypothesis=context["hypothesis"],
        method=context["method"],
        dataset=context["dataset"],
        novelty_score=context["novelty_score"],
        feasibility_score=context["feasibility_score"]
    )

    # Build messages array
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(context["messages"])
    messages.append({"role": "user", "content": user_message})

    # Call OpenRouter API
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages
    }

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        data = response.json()

    response_text = data["choices"][0]["message"]["content"]
    tokens_used = data.get("usage", {}).get("total_tokens", 0)

    return response_text, tokens_used


def check_rate_limits(user_id: int, session_id: int | None, conn) -> tuple[bool, str]:
    """
    Multi-tier rate limiting:
    1. Session-level: max 20 messages per session
    2. User-level: max 5 active sessions
    3. Hourly: max 20 messages per hour
    4. Daily: max 50k tokens per day
    """
    with conn.cursor() as cur:
        # Check session message count
        if session_id:
            cur.execute("SELECT message_count FROM conversation_sessions WHERE id = %s",
                       (session_id,))
            row = cur.fetchone()
            if row and row["message_count"] >= 20:
                return False, "Session message limit reached (20/20). Start a new session."

        # Check active sessions count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM conversation_sessions
            WHERE user_id = %s AND expires_at > NOW()
        """, (user_id,))
        if cur.fetchone()["count"] >= 5:
            return False, "Too many active sessions (5 max). Wait for sessions to expire."

        # Check hourly message count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM conversation_messages cm
            JOIN conversation_sessions cs ON cm.session_id = cs.id
            WHERE cs.user_id = %s
              AND cm.created_at > NOW() - INTERVAL '1 hour'
              AND cm.role = 'user'
        """, (user_id,))
        if cur.fetchone()["count"] >= 20:
            return False, "Hourly message limit reached (20/hour). Please wait."

        # Check daily token budget
        cur.execute("""
            SELECT COALESCE(SUM(tokens_used), 0) as total
            FROM conversation_messages cm
            JOIN conversation_sessions cs ON cm.session_id = cs.id
            WHERE cs.user_id = %s
              AND cm.created_at > NOW() - INTERVAL '24 hours'
        """, (user_id,))
        if cur.fetchone()["total"] >= 50000:
            return False, "Daily token budget exceeded. Resets in 24 hours."

    return True, ""


def cleanup_expired_sessions(conn):
    """
    Delete sessions where expires_at < NOW().
    Called by cron job every 6 hours.
    """
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM conversation_sessions
            WHERE expires_at < NOW()
        """)
        deleted_count = cur.rowcount
        conn.commit()

    return deleted_count
