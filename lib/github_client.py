"""
GitHub API integration for issue creation and management.
"""

from github import Github, GithubException
from datetime import datetime, timezone
import json
import re


def create_issue(title: str, body: str, labels: list[str],
                assignees: list[str], repo_owner: str, repo_name: str,
                token: str) -> dict:
    """
    Create GitHub issue via API.

    Returns:
        {
            "number": 234,
            "url": "https://api.github.com/repos/owner/repo/issues/234",
            "html_url": "https://github.com/owner/repo/issues/234"
        }

    Raises:
        GithubException: On API errors (401, 403, 404, 422, 500)
    """
    try:
        g = Github(token)
        repo = g.get_repo(f"{repo_owner}/{repo_name}")

        issue = repo.create_issue(
            title=title,
            body=body,
            labels=labels,
            assignees=assignees
        )

        return {
            "number": issue.number,
            "url": issue.url,
            "html_url": issue.html_url
        }
    except GithubException as e:
        # Re-raise with context
        raise


def validate_github_token(token: str) -> tuple[bool, str]:
    """
    Verify token has required scopes and access.

    Returns:
        (is_valid, error_message)
    """
    try:
        g = Github(token)
        user = g.get_user()
        user.login  # Trigger API call

        # Check rate limit
        rate_limit = g.get_rate_limit()
        if rate_limit.core.remaining < 10:
            return False, "GitHub API rate limit low"

        return True, ""
    except Exception as e:
        return False, str(e)


def format_issue_body(user_report: str, context_data: dict | None,
                     user_info: dict) -> str:
    """
    Build markdown body for GitHub issue.

    Template:
    ---
    ## User Report

    {user_description}

    ---

    ## Context

    - **Telegram User**: {username} (ID: {user_id})
    - **Submitted**: {timestamp}
    {optional_paper_link}
    {optional_idea_reference}
    {optional_conversation_history}

    ---

    _Submitted via Axiom Telegram Bot_
    """
    body_parts = ["## User Report\n\n", user_report, "\n\n---\n\n## Context\n\n"]

    # User info
    body_parts.append(f"- **Telegram User**: {user_info.get('username', 'Unknown')} ")
    body_parts.append(f"(ID: {user_info['user_id']})\n")
    body_parts.append(f"- **Submitted**: {user_info['timestamp']}\n")

    # Optional context
    if context_data:
        if context_data.get("paper_id"):
            paper_url = f"https://arxiv.org/abs/{context_data['paper_id']}"
            body_parts.append(f"- **Related Paper**: [{context_data['paper_id']}]({paper_url})\n")

        if context_data.get("idea_id"):
            body_parts.append(f"- **Related Idea**: #{context_data['idea_id']}\n")

        if context_data.get("session_id"):
            body_parts.append(f"- **Conversation Session**: #{context_data['session_id']}\n")

    body_parts.append("\n---\n\n_Submitted via Axiom Telegram Bot_")

    return "".join(body_parts)


def generate_issue_title(description: str, max_length: int = 70) -> str:
    """
    Extract concise title from description.

    Strategy:
    1. Use first sentence if < 70 chars
    2. Otherwise, use first 67 chars + "..."
    """
    # Try first sentence
    sentences = re.split(r'[.!?]\s+', description)
    first_sentence = sentences[0].strip()

    if len(first_sentence) <= max_length:
        return first_sentence

    # Truncate
    return description[:67].strip() + "..."
