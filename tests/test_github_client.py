import pytest
from lib.github_client import generate_issue_title, format_issue_body

def test_generate_issue_title_short_sentence():
    title = "This is a short title"
    assert generate_issue_title(title) == title

def test_generate_issue_title_truncates_long():
    long_desc = "A" * 100
    title = generate_issue_title(long_desc)
    assert len(title) == 70
    assert title.endswith("...")

def test_format_issue_body_includes_user_info():
    description = "Something is wrong"
    user_info = {"username": "testuser", "user_id": 123, "timestamp": "2023-01-01"}
    body = format_issue_body(description, None, user_info)
    assert "testuser" in body
    assert "123" in body
    assert "2023-01-01" in body

def test_format_issue_body_includes_paper_context():
    description = "Something is wrong"
    context = {"paper_id": "2401.00001", "title": "Paper Title"}
    body = format_issue_body(description, context, {"username": "u", "user_id": 1, "timestamp": "t"})
    assert "2401.00001" in body
    assert "arxiv.org/abs/2401.00001" in body
