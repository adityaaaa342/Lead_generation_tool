"""Node 6: Email Finder — discover and verify email addresses."""

from __future__ import annotations

import logging
import re
import socket
import smtplib
from typing import Any

import dns.resolver
from email_validator import validate_email, EmailNotValidError

from leadpilot.config import Settings, get_settings
from leadpilot.models import EmailResult, EmailStatus, EnrichedLead

logger = logging.getLogger(__name__)


def validate_email_syntax(email: str) -> bool:
    """Check email syntax using email-validator."""
    try:
        validate_email(email, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def get_mx_records(domain: str) -> list[str]:
    """Look up MX records for a domain."""
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return sorted(
            [str(r.exchange).rstrip(".") for r in answers],
            key=lambda x: x,
        )
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
        return []


def check_smtp_rcpt(email: str, mx_host: str, timeout: int = 10) -> str:
    """Check if an email address is accepted by the SMTP server.

    Returns: 'valid', 'invalid', or 'unknown'
    """
    try:
        with smtplib.SMTP(mx_host, 25, timeout=timeout) as smtp:
            smtp.ehlo("leadpilot.local")
            code, _ = smtp.mail("verify@leadpilot.local")
            if code != 250:
                return "unknown"
            code, _ = smtp.rcpt(email)
            smtp.quit()

            if code == 250:
                return "valid"
            elif code == 550:
                return "invalid"
            else:
                return "unknown"
    except (smtplib.SMTPException, socket.error, OSError) as exc:
        logger.debug("SMTP check failed for %s via %s: %s", email, mx_host, exc)
        return "unknown"


def detect_catchall(domain: str, mx_records: list[str]) -> bool:
    """Detect if a domain has a catch-all email configuration."""
    if not mx_records:
        return False

    # Try a random address that shouldn't exist
    test_email = f"nonexistent_xyzzy_test_42@{domain}"
    result = check_smtp_rcpt(test_email, mx_records[0])
    return result == "valid"


def generate_email_patterns(
    founder_name: str | None,
    domain: str,
) -> list[str]:
    """Generate common email patterns from a person's name and domain."""
    if not founder_name or not domain:
        return []

    # Clean and split the name
    name = founder_name.strip().lower()
    parts = re.split(r"[\s,]+", name)
    parts = [p for p in parts if len(p) > 1]

    if len(parts) < 2:
        if parts:
            first = parts[0]
            return [
                f"{first}@{domain}",
                f"info@{domain}",
                f"hello@{domain}",
                f"contact@{domain}",
            ]
        return [f"info@{domain}", f"hello@{domain}", f"contact@{domain}"]

    first = parts[0]
    last = parts[-1]

    return [
        f"{first}.{last}@{domain}",       # first.last
        f"{first}@{domain}",              # first
        f"{first[0]}{last}@{domain}",     # flast
        f"{first}{last[0]}@{domain}",     # firstl
        f"{first}_{last}@{domain}",       # first_last
        f"{last}@{domain}",              # last
        f"{first[0]}.{last}@{domain}",    # f.last
        f"info@{domain}",
        f"contact@{domain}",
    ]


def verify_email(
    email: str,
    mx_records: list[str] | None = None,
    skip_smtp: bool = False,
) -> EmailResult:
    """Full email verification: syntax → MX → SMTP RCPT.

    Args:
        email: Email address to verify.
        mx_records: Pre-fetched MX records (looked up if not provided).
        skip_smtp: If True, skip SMTP RCPT check.

    Returns:
        EmailResult with status and details.
    """
    # Step 1: Syntax check
    if not validate_email_syntax(email):
        return EmailResult(
            email=email,
            status=EmailStatus.INVALID,
            method="syntax_check",
        )

    # Step 2: MX lookup
    domain = email.split("@")[1]
    if mx_records is None:
        mx_records = get_mx_records(domain)

    if not mx_records:
        return EmailResult(
            email=email,
            status=EmailStatus.UNKNOWN,
            method="mx_lookup_failed",
            mx_records=[],
        )

    # Step 3: Catch-all detection
    is_catchall = detect_catchall(domain, mx_records)

    if skip_smtp:
        return EmailResult(
            email=email,
            status=EmailStatus.RISKY if is_catchall else EmailStatus.UNKNOWN,
            is_catchall=is_catchall,
            method="mx_only",
            mx_records=mx_records,
        )

    # Step 4: SMTP RCPT check
    smtp_result = check_smtp_rcpt(email, mx_records[0])

    if smtp_result == "valid":
        status = EmailStatus.RISKY if is_catchall else EmailStatus.VALID
    elif smtp_result == "invalid":
        status = EmailStatus.INVALID
    else:
        status = EmailStatus.UNKNOWN

    return EmailResult(
        email=email,
        status=status,
        is_catchall=is_catchall,
        method="smtp_rcpt",
        mx_records=mx_records,
    )


def find_emails_for_lead(
    lead: EnrichedLead,
    skip_personal: bool = False,
) -> list[EmailResult]:
    """Find and verify emails for a single lead.

    Priority:
    1. Contact email deterministically scraped from the website
    2. Generated patterns from founder name + domain — ONLY if the
       founder name was scraped (not LLM-hallucinated)
    3. Generic patterns (info@, hello@, contact@)
    """
    results: list[EmailResult] = []
    seen_emails: set[str] = set()

    # Pre-fetch MX records for the domain
    domain = lead.domain
    mx_records: list[str] = []
    if domain:
        mx_records = get_mx_records(domain)

    # Determine provenance of key fields
    prov = getattr(lead, "field_provenance", {}) or {}
    contact_email_source = prov.get("contact_email", "unknown")
    founder_name_source = prov.get("founder_name", "unknown")

    # 1. Contact email — trust it only if scraped; still try if LLM but tag differently
    existing_emails: list[str] = []
    if lead.contact_email:
        existing_emails.append(lead.contact_email)

    # 2. Generate patterns from founder name ONLY if it was scraped (not hallucinated)
    founder_is_trusted = founder_name_source == "scraped"
    if not skip_personal and lead.founder_name and domain and founder_is_trusted:
        patterns = generate_email_patterns(lead.founder_name, domain)
        existing_emails.extend(patterns)
    elif lead.founder_name and domain and not founder_is_trusted:
        logger.info(
            "Skipping email patterns for %s — founder_name '%s' came from %s (untrusted)",
            lead.company_name, lead.founder_name, founder_name_source,
        )

    # 3. Generic patterns (always safe)
    if domain:
        for prefix in ["info", "hello", "contact", "team"]:
            existing_emails.append(f"{prefix}@{domain}")

    # Deduplicate and verify
    for email in existing_emails:
        email = email.strip().lower()
        if email in seen_emails:
            continue
        seen_emails.add(email)

        result = verify_email(email, mx_records=mx_records)
        results.append(result)

        # Stop after finding a valid email
        if result.status == EmailStatus.VALID:
            break

    return results


def email_finder(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: Find and verify email addresses for enriched leads.

    Args:
        state: Pipeline state dict containing 'enriched_leads'.

    Returns:
        Updated state dict with emails populated in enriched_leads.
    """
    enriched_leads: list[EnrichedLead] = state["enriched_leads"]
    settings = get_settings()

    logger.info("Finding emails for %d leads", len(enriched_leads))

    for i, lead in enumerate(enriched_leads):
        logger.info("Finding emails for %d/%d: %s", i + 1, len(enriched_leads), lead.company_name)

        try:
            email_results = find_emails_for_lead(
                lead,
                skip_personal=settings.skip_personal_emails,
            )
            lead.emails = email_results
        except Exception as exc:
            logger.error("Email finder failed for %s: %s", lead.company_name, exc)

    return {"enriched_leads": enriched_leads}
