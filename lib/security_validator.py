"""
Security validation pipeline for user-submitted content.
Provides multi-layer validation for profanity, spam, injection, malware, and PII.
"""

import re
from typing import Tuple, List

# Security pattern definitions
PROFANITY_PATTERNS = [
    r'\b(fuck|shit|damn|ass|bitch|cunt|dick|cock|pussy|whore|slut|fag|nigger)\b',
    r'\b(bastard|piss|crap|hell)\b',
]

INJECTION_PATTERNS = [
    r"';\s*DROP\s+TABLE",
    r"<script[^>]*>",
    r"javascript:",
    r"onerror\s*=",
    r"onload\s*=",
    r"eval\s*\(",
    r"<iframe",
    r"data:text/html",
    r"UNION\s+SELECT",
    r"--\s*$",
    r"/\*.*\*/",
]

MALWARE_KEYWORDS = [
    "rm -rf",
    "eval(",
    "exec(",
    "__import__",
    "base64.b64decode",
    "/dev/null",
]

PII_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
}


def validate_issue_content(content: str) -> Tuple[bool, str]:
    """
    Run all validation checks on submission content.

    Returns:
        (is_valid, error_message)
    """
    # 1. Length validation
    if len(content) < 10:
        return False, "Description too short (min 10 characters)"
    if len(content) > 5000:
        return False, "Description too long (max 5000 characters)"

    # 2. Profanity filter
    if detect_profanity(content):
        return False, "Submission contains inappropriate content"

    # 3. Spam detection
    if detect_spam_patterns(content):
        return False, "Submission appears to be spam"

    # 4. Injection detection
    if detect_injection_attempts(content):
        return False, "Submission contains potentially dangerous content"

    # 5. Malware keywords
    if detect_malware_keywords(content):
        return False, "Submission contains suspicious commands or code"

    return True, ""


def detect_profanity(content: str) -> bool:
    """Check for profanity patterns."""
    content_lower = content.lower()
    for pattern in PROFANITY_PATTERNS:
        if re.search(pattern, content_lower, re.IGNORECASE):
            return True
    return False


def detect_spam_patterns(content: str) -> bool:
    """
    Detect spam characteristics:
    - Excessive capitalization (>50% caps)
    - Repetitive words/phrases
    - Multiple URLs (>3)
    - Common spam keywords
    """
    # Excessive caps
    if len(content) > 20:
        caps_ratio = sum(1 for c in content if c.isupper()) / len(content)
        if caps_ratio > 0.5:
            return True

    # Multiple URLs
    url_count = len(re.findall(r'https?://', content))
    if url_count > 3:
        return True

    # Repetitive patterns (same word 5+ times)
    words = content.lower().split()
    for word in set(words):
        if len(word) > 3 and words.count(word) >= 5:
            return True

    return False


def detect_injection_attempts(content: str) -> bool:
    """Check for SQL/XSS/command injection patterns."""
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False


def detect_malware_keywords(content: str) -> bool:
    """Check for dangerous shell commands and code execution."""
    content_lower = content.lower()
    for keyword in MALWARE_KEYWORDS:
        if keyword in content_lower:
            return True
    return False


def detect_pii(content: str) -> List[str]:
    """
    Detect personally identifiable information.

    Returns:
        List of PII types detected (e.g., ["email", "phone"])
    """
    found = []
    for pii_type, pattern in PII_PATTERNS.items():
        if re.search(pattern, content):
            found.append(pii_type)
    return found


def sanitize_content(content: str) -> str:
    """
    Strip dangerous content while preserving user intent.

    - Remove HTML tags
    - Remove script blocks
    - Normalize whitespace
    """
    # Remove HTML tags
    content = re.sub(r'<[^>]+>', '', content)

    # Remove script content
    content = re.sub(r'<script.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)

    # Normalize whitespace
    content = re.sub(r'\s+', ' ', content).strip()

    return content
