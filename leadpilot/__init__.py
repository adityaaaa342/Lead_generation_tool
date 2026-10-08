"""LeadPilot AI — Autonomous Lead Discovery, Enrichment & ICP Scoring Pipeline."""

from leadpilot.config import Settings, get_settings
from leadpilot.graph import build_graph, run_pipeline
from leadpilot.models import (
    ICP,
    CleanLead,
    CollectionPlan,
    EmailResult,
    EmailStatus,
    EnrichedLead,
    FieldProvenance,
    ICPScores,
    PipelineState,
    RawLead,
    ScoredLead,
)

__version__ = "0.2.0"

__all__ = [
    "ICP",
    "CleanLead",
    "CollectionPlan",
    "EmailResult",
    "EmailStatus",
    "EnrichedLead",
    "FieldProvenance",
    "ICPScores",
    "PipelineState",
    "RawLead",
    "ScoredLead",
    "Settings",
    "build_graph",
    "get_settings",
    "run_pipeline",
]
