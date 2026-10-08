"""Gold-set evaluator for LeadPilot pipeline accuracy.

Compares pipeline output (a leads DataFrame or Excel file) against the
hand-verified gold_set.csv and reports per-field accuracy metrics.

Usage:
    python -m tests.evaluate_accuracy [--pipeline-output leads.xlsx]
    python -m pytest tests/test_gold_set.py -v

Metrics reported:
    - Match rate:    How many gold-set companies were found in the output?
    - Domain accuracy:  Of matched leads, how many domains are correct?
    - Location accuracy: Of matched leads, how many locations mention the right city?
    - Industry accuracy: Of matched leads, does the industry tag overlap?
    - Hallucination rate: How many output leads have data where gold says it
                          shouldn't exist (e.g. website for has_website=FALSE)?
    - Null-correctness:  How often does the pipeline correctly return empty
                          instead of guessing?
"""

from __future__ import annotations

import csv
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
from thefuzz import fuzz

logger = logging.getLogger(__name__)

GOLD_SET_PATH = Path(__file__).parent / "gold_set.csv"

# Minimum fuzzy ratio to consider a company name a match
NAME_MATCH_THRESHOLD = 85


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class GoldLead:
    """A single entry from the gold set."""
    company_name: str
    domain: Optional[str] = None
    location: Optional[str] = None
    industry: Optional[str] = None
    founder_name: Optional[str] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    has_website: bool = True


@dataclass
class FieldResult:
    """Accuracy result for a single field comparison."""
    field_name: str
    gold_value: Optional[str]
    pipeline_value: Optional[str]
    correct: bool
    hallucinated: bool = False  # pipeline gave a value when gold says none exists
    empty_ok: bool = False      # pipeline correctly returned empty


@dataclass
class LeadResult:
    """Evaluation result for a single lead."""
    company_name: str
    matched: bool
    matched_to: Optional[str] = None
    match_score: int = 0
    field_results: list[FieldResult] = field(default_factory=list)


@dataclass
class EvalReport:
    """Overall evaluation report."""
    gold_count: int = 0
    pipeline_count: int = 0
    matched_count: int = 0
    lead_results: list[LeadResult] = field(default_factory=list)

    # Aggregate metrics
    domain_correct: int = 0
    domain_total: int = 0
    location_correct: int = 0
    location_total: int = 0
    industry_correct: int = 0
    industry_total: int = 0
    hallucinations: int = 0
    null_correct: int = 0
    null_total: int = 0

    @property
    def match_rate(self) -> float:
        return self.matched_count / self.gold_count if self.gold_count else 0.0

    @property
    def domain_accuracy(self) -> float:
        return self.domain_correct / self.domain_total if self.domain_total else 0.0

    @property
    def location_accuracy(self) -> float:
        return self.location_correct / self.location_total if self.location_total else 0.0

    @property
    def industry_accuracy(self) -> float:
        return self.industry_correct / self.industry_total if self.industry_total else 0.0

    @property
    def hallucination_rate(self) -> float:
        return self.hallucinations / self.pipeline_count if self.pipeline_count else 0.0

    @property
    def null_correctness(self) -> float:
        return self.null_correct / self.null_total if self.null_total else 0.0

    def summary(self) -> str:
        """Return a human-readable summary of the evaluation."""
        lines = [
            "=" * 60,
            "  LeadPilot Accuracy Report — Gold Set Evaluation",
            "=" * 60,
            "",
            f"  Gold set entries:         {self.gold_count}",
            f"  Pipeline output leads:    {self.pipeline_count}",
            f"  Matched (found in output):{self.matched_count}",
            f"  Match rate:               {self.match_rate:.1%}",
            "",
            "  Per-field accuracy (of matched leads):",
            f"    Domain:    {self.domain_correct}/{self.domain_total} = {self.domain_accuracy:.1%}",
            f"    Location:  {self.location_correct}/{self.location_total} = {self.location_accuracy:.1%}",
            f"    Industry:  {self.industry_correct}/{self.industry_total} = {self.industry_accuracy:.1%}",
            "",
            f"  Hallucinations detected:  {self.hallucinations}",
            f"  Hallucination rate:       {self.hallucination_rate:.1%}",
            f"  Null-correctness:         {self.null_correct}/{self.null_total} = {self.null_correctness:.1%}",
            "",
        ]

        # Show per-lead details
        if self.lead_results:
            lines.append("  Per-lead details:")
            lines.append("  " + "-" * 56)
            for lr in self.lead_results:
                status = "✓ MATCHED" if lr.matched else "✗ MISSING"
                matched_info = f" → '{lr.matched_to}' ({lr.match_score}%)" if lr.matched else ""
                lines.append(f"    {status}: {lr.company_name}{matched_info}")
                for fr in lr.field_results:
                    if fr.hallucinated:
                        lines.append(f"      ⚠ {fr.field_name}: HALLUCINATED '{fr.pipeline_value}'")
                    elif fr.correct:
                        lines.append(f"      ✓ {fr.field_name}: correct")
                    elif fr.empty_ok:
                        lines.append(f"      ✓ {fr.field_name}: correctly empty")
                    else:
                        lines.append(
                            f"      ✗ {fr.field_name}: expected '{fr.gold_value}' "
                            f"got '{fr.pipeline_value}'"
                        )
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)


