"""Integration test — run the full pipeline with mocked collectors."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from leadpilot.models import (
    ICP,
    CollectionPlan,
    ICPScores,
    RawLead,
    SourceConfig,
)
from leadpilot.nodes.score import ReasonResponse


MOCK_LEADS = [
    RawLead(
        company_name="TechStartup Alpha",
        domain="techstartup-alpha.com",
        website_url="https://techstartup-alpha.com",
        emails=["hello@techstartup-alpha.com"],
        description="AI-powered DevOps automation",
        location="Bangalore, India",
        source_name="directory_collector",
        source_url="https://tie.org/members",
    ),
    RawLead(
        company_name="CloudBeta Inc",
        domain="cloudbeta.io",
        website_url="https://cloudbeta.io",
        emails=["info@cloudbeta.io"],
        description="Multi-cloud infrastructure",
        location="Mumbai, India",
        source_name="github_collector",
        source_url="https://github.com/cloudbeta",
    ),
]


class TestPipelineIntegration:
    """Integration tests with mocked external dependencies."""

    @patch("leadpilot.graph.HTTPClient")
    @patch("leadpilot.graph.LLMClient")
    def test_build_graph_compiles(self, mock_llm_cls, mock_http_cls):
        """The graph should compile without errors."""
        from leadpilot.graph import build_graph
        graph = build_graph()
        assert graph is not None

    def test_pipeline_state_initialization(self):
        """Pipeline state should be properly initialized."""
        from leadpilot.models import PipelineState

        state = PipelineState(
            brief="We sell DevOps tools to startups",
            limit=10,
        )
        assert state.brief == "We sell DevOps tools to startups"
        assert state.limit == 10
        assert state.icp is None
        assert state.scored_leads == []
