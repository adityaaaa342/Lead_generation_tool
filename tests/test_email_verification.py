"""Unit tests for email verification — syntax, MX, patterns, catch-all."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from leadpilot.models import EmailStatus, EnrichedLead
from leadpilot.nodes.email_finder import (
    validate_email_syntax,
    generate_email_patterns,
    verify_email,
    find_emails_for_lead,
    get_mx_records,
    detect_catchall,
)


class TestEmailSyntax:
    """Tests for email syntax validation."""

    def test_valid_email(self):
        assert validate_email_syntax("user@example.com") is True

    def test_valid_with_dots(self):
        assert validate_email_syntax("first.last@example.com") is True

    def test_valid_with_plus(self):
        assert validate_email_syntax("user+tag@example.com") is True

    def test_invalid_no_at(self):
        assert validate_email_syntax("userexample.com") is False

    def test_invalid_no_domain(self):
        assert validate_email_syntax("user@") is False

    def test_invalid_no_tld(self):
        assert validate_email_syntax("user@example") is False

    def test_invalid_spaces(self):
        assert validate_email_syntax("user @example.com") is False

    def test_empty_string(self):
        assert validate_email_syntax("") is False


class TestEmailPatterns:
    """Tests for email pattern generation."""

    def test_full_name(self):
        patterns = generate_email_patterns("John Smith", "example.com")
        assert "john.smith@example.com" in patterns
        assert "john@example.com" in patterns
        assert "jsmith@example.com" in patterns

    def test_single_name(self):
        patterns = generate_email_patterns("John", "example.com")
        assert "john@example.com" in patterns
        assert "info@example.com" in patterns

    def test_empty_name(self):
        patterns = generate_email_patterns("", "example.com")
        assert patterns == []

    def test_none_name(self):
        patterns = generate_email_patterns(None, "example.com")
        assert patterns == []

    def test_none_domain(self):
        patterns = generate_email_patterns("John Smith", "")
        assert patterns == []

    def test_name_with_comma(self):
        patterns = generate_email_patterns("Smith, John", "example.com")
        assert "smith.john@example.com" in patterns

    def test_includes_generic_patterns(self):
        patterns = generate_email_patterns("John Smith", "example.com")
        assert "info@example.com" in patterns
        assert "contact@example.com" in patterns


class TestVerifyEmail:
    """Tests for full email verification (with mocked DNS/SMTP)."""

    def test_invalid_syntax_rejected(self):
        result = verify_email("not-an-email")
        assert result.status == EmailStatus.INVALID
        assert result.method == "syntax_check"

    @patch("leadpilot.nodes.email_finder.get_mx_records")
    def test_no_mx_returns_unknown(self, mock_mx):
        mock_mx.return_value = []
        result = verify_email("user@nonexistent-domain-xyz.com")
        assert result.status == EmailStatus.UNKNOWN

    @patch("leadpilot.nodes.email_finder.detect_catchall")
    @patch("leadpilot.nodes.email_finder.check_smtp_rcpt")
    @patch("leadpilot.nodes.email_finder.get_mx_records")
    def test_valid_email_flow(self, mock_mx, mock_smtp, mock_catchall):
        mock_mx.return_value = ["mx.example.com"]
        mock_smtp.return_value = "valid"
        mock_catchall.return_value = False

        result = verify_email("user@example.com")
        assert result.status == EmailStatus.VALID
        assert result.is_catchall is False

    @patch("leadpilot.nodes.email_finder.detect_catchall")
    @patch("leadpilot.nodes.email_finder.check_smtp_rcpt")
    @patch("leadpilot.nodes.email_finder.get_mx_records")
    def test_catchall_marks_risky(self, mock_mx, mock_smtp, mock_catchall):
        mock_mx.return_value = ["mx.example.com"]
        mock_smtp.return_value = "valid"
        mock_catchall.return_value = True

        result = verify_email("user@example.com")
        assert result.status == EmailStatus.RISKY
        assert result.is_catchall is True

    @patch("leadpilot.nodes.email_finder.detect_catchall")
    @patch("leadpilot.nodes.email_finder.check_smtp_rcpt")
    @patch("leadpilot.nodes.email_finder.get_mx_records")
    def test_smtp_invalid(self, mock_mx, mock_smtp, mock_catchall):
        mock_mx.return_value = ["mx.example.com"]
        mock_smtp.return_value = "invalid"
        mock_catchall.return_value = False

        result = verify_email("user@example.com")
        assert result.status == EmailStatus.INVALID

    def test_skip_smtp(self):
        """When skip_smtp=True, should not try SMTP."""
        with patch("leadpilot.nodes.email_finder.get_mx_records") as mock_mx:
            mock_mx.return_value = ["mx.example.com"]
            with patch("leadpilot.nodes.email_finder.detect_catchall") as mock_catchall:
                mock_catchall.return_value = False
                result = verify_email("user@example.com", skip_smtp=True)
                assert result.status == EmailStatus.UNKNOWN
                assert result.method == "mx_only"


class TestFindEmailsForLead:
    """Tests for email discovery for a lead."""

    @patch("leadpilot.nodes.email_finder.verify_email")
    @patch("leadpilot.nodes.email_finder.get_mx_records")
    def test_finds_from_contact_email(self, mock_mx, mock_verify):
        mock_mx.return_value = ["mx.acme.com"]
        mock_verify.return_value = MagicMock(
            email="raj@acme.com",
            status=EmailStatus.VALID,
        )

        lead = EnrichedLead(
            company_name="Acme",
            domain="acme.com",
            contact_email="raj@acme.com",
        )
        results = find_emails_for_lead(lead)
        assert len(results) >= 1

    @patch("leadpilot.nodes.email_finder.verify_email")
    @patch("leadpilot.nodes.email_finder.get_mx_records")
    def test_generates_patterns_from_founder(self, mock_mx, mock_verify):
        mock_mx.return_value = ["mx.acme.com"]
        mock_verify.return_value = MagicMock(
            email="raj.kumar@acme.com",
            status=EmailStatus.UNKNOWN,
        )

        lead = EnrichedLead(
            company_name="Acme",
            domain="acme.com",
            founder_name="Raj Kumar",
        )
        results = find_emails_for_lead(lead, skip_personal=False)
        assert len(results) >= 1

    @patch("leadpilot.nodes.email_finder.verify_email")
    @patch("leadpilot.nodes.email_finder.get_mx_records")
    def test_skip_personal_uses_generic(self, mock_mx, mock_verify):
        mock_mx.return_value = ["mx.acme.com"]
        mock_verify.return_value = MagicMock(
            email="info@acme.com",
            status=EmailStatus.VALID,
        )

        lead = EnrichedLead(
            company_name="Acme",
            domain="acme.com",
            founder_name="Raj Kumar",
        )
        results = find_emails_for_lead(lead, skip_personal=True)
        # Should not include personal patterns
        emails_checked = [r.email for r in results]
        assert "raj.kumar@acme.com" not in emails_checked