# ── Loading ──────────────────────────────────────────────────────────────────

def load_gold_set(path: Path = GOLD_SET_PATH) -> list[GoldLead]:
    """Load the gold set from a CSV file."""
    leads = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(GoldLead(
                company_name=row["company_name"].strip(),
                domain=row.get("domain", "").strip() or None,
                location=row.get("location", "").strip() or None,
                industry=row.get("industry", "").strip() or None,
                founder_name=row.get("founder_name", "").strip() or None,
                contact_email=row.get("contact_email", "").strip() or None,
                phone=row.get("phone", "").strip() or None,
                has_website=row.get("has_website", "TRUE").strip().upper() == "TRUE",
            ))
    return leads


def load_pipeline_output(path: Path) -> pd.DataFrame:
    """Load pipeline output from an Excel or CSV file."""
    if path.suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    elif path.suffix == ".csv":
        return pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}")


# ── Matching ─────────────────────────────────────────────────────────────────

def _normalize(text: str | None) -> str:
    """Lowercase and strip for comparison."""
    if not text:
        return ""
    return text.strip().lower()


def _domain_matches(gold_domain: str | None, pipeline_domain: str | None) -> bool:
    """Check if two domains match (ignoring www. and trailing slashes)."""
    g = _normalize(gold_domain)
    p = _normalize(pipeline_domain)
    if not g or not p:
        return False
    # Strip common prefixes
    for prefix in ("https://", "http://", "www."):
        if g.startswith(prefix):
            g = g[len(prefix):]
        if p.startswith(prefix):
            p = p[len(prefix):]
    return g.rstrip("/") == p.rstrip("/")


def _location_matches(gold_loc: str | None, pipeline_loc: str | None) -> bool:
    """Check if the pipeline location contains the key city from the gold set."""
    g = _normalize(gold_loc)
    p = _normalize(pipeline_loc)
    if not g or not p:
        return False
    # Extract the city (first part before comma)
    gold_city = g.split(",")[0].strip()
    return gold_city in p


def _industry_overlaps(gold_ind: str | None, pipeline_ind: str | None) -> bool:
    """Check if any keyword from the gold industry appears in the pipeline industry."""
    g = _normalize(gold_ind)
    p = _normalize(pipeline_ind)
    if not g or not p:
        return False
    # Split gold industry into keywords (e.g. "Food & Beverage / Restaurant")
    keywords = [k.strip() for k in g.replace("/", " ").replace("&", " ").split() if len(k.strip()) > 2]
    return any(kw in p for kw in keywords)


def find_best_match(
    gold_name: str, pipeline_df: pd.DataFrame, name_col: str = "Company"
) -> tuple[Optional[int], int]:
    """Find the best fuzzy match for a gold company name in the pipeline output.

    Returns (row_index, match_score). Returns (None, 0) if no match >= threshold.
    """
    best_idx = None
    best_score = 0
    gold_norm = _normalize(gold_name)

    for idx, row in pipeline_df.iterrows():
        pipe_name = _normalize(str(row.get(name_col, "")))
        if not pipe_name:
            continue

        # Try exact substring first
        if gold_norm in pipe_name or pipe_name in gold_norm:
            score = 95
        else:
            score = fuzz.token_sort_ratio(gold_norm, pipe_name)

        if score > best_score:
            best_score = score
            best_idx = idx

    if best_score >= NAME_MATCH_THRESHOLD:
        return best_idx, best_score
    return None, 0


# ── Evaluation ───────────────────────────────────────────────────────────────

