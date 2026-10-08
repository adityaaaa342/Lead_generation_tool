"""Unit tests for the scoring node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from leadpilot.models import (
    ICP,
    EnrichedLead,
    ICPScores,
    ScoredLead,
)
from leadpilot.nodes.score import (
    ReasonResponse,
    _lead_to_summary,
    score,
    score_lead,
)


class TestICPScores:
    """Tests for ICPScores model."""

    def test_total_calculation(self):
        scores = ICPScores(
            industry_score=18,
            size_score=15,
            location_score=20,
            role_score=12,
            signal_score=16,
        )
        assert scores.total == 81

    def test_min_scores(self):
        scores = ICPScores(
            industry_score=0,
            size_score=0,
            location_score=0,
            role_score=0,
            signal_score=0,
        )
        assert scores.total == 0

    def test_max_scores(self):
        scores = ICPScores(
            industry_score=20,
            size_score=20,
            location_score=20,
            role_score=20,
            signal_score=20,
        )
        assert scores.total == 100

    def test_score_bounds_validation(self):
        """Scores above 20 should be rejected."""
        with pytest.raises(Exception):
            ICPScores(
                industry_score=25,
                size_score=15,
                location_score=20,
                role_score=12,
                signal_score=16,
            )

    def test_negative_score_rejected(self):
        with pytest.raises(Exception):
            ICPScores(
                industry_score=-1,
                size_score=15,
                location_score=20,
                role_score=12,
                signal_score=16,
            )


class TestLeadToSummary:
    """Tests for lead summary generation."""

    def test_converts_enriched_lead(self, sample_enriched_lead):
        summary = _lead_to_summary(sample_enriched_lead)
        assert summary["company_name"] == "Acme Corp"
        assert summary["industry"] == "SaaS / Cloud Infrastructure"
        assert summary["size_guess"] == "50-100"
        assert "Kubernetes" in summary["technologies"]

    def test_handles_none_fields(self):
        lead = EnrichedLead(company_name="Minimal Corp")
        summary = _lead_to_summary(lead)
        assert summary["company_name"] == "Minimal Corp"
        assert summary["industry"] is None
        assert summary["location"] is None


class TestScoreLead:
    """Tests for single lead scoring (rule-based)."""

    def test_scores_deterministically(self, sample_icp, sample_enriched_lead):
        """score_lead should return a deterministic score without an LLM."""
        scored = score_lead(sample_enriched_lead, sample_icp)

        assert isinstance(scored, ScoredLead)
        assert 0 <= scored.total_score <= 100
        assert scored.company_name == "Acme Corp"
        assert "industry=" in scored.reason
        assert "location=" in scored.reason

    def test_llm_argument_ignored(self, sample_icp, sample_enriched_lead):
        """Passing an llm argument should not affect the score (it is ignored)."""
        mock_llm = MagicMock()
        mock_llm.complete_json.side_effect = Exception("should not be called")

        scored = score_lead(sample_enriched_lead, sample_icp, llm=mock_llm)

        mock_llm.complete_json.assert_not_called()
        assert 0 <= scored.total_score <= 100

    def test_good_lead_scores_high(self, sample_icp, sample_enriched_lead):
        """A lead matching industry, location, size, and keywords should score >= 60."""
        scored = score_lead(sample_enriched_lead, sample_icp)
        assert scored.total_score >= 60, f"Expected >=60, got {scored.total_score}"

    def test_empty_lead_scores_low(self, sample_icp):
        """A lead with no data should score low."""
        empty_lead = EnrichedLead(company_name="Ghost Co")
        scored = score_lead(empty_lead, sample_icp)
        assert scored.total_score <= 40, f"Expected <=40, got {scored.total_score}"

    def test_graceful_reason_failure(self, sample_icp, sample_enriched_lead):
        """score_lead should never raise — the reason field is always a string."""
        scored = score_lead(sample_enriched_lead, sample_icp)
        assert isinstance(scored.reason, str)
        assert len(scored.reason) > 0


class TestScoreNode:
    """Tests for the full score node."""

    def test_scores_all_leads(self, sample_icp, sample_enriched_lead):
        state = {
            "enriched_leads": [sample_enriched_lead, sample_enriched_lead],
            "icp": sample_icp,
            "errors": [],
        }

        result = score(state)
        assert len(result["scored_leads"]) == 2
        assert result["scored_leads"][0].total_score == result["scored_leads"][1].total_score

    def test_sorts_by_score_descending(self, sample_icp):
        """Leads with more matching data should rank above sparse leads."""
        rich_lead = EnrichedLead(
            company_name="High Score Co",
            industry="SaaS",
            location="Bangalore, India",
            size_guess="50-100",
            description="cloud devops kubernetes automation",
            product_description="DevOps platform",
            contact_email="info@highscore.com",
        )
        sparse_lead = EnrichedLead(company_name="Low Score Co")

        result = score(
            {"enriched_leads": [sparse_lead, rich_lead], "icp": sample_icp, "errors": []}
        )

        assert result["scored_leads"][0].company_name == "High Score Co"
        assert result["scored_leads"][0].total_score > result["scored_leads"][1].total_score

    def test_handles_scoring_error_gracefully(self, sample_icp, sample_enriched_lead):
        """If an internal scorer raises unexpectedly, lead gets 0 score, no crash."""
        from unittest.mock import patch as mock_patch

        with mock_patch(
            "leadpilot.nodes.score._score_industry",
            side_effect=RuntimeError("unexpected failure"),
        ):
            state = {
                "enriched_leads": [sample_enriched_lead],
                "icp": sample_icp,
                "errors": [],
            }
            result = score(state)

        assert len(result["scored_leads"]) == 1
        assert result["scored_leads"][0].total_score == 0
        assert len(result["errors"]) > 0

