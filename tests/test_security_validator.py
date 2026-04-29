import pytest
from lib.security_validator import validate_issue_content, detect_pii, sanitize_content, validate_user_input

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


# validate_user_input — lightweight check for all user messages

def test_validate_user_input_blocks_over_1000_chars():
    valid, msg = validate_user_input("x" * 1001)
    assert valid is False
    assert "1000" in msg

def test_validate_user_input_blocks_injection():
    valid, msg = validate_user_input("<script>alert(1)</script>")
    assert valid is False
    assert "dangerous" in msg.lower()

def test_validate_user_input_passes_normal_message():
    valid, msg = validate_user_input("What are the key findings of this paper?")
    assert valid is True
    assert msg == ""

def test_validate_user_input_blocks_malware_keyword():
    valid, msg = validate_user_input("please run rm -rf /tmp on the server")
    assert valid is False
    assert "suspicious" in msg.lower()