def evaluate(
    pipeline_df: pd.DataFrame,
    gold_set: list[GoldLead] | None = None,
    name_col: str = "Company",
    domain_col: str = "Domain",
    location_col: str = "Location",
    industry_col: str = "Industry",
    website_col: str = "Website",
) -> EvalReport:
    """Evaluate pipeline output against the gold set.

    Args:
        pipeline_df: DataFrame of pipeline output (from leads_to_dataframe or Excel).
        gold_set:    List of GoldLead entries. If None, loads from default CSV.
        name_col:    Column name for company name in the pipeline output.

    Returns:
        EvalReport with all metrics computed.
    """
    if gold_set is None:
        gold_set = load_gold_set()

    report = EvalReport(
        gold_count=len(gold_set),
        pipeline_count=len(pipeline_df),
    )

    for gold in gold_set:
        match_idx, match_score = find_best_match(gold.company_name, pipeline_df, name_col)

        if match_idx is None:
            report.lead_results.append(LeadResult(
                company_name=gold.company_name,
                matched=False,
            ))
            continue

        # Matched
        report.matched_count += 1
        row = pipeline_df.iloc[match_idx]
        lr = LeadResult(
            company_name=gold.company_name,
            matched=True,
            matched_to=str(row.get(name_col, "")),
            match_score=match_score,
        )

        # ── Domain check ─────────────────────────────────────────────
        if gold.domain:
            report.domain_total += 1
            pipe_domain = str(row.get(domain_col, "")) if pd.notna(row.get(domain_col)) else ""
            correct = _domain_matches(gold.domain, pipe_domain)
            if correct:
                report.domain_correct += 1
            lr.field_results.append(FieldResult(
                field_name="domain",
                gold_value=gold.domain,
                pipeline_value=pipe_domain,
                correct=correct,
            ))

        # ── Location check ───────────────────────────────────────────
        if gold.location:
            report.location_total += 1
            pipe_loc = str(row.get(location_col, "")) if pd.notna(row.get(location_col)) else ""
            correct = _location_matches(gold.location, pipe_loc)
            if correct:
                report.location_correct += 1
            lr.field_results.append(FieldResult(
                field_name="location",
                gold_value=gold.location,
                pipeline_value=pipe_loc,
                correct=correct,
            ))

        # ── Industry check ───────────────────────────────────────────
        if gold.industry:
            report.industry_total += 1
            pipe_ind = str(row.get(industry_col, "")) if pd.notna(row.get(industry_col)) else ""
            correct = _industry_overlaps(gold.industry, pipe_ind)
            if correct:
                report.industry_correct += 1
            lr.field_results.append(FieldResult(
                field_name="industry",
                gold_value=gold.industry,
                pipeline_value=pipe_ind,
                correct=correct,
            ))

        # ── Hallucination check (website for has_website=FALSE) ──────
        if not gold.has_website:
            report.null_total += 1
            pipe_website = str(row.get(website_col, "")) if pd.notna(row.get(website_col)) else ""
            pipe_domain = str(row.get(domain_col, "")) if pd.notna(row.get(domain_col)) else ""
            if pipe_website or pipe_domain:
                report.hallucinations += 1
                lr.field_results.append(FieldResult(
                    field_name="website",
                    gold_value=None,
                    pipeline_value=pipe_website or pipe_domain,
                    correct=False,
                    hallucinated=True,
                ))
            else:
                report.null_correct += 1
                lr.field_results.append(FieldResult(
                    field_name="website",
                    gold_value=None,
                    pipeline_value="",
                    correct=True,
                    empty_ok=True,
                ))

        report.lead_results.append(lr)

    return report


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    """Run evaluation from the command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate LeadPilot pipeline accuracy")
    parser.add_argument(
        "--pipeline-output", "-p",
        type=Path,
        required=True,
        help="Path to the pipeline output file (Excel or CSV)",
    )
    parser.add_argument(
        "--gold-set", "-g",
        type=Path,
        default=GOLD_SET_PATH,
        help="Path to the gold set CSV (default: tests/gold_set.csv)",
    )
    args = parser.parse_args()

    df = load_pipeline_output(args.pipeline_output)
    gold = load_gold_set(args.gold_set)
    report = evaluate(df, gold)
    print(report.summary())

    # Exit with non-zero if accuracy is below thresholds
    if report.match_rate < 0.5:
        print("\n⚠ FAIL: Match rate below 50%")
        sys.exit(1)
    if report.domain_accuracy < 0.6:
        print("\n⚠ FAIL: Domain accuracy below 60%")
        sys.exit(1)


if __name__ == "__main__":
    main()
