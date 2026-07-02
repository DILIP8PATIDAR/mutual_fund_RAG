"""Tests for the Phase 3 input guard: length + PII detection."""

from src.rag.guard import (
    MAX_MESSAGE_CHARS,
    check_input,
    detect_pii,
)


def test_empty_message_rejected():
    result = check_input("  ")
    assert result.ok is False
    assert "enter a question" in result.message.lower()


def test_overlong_message_rejected():
    result = check_input("x" * (MAX_MESSAGE_CHARS + 1))
    assert result.ok is False
    assert "too long" in result.message.lower()


def test_plain_factual_message_passes():
    result = check_input("What is the expense ratio of HDFC Mid Cap Fund?")
    assert result.ok is True
    assert result.pii_types == ()


def test_pan_detected_and_blocked():
    assert "pan" in detect_pii("My PAN is ABCDE1234F")
    result = check_input("My PAN is ABCDE1234F, tell me about HDFC Mid Cap")
    assert result.ok is False
    assert "pan" in result.pii_types


def test_aadhaar_detected():
    assert "aadhaar" in detect_pii("Aadhaar 1234 5678 9012")
    assert "aadhaar" in detect_pii("aadhaar 123456789012")


def test_phone_detected():
    assert "phone" in detect_pii("call me on 9876543210")
    assert "phone" in detect_pii("+91 9876543210")


def test_email_detected():
    assert "email" in detect_pii("reach me at user@example.com")


def test_otp_detected():
    assert "otp" in detect_pii("my otp is 445566")


def test_account_number_detected():
    assert "account_number" in detect_pii("account 123456789012345")


def test_clean_query_has_no_pii():
    assert detect_pii("exit load on HDFC Small Cap Fund") == []
