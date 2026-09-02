"""
Case data fetcher for USCIS.

Primary: Authenticated myUSCIS internal API (full JSON with hidden metadata).
Fallback: Public egov.uscis.gov via Selenium (Cloudflare-safe).
"""

import logging
import re
from datetime import datetime, timezone

import requests
from requests.exceptions import RequestException

import config
import auth

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# USCIS internal event code descriptions
# These are NOT shown on the public status page
# ─────────────────────────────────────────────────────────
EVENT_CODE_DESCRIPTIONS = {
    "IAF": "Initial Application Filed / Case Received",
    "FTA0": "Fingerprint Fee / Biometrics Processing",
    "FTA1": "Fingerprint Appointment Scheduled",
    "FTA2": "Fingerprint Appointment Completed",
    "BIO": "Biometrics Captured",
    "RFE": "Request for Evidence Sent",
    "RFER": "Response to RFE Received",
    "NOID": "Notice of Intent to Deny",
    "APR": "Case Approved",
    "DEN": "Case Denied",
    "TRF": "Case Transferred to Another Office",
    "PROD": "Card / Document Being Produced",
    "MAIL": "Card / Document Was Mailed",
    "DLV": "Card / Document Was Delivered",
    "ADIT": "ADIT Processing",
    "INT": "Interview Scheduled",
    "INTC": "Interview Completed",
    "WDN": "Case Withdrawn",
    "DA": "Decision on Appeal",
    "SUS": "Case Suspended",
    "REO": "Case Reopened",
}

# ─────────────────────────────────────────────────────────
# Standard headers to mimic a real browser session
# ─────────────────────────────────────────────────────────
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://my.uscis.gov/account/",
    "Origin": "https://my.uscis.gov",
}


def fetch_case_from_myuscis(receipt_number: str) -> dict | None:
    """
    Fetch detailed case data from the myUSCIS internal API.

    Returns a normalized dict with all available fields, or None on failure.
    """
    cookies = auth.get_valid_cookies()
    if not cookies:
        return None
    url = f"{config.MYUSCIS_CASE_API}{receipt_number}"

    try:
        resp = requests.get(url, cookies=cookies, headers=BROWSER_HEADERS, timeout=30)

        if resp.status_code == 401:
            logger.warning("myUSCIS API returned 401 for %s. Clearing invalid session cookies.", receipt_number)
            auth.clear_cookies()
            return None

        if resp.status_code != 200:
            logger.error(
                "myUSCIS API returned %d for %s", resp.status_code, receipt_number
            )
            return None

        raw_response = resp.json()
        return _normalize_myuscis_response(receipt_number, raw_response)

    except RequestException as e:
        logger.error("Request failed for %s: %s", receipt_number, e)
        return None


def _normalize_myuscis_response(receipt_number: str, raw_response: dict) -> dict:
    """
    Normalize the raw myUSCIS JSON into a consistent structure.

    The actual API wraps everything in a "data" key:
    {
      "data": {
        "receiptNumber": "...",
        "formType": "I-765",
        "updatedAt": "2026-06-10",
        "updatedAtTimestamp": "2026-06-10T21:58:08.248Z",
        "events": [ { "eventCode": "FTA0", ... } ],
        ...
      }
    }
    """
    # Unwrap the "data" envelope
    case = raw_response.get("data", raw_response)
    if isinstance(case, list):
        case = case[0] if case else {}

    # Extract and enrich event history
    event_history = []
    raw_events = case.get("events", [])
    for evt in raw_events:
        code = evt.get("eventCode", "")
        event_history.append({
            "event_id": evt.get("eventId", ""),
            "code": code,
            "description": EVENT_CODE_DESCRIPTIONS.get(code, f"Unknown Code: {code}"),
            "event_date": evt.get("eventDateTime", ""),
            "event_timestamp": evt.get("eventTimestamp", ""),
            "created_at": evt.get("createdAt", ""),
            "created_at_timestamp": evt.get("createdAtTimestamp", ""),
            "updated_at": evt.get("updatedAt", ""),
            "updated_at_timestamp": evt.get("updatedAtTimestamp", ""),
        })

    # Determine a human-readable current status from the latest event
    latest_event_code = raw_events[0].get("eventCode", "") if raw_events else ""
    status_text = EVENT_CODE_DESCRIPTIONS.get(latest_event_code, "")

    # Build enriched status text
    if case.get("closed"):
        status_text = "Case Closed — " + status_text
    elif case.get("actionRequired"):
        status_text = "Action Required — " + status_text
    elif not status_text:
        status_text = "Case Pending"

    return {
        "receipt_number": receipt_number,
        "source": "myuscis_api",
        "fetched_at": datetime.now(timezone.utc).isoformat(),

        # Case details
        "status_text": status_text,
        "form_type": case.get("formType", ""),
        "form_name": case.get("formName", ""),
        "applicant_name": case.get("applicantName", ""),
        "representative_name": case.get("representativeName", ""),

        # Dates
        "submission_date": case.get("submissionDate", ""),
        "submission_timestamp": case.get("submissionTimestamp", ""),
        "status_date": case.get("updatedAt", ""),

        # Internal / hidden fields (the silent update gold)
        "last_updated_at": case.get("updatedAtTimestamp", ""),
        "latest_event_code": latest_event_code,
        "service_center": case.get("elisChannelType", ""),

        # Case flags
        "closed": case.get("closed", False),
        "action_required": case.get("actionRequired", False),
        "is_premium": case.get("isPremiumProcessed", False),
        "cms_failure": case.get("cmsFailure", False),
        "all_statuses_complete": case.get("areAllGroupStatusesComplete", False),

        # Rich data
        "event_history": event_history,
        "documents": case.get("documents", []),
        "notices": case.get("notices", []),
        "evidence_requests": case.get("evidenceRequests", []),
        "concurrent_cases": case.get("concurrentCases", []),

        # Keep raw for future diff
        "_raw": case,
    }


def fetch_case_from_myuscis_with_cookie(receipt_number: str, cookies: dict) -> dict | None:
    """
    Fetch detailed case data from the myUSCIS internal API with the provided cookies dict.
    Returns a normalized dict with all available fields, or None on failure.
    """
    url = f"{config.MYUSCIS_CASE_API}{receipt_number}"

    try:
        resp = requests.get(url, cookies=cookies, headers=BROWSER_HEADERS, timeout=20)

        if resp.status_code == 401:
            logger.warning("myUSCIS API returned 401 for %s (Unauthorized).", receipt_number)
            return None

        if resp.status_code != 200:
            logger.error("myUSCIS API returned %d for %s", resp.status_code, receipt_number)
            return None

        raw_response = resp.json()
        return _normalize_myuscis_response(receipt_number, raw_response)

    except RequestException as e:
        logger.error("Request failed for %s: %s", receipt_number, e)
        return None


def fetch_case(receipt_number: str) -> dict | None:
    """
    Fetch case data using saved cookies directly from myUSCIS internal API.
    """
    logger.info("Fetching case data for %s ...", receipt_number)
    cookies = auth.get_valid_cookies()
    if not cookies:
        logger.warning("No saved session cookies found.")
        return None

    result = fetch_case_from_myuscis_with_cookie(receipt_number, cookies)
    if result:
        logger.info("Got live case data from myUSCIS API for %s", receipt_number)
        return result

    logger.error("Could not fetch case data for %s from myUSCIS API.", receipt_number)
    return None


def fetch_all_cases() -> list[dict]:
    """Fetch case data for all configured receipt numbers."""
    results = []
    for rn in config.RECEIPT_NUMBERS:
        data = fetch_case(rn)
        if data:
            results.append(data)
    return results
