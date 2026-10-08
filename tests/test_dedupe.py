"""Unit tests for clean_dedupe node — domain normalization, fuzzy matching, merge."""

from __future__ import annotations

import pytest

from leadpilot.models import RawLead
from leadpilot.nodes.clean_dedupe import (
    are_duplicates,
    clean_dedupe,
    merge_leads,
    normalize_company_name,
    normalize_domain,
)


class TestNormalizeDomain:
    """Tests for domain normalization."""

    def test_basic_domain(self):
        assert normalize_domain("example.com") == "example.com"

    def test_strips_protocol(self):
        assert normalize_domain("https://example.com") == "example.com"
        assert normalize_domain("http://example.com") == "example.com"

    def test_strips_www(self):
        assert normalize_domain("www.example.com") == "example.com"

    def test_strips_trailing_slash(self):
        assert normalize_domain("example.com/") == "example.com"

    def test_lowercases(self):
        assert normalize_domain("Example.COM") == "example.com"

    def test_full_url(self):
        assert normalize_domain("https://www.Example.COM/") == "example.com"

    def test_none_input(self):
        assert normalize_domain(None) is None

    def test_empty_string(self):
        assert normalize_domain("") is None

    def test_whitespace(self):
        assert normalize_domain("  example.com  ") == "example.com"


class TestNormalizeCompanyName:
    """Tests for company name normalization."""

    def test_lowercase(self):
        assert normalize_company_name("Acme") == "acme"

    def test_strips_corp(self):
        assert normalize_company_name("Acme Corp") == "acme"

    def test_strips_inc(self):
        assert normalize_company_name("Acme Inc.") == "acme"

    def test_strips_pvt_ltd(self):
        assert normalize_company_name("Gamma Technologies Pvt. Ltd.") == "gamma"

    def test_strips_solutions(self):
        assert normalize_company_name("DataSoft Solutions") == "datasoft"

    def test_strips_technologies(self):
        assert normalize_company_name("Gamma Technologies") == "gamma"

    def test_special_chars(self):
        assert normalize_company_name("Acme & Co.") == "acme"

    def test_whitespace(self):
        assert normalize_company_name("  Acme  Corp  ") == "acme"


class TestAreDuplicates:
    """Tests for duplicate detection."""

    def test_same_domain(self):
        a = RawLead(
            company_name="Acme", domain="acme.com",
            source_name="test", source_url="http://test.com",
        )
        b = RawLead(
            company_name="Different Name", domain="acme.com",
            source_name="test", source_url="http://test.com",
        )
        assert are_duplicates(a, b) is True

    def test_different_domain(self):
        a = RawLead(
            company_name="Acme", domain="acme.com",
            source_name="test", source_url="http://test.com",
        )
        b = RawLead(
            company_name="Beta", domain="beta.com",
            source_name="test", source_url="http://test.com",
        )
        assert are_duplicates(a, b) is False

    def test_fuzzy_name_match(self):
        a = RawLead(
            company_name="Acme Corporation",
            source_name="test", source_url="http://test.com",
        )
        b = RawLead(
            company_name="ACME Corp",
            source_name="test", source_url="http://test.com",
        )
        assert are_duplicates(a, b) is True

    def test_email_domain_match(self):
        a = RawLead(
            company_name="Company A", emails=["info@shared.com"],
            source_name="test", source_url="http://test.com",
        )
        b = RawLead(
            company_name="Company B", emails=["contact@shared.com"],
            source_name="test", source_url="http://test.com",
        )
        assert are_duplicates(a, b) is True

    def test_no_match(self):
        a = RawLead(
            company_name="Alpha Inc", domain="alpha.com",
            emails=["a@alpha.com"],
            source_name="test", source_url="http://test.com",
        )
        b = RawLead(
            company_name="Omega Ltd", domain="omega.com",
            emails=["b@omega.com"],
            source_name="test", source_url="http://test.com",
        )
        assert are_duplicates(a, b) is False


class TestMergeLeads:
    """Tests for merging duplicate leads."""

    def test_merge_combines_emails(self):
        leads = [
            RawLead(
                company_name="Acme", domain="acme.com",
                emails=["a@acme.com"],
                source_name="src1", source_url="http://src1.com",
            ),
            RawLead(
                company_name="Acme Corp", domain="acme.com",
                emails=["b@acme.com"],
                source_name="src2", source_url="http://src2.com",
            ),
        ]
        merged = merge_leads(leads)
        assert set(merged.emails) == {"a@acme.com", "b@acme.com"}

    def test_merge_preserves_best_name(self):
        leads = [
            RawLead(
                company_name="Acme", domain="acme.com",
                source_name="src1", source_url="http://src1.com",
            ),
            RawLead(
                company_name="Acme Corp", domain="acme.com",
                website_url="https://acme.com",
                description="Cloud company",
                emails=["info@acme.com"],
                source_name="src2", source_url="http://src2.com",
            ),
        ]
        merged = merge_leads(leads)
        # The richer lead should be primary
        assert merged.company_name == "Acme Corp"

    def test_merge_count(self):
        leads = [
            RawLead(
                company_name="A", source_name="s", source_url="http://a.com"
            ),
            RawLead(
                company_name="A", source_name="s", source_url="http://b.com"
            ),
            RawLead(
                company_name="A", source_name="s", source_url="http://c.com"
            ),
        ]
        merged = merge_leads(leads)
        assert merged.merged_count == 3

    def test_merge_fills_missing_fields(self):
        leads = [
            RawLead(
                company_name="Acme",
                description="Cloud company",
                source_name="src1", source_url="http://src1.com",
            ),
            RawLead(
                company_name="Acme",
                domain="acme.com",
                location="India",
                source_name="src2", source_url="http://src2.com",
            ),
        ]
        merged = merge_leads(leads)
        assert merged.domain == "acme.com"
        assert merged.location == "India"
        assert merged.description == "Cloud company"


class TestCleanDedupeNode:
    """Tests for the full clean_dedupe node."""

    def test_removes_duplicates(self, sample_raw_leads):
        # sample_raw_leads has 10 leads with 2 pairs of duplicates
        result = clean_dedupe({"raw_leads": sample_raw_leads})
        clean_leads = result["clean_leads"]

        # Should merge: Acme Corp + ACME Corporation, Gamma Tech + Gamma Technologies
        assert len(clean_leads) == 8  # 10 - 2 duplicates

    def test_empty_input(self):
        result = clean_dedupe({"raw_leads": []})
        assert result["clean_leads"] == []

    def test_single_lead(self):
        leads = [
            RawLead(
                company_name="Solo",
                domain="solo.com",
                source_name="test",
                source_url="http://test.com",
            ),
        ]
        result = clean_dedupe({"raw_leads": leads})
        assert len(result["clean_leads"]) == 1
        assert result["clean_leads"][0].company_name == "Solo"

    def test_all_unique(self):
        leads = [
            RawLead(
                company_name=f"Company {i}",
                domain=f"company{i}.com",
                source_name="test",
                source_url=f"http://test{i}.com",
            )
            for i in range(5)
        ]
        result = clean_dedupe({"raw_leads": leads})
        assert len(result["clean_leads"]) == 5
