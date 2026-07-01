from __future__ import annotations

import json
from typing import Any


def build_review(db, config: dict[str, Any], limit: int = 10) -> dict[str, Any]:
    candidates = [
        _candidate_item(db, candidate)
        for candidate in db.find_pending_candidates(config["project_id"])[:limit]
    ]
    return {
        "status": "clear" if not candidates else "needs_review",
        "project_id": config["project_id"],
        "pending_count": len(candidates),
        "candidates": candidates,
    }


def format_review(review: dict[str, Any]) -> str:
    lines = [
        f"Agent Memory Review: {review['status']}",
        f"Project: {review['project_id']}",
        f"Pending candidates: {review['pending_count']}",
    ]
    if not review["candidates"]:
        lines.append("")
        lines.append("No pending memory candidates.")
        return "\n".join(lines)

    for index, candidate in enumerate(review["candidates"], start=1):
        lines.extend(
            [
                "",
                f"{index}. {candidate['id']} - {candidate['title']}",
                f"Recommended: {candidate['recommended_action']}",
                f"Confidence: {candidate['confidence_score']:.2f}; repeats: {candidate['repeat_count']}",
                f"Pattern: {candidate['failure_pattern']}",
                f"Cause: {candidate['suspected_cause']}",
                f"Lesson: {candidate['recommended_fix']}",
                f"Approve: {candidate['approve_command']}",
                f"Reject: {candidate['reject_command']}",
            ]
        )
        if candidate["files"]:
            lines.append(f"Files: {', '.join(candidate['files'])}")
        if candidate["evidence"]:
            lines.append("Evidence:")
            for event in candidate["evidence"]:
                lines.append(f"- {event['id']} {event['event_type']}: {event['summary']}")
    return "\n".join(lines)


def _candidate_item(db, candidate: dict[str, Any]) -> dict[str, Any]:
    event_ids = json.loads(candidate["supporting_event_ids_json"])
    events = db.get_raw_events(event_ids)
    scope = json.loads(candidate["scope_json"])
    trigger = json.loads(candidate["trigger_json"])
    candidate_id = candidate["id"]
    return {
        "id": candidate_id,
        "title": candidate["title"],
        "status": candidate["status"],
        "recommended_action": _recommended_action(candidate),
        "confidence_score": float(candidate["confidence_score"]),
        "repeat_count": int(candidate["repeat_count"]),
        "failure_pattern": candidate["failure_pattern"],
        "suspected_cause": candidate["suspected_cause"],
        "recommended_fix": candidate["recommended_fix"],
        "files": scope.get("files", []),
        "trigger_terms": trigger.get("terms", []),
        "trigger_commands": trigger.get("commands", []),
        "evidence": [
            {
                "id": event["id"],
                "event_type": event["event_type"],
                "summary": event["summary"],
                "source": event["source"],
                "created_at": event["created_at"],
            }
            for event in events
        ],
        "approve_command": f"memory approve {candidate_id}",
        "reject_command": f"memory reject {candidate_id}",
    }


def _recommended_action(candidate: dict[str, Any]) -> str:
    score = float(candidate["confidence_score"])
    repeats = int(candidate["repeat_count"])
    fix = candidate["recommended_fix"]
    if repeats >= 2 and score >= 0.5:
        return "approve"
    if fix.startswith("Remember this user correction") and score >= 0.4:
        return "approve"
    return "needs_more_evidence"
