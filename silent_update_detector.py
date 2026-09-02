"""
Silent Update Detector.

Compares newly fetched case data against historical snapshots to detect:
1. Public status changes (status text changed)
2. Silent timestamp updates (internal timestamp changed, status text same)
3. New event additions (new entries in event history)
"""

import logging
from datetime import datetime, timezone
from copy import deepcopy

import config

logger = logging.getLogger(__name__)

# Change categories
CHANGE_PUBLIC_STATUS = "public_status_change"
CHANGE_SILENT_TIMESTAMP = "silent_timestamp_update"
CHANGE_NEW_EVENT = "new_event_added"
CHANGE_NIEM_CODE = "niem_code_change"
CHANGE_SERVICE_CENTER = "service_center_change"
CHANGE_FIRST_FETCH = "first_fetch"


def detect_changes(receipt_number: str, new_data: dict, save_to_disk: bool = False) -> list[dict]:
    """
    Compare new case data against the last known snapshot.

    Returns a list of detected change dicts, each with:
      - type: one of the CHANGE_* constants
      - description: human-readable description
      - old_value / new_value: what changed
      - detected_at: ISO timestamp
      - severity: 'info', 'warning', or 'alert'
    """
    history = config.load_case_history() if save_to_disk else {}
    case_history = history.get(receipt_number, {})
    snapshots = case_history.get("snapshots", [])

    changes = []
    now = datetime.now(timezone.utc).isoformat()

    if not snapshots:
        # First time seeing this case
        changes.append({
            "type": CHANGE_FIRST_FETCH,
            "description": f"First data capture for {receipt_number}",
            "old_value": None,
            "new_value": new_data.get("status_text", ""),
            "detected_at": now,
            "severity": "info",
        })
    else:
        last = snapshots[-1]

        # ── 1. Public status text change ──
        old_status = last.get("status_text", "")
        new_status = new_data.get("status_text", "")
        if old_status and new_status and old_status != new_status:
            changes.append({
                "type": CHANGE_PUBLIC_STATUS,
                "description": f"Status changed: '{old_status}' → '{new_status}'",
                "old_value": old_status,
                "new_value": new_status,
                "detected_at": now,
                "severity": "alert",
            })

        # ── 2. Silent timestamp update ──
        old_ts = last.get("last_updated_at", "")
        new_ts = new_data.get("last_updated_at", "")
        if old_ts and new_ts and old_ts != new_ts and old_status == new_status:
            changes.append({
                "type": CHANGE_SILENT_TIMESTAMP,
                "description": (
                    f"Silent update detected — internal timestamp changed "
                    f"from '{old_ts}' to '{new_ts}' (status text unchanged)"
                ),
                "old_value": old_ts,
                "new_value": new_ts,
                "detected_at": now,
                "severity": "warning",
            })

        # ── 3. New event in history ──
        old_events = last.get("event_history", [])
        new_events = new_data.get("event_history", [])
        if len(new_events) > len(old_events):
            added = new_events[len(old_events):]
            for evt in added:
                changes.append({
                    "type": CHANGE_NEW_EVENT,
                    "description": (
                        f"New event: {evt.get('description', 'Unknown')} "
                        f"(code: {evt.get('code', 'N/A')}, date: {evt.get('event_date') or evt.get('date', 'N/A')})"
                    ),
                    "old_value": None,
                    "new_value": evt,
                    "detected_at": now,
                    "severity": "warning",
                })

        # ── 4. NIEM event code change ──
        old_code = last.get("niem_event_code", "")
        new_code = new_data.get("niem_event_code", "")
        if old_code and new_code and old_code != new_code:
            changes.append({
                "type": CHANGE_NIEM_CODE,
                "description": (
                    f"Internal processing code changed: '{old_code}' → '{new_code}'"
                ),
                "old_value": old_code,
                "new_value": new_code,
                "detected_at": now,
                "severity": "warning",
            })

        # ── 5. Service center change ──
        old_center = last.get("service_center", "")
        new_center = new_data.get("service_center", "")
        if old_center and new_center and old_center != new_center:
            changes.append({
                "type": CHANGE_SERVICE_CENTER,
                "description": (
                    f"Service center changed: '{old_center}' → '{new_center}'"
                ),
                "old_value": old_center,
                "new_value": new_center,
                "detected_at": now,
                "severity": "info",
            })

    # ── Save new snapshot ──
    snapshot = deepcopy(new_data)
    # Remove raw data from stored snapshot to save space
    snapshot.pop("_raw", None)
    snapshots.append(snapshot)

    # Store changes in history
    change_log = case_history.get("change_log", [])
    change_log.extend(changes)

    history[receipt_number] = {
        "snapshots": snapshots,
        "change_log": change_log,
        "last_checked": now,
        "current_status": new_data.get("status_text", ""),
        "form_type": new_data.get("form_type", ""),
    }

    if save_to_disk:
        config.save_case_history(history)

    if changes:
        for ch in changes:
            level = (
                logging.WARNING if ch["severity"] in ("alert", "warning")
                else logging.INFO
            )
            logger.log(level, "[CHANGE] [%s] %s", receipt_number, ch["description"])
    else:
        logger.info("No changes detected for %s", receipt_number)

    return changes


def get_case_summary(receipt_number: str) -> dict | None:
    """Get the current summary for a receipt number from stored history."""
    history = config.load_case_history()
    return history.get(receipt_number)


def get_all_summaries() -> dict:
    """Get summaries for all tracked cases."""
    return config.load_case_history()
