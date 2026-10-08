"""Node 1: ICP Builder — convert a business brief into a structured ICP."""

from __future__ import annotations

import logging
from typing import Any

from leadpilot.llm.client import LLMClient
from leadpilot.llm.prompts import icp_builder_messages
from leadpilot.models import ICP, PipelineState

logger = logging.getLogger(__name__)


def icp_builder(state: dict[str, Any], llm: LLMClient | None = None) -> dict[str, Any]:
    """LangGraph node: Build a structured ICP from the user's business brief.

    Args:
        state: Pipeline state dict containing 'brief'.
        llm: Optional LLMClient instance (created if not provided).

    Returns:
        Updated state dict with 'icp' populated.
    """
    brief = state["brief"]
    logger.info("Building ICP from brief: %s", brief[:100])

    if llm is None:
        llm = LLMClient()

    messages = icp_builder_messages(brief)
    icp = llm.complete_json(messages, response_model=ICP)

    logger.info(
        "ICP built: industries=%s, roles=%s, locations=%s",
        icp.industry,
        icp.target_roles,
        icp.locations,
    )

    return {"icp": icp}
