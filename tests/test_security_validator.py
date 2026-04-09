import pytest
from lib.security_validator import validate_issue_content, detect_pii, sanitize_content

def test_validates_minimum_length():
    valid, msg = validate_issue_content("abc")
    assert valid is False
    assert "too short" in msg.lower()

def test_validates_maximum_length():
    valid, msg = validate_issue_content("A" * 6001)
    assert valid is False
    assert "too long" in msg.lower()

def test_detects_sql_injection():
    valid, msg = validate_issue_content("'; DROP TABLE users; --")
    assert valid is False
    assert "dangerous" in msg.lower()

def test_detects_xss():
    valid, msg = validate_issue_content("<script>alert(1)</script>")
    assert valid is False
    assert "dangerous" in msg.lower()

def test_detects_spam_caps():
    valid, msg = validate_issue_content("ALL CAPS MESSAGE IS SPAM")
    assert valid is False
    assert "spam" in msg.lower()

def test_detects_pii_email():
    pii = detect_pii("Contact me at test@example.com")
    assert "email" in pii

def test_sanitize_strips_html():
    sanitized = sanitize_content("<b>bold</b>")
    assert "bold" in sanitized
    assert "<b>" not in sanitized

def test_passes_valid_content():
    valid, msg = validate_issue_content("This is a perfectly normal user report about a bug.")
    assert valid is True
    assert msg == ""
