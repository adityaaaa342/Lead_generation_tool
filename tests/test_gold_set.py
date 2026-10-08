"""Pytest tests that use the gold set to verify pipeline accuracy.

These tests construct synthetic pipeline output and verify the evaluation
logic works correctly.  When run against real pipeline output, they provide
regression guardrails.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.evaluate_accuracy import (
    EvalReport,
    GoldLead,
    evaluate,
    find_best_match,
    load_gold_set,
    _domain_matches,
    _location_matches,
    _industry_overlaps,
)


class TestDomainMatching:
    """Tests for domain comparison logic."""

    def test_exact_match(self):
        assert _domain_matches("example.com", "example.com")

    def test_www_prefix_ignored(self):
        assert _domain_matches("example.com", "www.example.com")

    def test_protocol_ignored(self):
        assert _domain_matches("example.com", "https://example.com")

    def test_trailing_slash_ignored(self):
        assert _domain_matches("example.com", "example.com/")

    def test_different_domains(self):
        assert not _domain_matches("example.com", "other.com")

    def test_none_handling(self):
        assert not _domain_matches(None, "example.com")
        assert not _domain_matches("example.com", None)
        assert not _domain_matches(None, None)

    def test_empty_handling(self):
        assert not _domain_matches("", "example.com")
        assert not _domain_matches("example.com", "")


class TestLocationMatching:
    """Tests for location comparison logic."""

    def test_city_in_full_location(self):
        assert _location_matches("Nagpur, India", "nagpur, maharashtra, india")

    def test_city_only(self):
        assert _location_matches("Nagpur", "nagpur")

    def test_different_cities(self):
        assert not _location_matches("Nagpur, India", "Mumbai, India")

    def test_none_handling(self):
        assert not _location_matches(None, "Nagpur")
        assert not _location_matches("Nagpur", None)


class TestIndustryOverlap:
    """Tests for industry matching logic."""

    def test_keyword_present(self):
        assert _industry_overlaps(
            "Food & Beverage / Restaurant",
            "restaurant / dining"
        )

    def test_partial_match(self):
        assert _industry_overlaps("Cafe / Coffee", "coffee shop")

    def test_no_overlap(self):
        assert not _industry_overlaps("Fitness / Gym", "software / saas")

    def test_none_handling(self):
        assert not _industry_overlaps(None, "restaurant")
        assert not _industry_overlaps("restaurant", None)


class TestFindBestMatch:
    """Tests for fuzzy company name matching."""

    def test_exact_match(self):
        df = pd.DataFrame({"Company": ["Haldiram's Nagpur", "Other Co"]})
        idx, score = find_best_match("Haldiram's Nagpur", df)
        assert idx == 0
        assert score >= 85

    def test_substring_match(self):
        df = pd.DataFrame({"Company": ["Cafe Coffee Day (Nagpur)", "Other"]})
        idx, score = find_best_match("Cafe Coffee Day", df)
        assert idx == 0
        assert score >= 85

    def test_no_match(self):
        df = pd.DataFrame({"Company": ["Completely Different Name"]})
        idx, score = find_best_match("Haldiram's Nagpur", df)
        assert idx is None
        assert score == 0


class TestEvaluate:
    """Integration tests for the evaluate function."""

    def test_perfect_pipeline(self):
        """A pipeline that returns all gold-set entries correctly should score 100%."""
        gold = [
            GoldLead(
                company_name="Acme Corp",
                domain="acme.com",
                location="Nagpur, India",
                industry="Software / SaaS",
                has_website=True,
            ),
        ]
        df = pd.DataFrame([{
            "Company": "Acme Corp",
            "Domain": "acme.com",
            "Location": "Nagpur, India",
            "Industry": "SaaS / Cloud",
            "Website": "https://acme.com",
        }])

        report = evaluate(df, gold)
        assert report.match_rate == 1.0
        assert report.domain_accuracy == 1.0
        assert report.location_accuracy == 1.0
        assert report.industry_accuracy == 1.0
        assert report.hallucinations == 0

    def test_hallucination_detected(self):
        """Pipeline inventing a website for a company that has none → hallucination."""
        gold = [
            GoldLead(
                company_name="Small Local Shop",
                has_website=False,
            ),
        ]
        df = pd.DataFrame([{
            "Company": "Small Local Shop",
            "Domain": "smalllocalshop.com",  # hallucinated!
            "Location": "",
            "Industry": "",
            "Website": "https://smalllocalshop.com",
        }])

        report = evaluate(df, gold)
        assert report.hallucinations == 1
        assert report.hallucination_rate > 0

    def test_null_correctness(self):
        """Pipeline correctly returning empty for a company with no website."""
        gold = [
            GoldLead(
                company_name="Small Local Shop",
                has_website=False,
            ),
        ]
        df = pd.DataFrame([{
            "Company": "Small Local Shop",
            "Domain": "",
            "Location": "",
            "Industry": "",
            "Website": "",
        }])

        report = evaluate(df, gold)
        assert report.null_correct == 1
        assert report.hallucinations == 0

    def test_missing_lead_lowers_match_rate(self):
        """Gold entry not found in pipeline → reduces match rate."""
        gold = [
            GoldLead(company_name="Found Co"),
            GoldLead(company_name="Missing Co"),
        ]
        df = pd.DataFrame([{
            "Company": "Found Co",
            "Domain": "",
            "Location": "",
            "Industry": "",
            "Website": "",
        }])

        report = evaluate(df, gold)
        assert report.match_rate == 0.5
        assert report.matched_count == 1

    def test_wrong_domain_detected(self):
        """Pipeline returning wrong domain → domain_accuracy < 100%."""
        gold = [
            GoldLead(
                company_name="Test Corp",
                domain="testcorp.com",
            ),
        ]
        df = pd.DataFrame([{
            "Company": "Test Corp",
            "Domain": "wrong-domain.com",
            "Location": "",
            "Industry": "",
            "Website": "",
        }])

        report = evaluate(df, gold)
        assert report.domain_accuracy == 0.0
        assert report.domain_correct == 0

    def test_report_summary_renders(self):
        """The summary string should render without errors."""
        gold = [GoldLead(company_name="Test Co", domain="test.com")]
        df = pd.DataFrame([{
            "Company": "Test Co", "Domain": "test.com",
            "Location": "", "Industry": "", "Website": "",
        }])
        report = evaluate(df, gold)
        summary = report.summary()
        assert "Accuracy Report" in summary
        assert "Match rate" in summary


class TestGoldSetLoads:
    """Verify the gold_set.csv file is valid and loadable."""

    def test_loads_without_error(self):
        gold = load_gold_set()
        assert len(gold) >= 15, f"Gold set too small: {len(gold)} entries"

    def test_all_entries_have_names(self):
        gold = load_gold_set()
        for entry in gold:
            assert entry.company_name, f"Empty company name in gold set"

    def test_has_nagpur_entries(self):
        gold = load_gold_set()
        nagpur_entries = [g for g in gold if g.location and "nagpur" in g.location.lower()]
        assert len(nagpur_entries) >= 10, "Gold set should have ≥10 Nagpur entries"

    def test_has_no_website_entries(self):
        gold = load_gold_set()
        no_web = [g for g in gold if not g.has_website]
        assert len(no_web) >= 1, "Gold set should have ≥1 has_website=FALSE entry"
