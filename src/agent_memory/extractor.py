from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class NormalizedEvent:
    event_id: str
    event_type: str
    command_family: str
    error_terms: list[str]
    files_touched: list[str]
    user_terms: list[str]
    file_change_state: str
    summary: str
    # Raw text is kept for HUMAN-READABLE lesson output. Keyword lists above are
    # only for matching/clustering -- they must never be shown as the lesson.
    command: str | None = None
    raw_error: str = ""
    raw_correction: str = ""


def command_family(command: str | None) -> str:
    if not command:
        return "unknown"
    parts = command.strip().split()
    if not parts:
        return "unknown"
    if len(parts) >= 2 and parts[0] in {"npm", "pnpm", "yarn"}:
        return f"{parts[0]} {parts[1]}"
    return parts[0]


def terms(text: str | None) -> list[str]:
    if not text:
        return []
    words = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", text.lower())
    noisy = {
        "actual",
        "error",
        "expected",
        "failed",
        "still",
        "that",
        "traceback",
        "warning",
        "wrong",
    }
    deduped: list[str] = []
    for word in words:
        if word in noisy or word in deduped:
            continue
        deduped.append(word)
        if len(deduped) >= 20:
            break
    return deduped


def normalize_raw_event(row: dict[str, Any]) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=row["id"],
        event_type=row["event_type"],
        command_family=command_family(row.get("command")),
        error_terms=terms(row.get("stderr_excerpt")),
        files_touched=json.loads(row.get("files_touched_json") or "[]"),
        user_terms=terms(row.get("user_text")),
        file_change_state=row.get("file_change_state") or "unknown",
        summary=row.get("summary") or "",
        command=row.get("command"),
        raw_error=row.get("stderr_excerpt") or "",
        raw_correction=row.get("user_text") or "",
    )


def signal_score(event: NormalizedEvent) -> float:
    score = 0.0
    if event.command_family != "unknown":
        score += 0.15
    if event.error_terms:
        score += 0.2
    if event.files_touched:
        score += 0.2
    if event.user_terms:
        score += 0.3
    if event.event_type == "user_correction" and event.user_terms:
        score += 0.2
    if event.event_type == "failed_command" and event.command_family != "unknown" and event.error_terms:
        score += 0.1
    if event.file_change_state == "changed_since_last_failure":
        score += 0.15
    if event.file_change_state == "unchanged" and event.event_type == "failed_command":
        score -= 0.4
    return max(0.0, min(1.0, score))


def overlap(left: list[str], right: list[str]) -> int:
    return len(set(left).intersection(right))


def candidate_similarity(event: NormalizedEvent, candidate: dict[str, Any]) -> float:
    scope = json.loads(candidate["scope_json"])
    trigger = json.loads(candidate["trigger_json"])
    score = 0.0
    if overlap(event.files_touched, scope.get("files", [])):
        score += 0.35
    term_overlap = overlap(event.error_terms + event.user_terms, trigger.get("terms", []))
    if term_overlap:
        score += 0.35
    if not event.files_touched and term_overlap >= 2:
        score += 0.25
    if event.command_family in trigger.get("commands", []):
        score += 0.2
    return min(1.0, score)


def confidence_score(event: NormalizedEvent, repeat_count: int, manual: bool = False) -> float:
    score = 0.0
    if repeat_count >= 2:
        score += 0.25
    if event.user_terms:
        score += 0.25
    if event.files_touched:
        score += 0.15
    if event.command_family != "unknown":
        score += 0.15
    if manual:
        score += 0.1
    return min(1.0, score)


def confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


# Lines that are traceback scaffolding, not the actual error.
_TRACEBACK_NOISE = re.compile(
    r'^\s*('
    r'traceback \(most recent call last\)|'
    r'file ".*?", line \d+.*|'
    r'at [\w$.<> ]+\(.*\)|'          # JS stack frames: "at fn (file:line)"
    r'exit code \d+|'
    r'during handling of the above.*|the above exception.*|'
    r'[-=_]{3,}.*|'                   # separator rules
    r'[\s~^|>+]+'                     # caret / underline / prompt-marker lines
    r')\s*$',
    re.IGNORECASE,
)
# Words that mark the salient error/assertion line inside noisy output.
_ERROR_SIGNAL = re.compile(
    r'\b(error|exception|assert\w*|expected|failure|not found|cannot find|no such|'
    r'no module|undefined|is not defined|unresolved|panic|fatal|denied|refused|'
    r'rejected|timed?\s?out|unrecognized|invalid|missing|conflict|npm err|'
    r'syntaxerror|typeerror|valueerror|keyerror)\b',
    re.IGNORECASE,
)
# Conversational preamble to strip from a correction so the lesson is the directive.
_CORRECTION_PREAMBLE = re.compile(
    r"^(no[,.]\s+|nope[,.]\s+|actually[,.]\s+|wait[,.]\s+|"
    r"that\'?s (?:wrong|not right|incorrect|not it)[,.]?\s+|"
    r"that is (?:wrong|not right|incorrect)[,.]?\s+|still wrong[,.]?\s+)+",
    re.IGNORECASE,
)


def _tidy(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _clean_correction(text: str, limit: int = 240) -> str:
    return _tidy(_CORRECTION_PREAMBLE.sub("", " ".join((text or "").split())).strip(), limit)


def error_signature(text: str | None, limit: int = 160) -> str:
    """Extract the meaningful error line from noisy stderr / a traceback.

    Deterministic, no LLM: drop traceback scaffolding (``File "..."``, caret
    lines, ``Traceback ...``, ``Exit code N``) and return the salient
    error/assertion line -- e.g. ``ModuleNotFoundError: No module named 'x'`` --
    rather than a bag of keywords. Exceptions usually sit at the end of a
    traceback, so scan bottom-up for the first signal-bearing line.
    """
    if not text:
        return ""
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip()
        and not _TRACEBACK_NOISE.match(ln.strip())
        and not ln.strip().lower().startswith(("file \"", "at ", "traceback"))
    ]
    if not lines:
        return ""
    for line in reversed(lines):
        if _ERROR_SIGNAL.search(line):
            return _tidy(line, limit)
    return _tidy(lines[-1], limit)


def _suggested_lesson(event: NormalizedEvent) -> str:
    # A user correction is already a clear, human-written instruction. Keep it
    # verbatim (minus conversational filler) instead of reducing it to keywords.
    correction = _clean_correction(event.raw_correction)
    if correction:
        return correction
    if event.user_terms:  # fallback only if the raw correction text is missing
        return _tidy(" ".join(event.user_terms[:14]).capitalize(), 240)

    # For a bare command failure, surface the real error line -- not term-soup.
    signature = error_signature(event.raw_error)
    command = (event.command or "").strip()
    if signature and command:
        return f"`{command}` has failed here before with: {signature}"
    if signature:
        return f"This failure has recurred here: {signature}"
    if command:
        return f"`{command}` has failed here before; check the project-specific setup."
    return event.summary or "A project-specific command failure recurred here."


def _candidate_title(event: NormalizedEvent) -> str:
    correction = _clean_correction(event.raw_correction, limit=70)
    if correction:
        return correction
    signature = error_signature(event.raw_error, limit=70)
    if event.files_touched and signature:
        return _tidy(f"{event.files_touched[0]}: {signature}", 80)
    if signature:
        return signature
    if event.files_touched:
        return f"Recurring failure near {event.files_touched[0]}"
    return "Recurring project failure"


def draft_candidate(db, project_id: str, event: NormalizedEvent, score: float) -> str:
    title = _candidate_title(event)
    return db.insert_candidate(
        project_id=project_id,
        title=title,
        failure_pattern=event.summary,
        suspected_cause="Repeated failure shape in this project.",
        recommended_fix=_suggested_lesson(event),
        scope={"files": event.files_touched},
        trigger={"terms": event.error_terms + event.user_terms, "commands": [event.command_family]},
        supporting_event_ids=[event.event_id],
        repeat_count=1,
        confidence_score=score,
    )


def promote_candidate(db, config: dict[str, Any], candidate: dict[str, Any], reason: str) -> str:
    score = float(candidate["confidence_score"])
    existing = _similar_lesson(db, config, candidate)
    if existing is not None:
        existing_events = json.loads(existing["supporting_event_ids_json"])
        candidate_events = json.loads(candidate["supporting_event_ids_json"])
        merged_events = list(dict.fromkeys(existing_events + candidate_events))
        lesson_text = _preferred_lesson_text(existing["lesson"], candidate["recommended_fix"])
        merged_score = max(float(existing["confidence_score"]), score)
        # Union scope files and trigger terms so one lesson covers every site the
        # same failure/correction showed up at, instead of spawning a near-duplicate
        # lesson per file that bloats the injected context.
        merged_scope, merged_trigger = _union_scope_trigger(existing, candidate)
        db.merge_lesson(
            existing["id"],
            lesson=lesson_text,
            confidence=confidence_label(merged_score),
            confidence_score=merged_score,
            supporting_event_ids=merged_events,
            scope=merged_scope,
            trigger=merged_trigger,
        )
        db.mark_candidate_merged(candidate["id"], existing["id"])
        return existing["id"]
    lesson_id = db.insert_lesson(
        project_id=config["project_id"],
        title=candidate["title"],
        lesson=candidate["recommended_fix"],
        scope=json.loads(candidate["scope_json"]),
        trigger=json.loads(candidate["trigger_json"]),
        project_type=None,
        confidence=confidence_label(score),
        confidence_score=score,
        promotion_reason=reason,
        supporting_event_ids=json.loads(candidate["supporting_event_ids_json"]),
    )
    db.mark_candidate_merged(candidate["id"], lesson_id)
    return lesson_id


def _norm_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _union(left: list[str], right: list[str]) -> list[str]:
    return list(dict.fromkeys(list(left) + list(right)))


def _union_scope_trigger(existing: dict[str, Any], candidate: dict[str, Any]):
    existing_scope = json.loads(existing["scope_json"])
    candidate_scope = json.loads(candidate["scope_json"])
    existing_trigger = json.loads(existing["trigger_json"])
    candidate_trigger = json.loads(candidate["trigger_json"])
    scope = {"files": _union(existing_scope.get("files", []), candidate_scope.get("files", []))}
    trigger = {
        "terms": _union(existing_trigger.get("terms", []), candidate_trigger.get("terms", [])),
        "commands": _union(existing_trigger.get("commands", []), candidate_trigger.get("commands", [])),
    }
    return scope, trigger


def _similar_lesson(db, config: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any] | None:
    candidate_scope = json.loads(candidate["scope_json"])
    candidate_trigger = json.loads(candidate["trigger_json"])
    candidate_files = candidate_scope.get("files", [])
    candidate_terms = candidate_trigger.get("terms", [])
    candidate_text = _norm_text(candidate["recommended_fix"])
    for lesson in db.enabled_lessons(config["project_id"], 1000):
        # Identical advice at a different file is the same lesson; merge and union
        # scope rather than duplicating it per file.
        if candidate_text and _norm_text(lesson["lesson"]) == candidate_text:
            return lesson
        lesson_scope = json.loads(lesson["scope_json"])
        lesson_trigger = json.loads(lesson["trigger_json"])
        file_overlap = overlap(candidate_files, lesson_scope.get("files", []))
        term_overlap = overlap(candidate_terms, lesson_trigger.get("terms", []))
        if file_overlap and term_overlap >= 2:
            return lesson
        if not candidate_files and term_overlap >= 4:
            return lesson
    return None


def _is_failure_signature(text: str) -> bool:
    return "has failed here before" in text or text.startswith("This failure has recurred")


def _preferred_lesson_text(existing: str, candidate: str) -> str:
    # A human correction (a plain-language instruction) is more valuable than an
    # auto-generated failure signature, so prefer it when the two merge.
    if _is_failure_signature(existing) and not _is_failure_signature(candidate):
        return candidate
    if _is_failure_signature(candidate) and not _is_failure_signature(existing):
        return existing
    return existing


def approve_candidate(db, config: dict[str, Any], candidate_id: str) -> str | None:
    candidate = db.get_candidate(candidate_id)
    if candidate is None or candidate["status"] not in {"pending", "approved"}:
        return None
    score = min(1.0, max(float(candidate["confidence_score"]), 0.5) + 0.1)
    candidate["confidence_score"] = score
    return promote_candidate(db, config, candidate, "manual_approval")


def process_raw_event(db, config: dict[str, Any], event_id: str) -> str:
    row = db.get_raw_event(event_id)
    event = normalize_raw_event(row)
    if signal_score(event) < config["min_signal_threshold"]:
        return "skipped_low_signal"

    best = None
    best_score = 0.0
    for candidate in db.find_pending_candidates(config["project_id"]):
        score = candidate_similarity(event, candidate)
        if score > best_score:
            best = candidate
            best_score = score

    if best is not None and best_score >= 0.5:
        repeat_count = int(best["repeat_count"]) + 1
        score = confidence_score(event, repeat_count)
        recommended_fix = _suggested_lesson(event) if event.user_terms else None
        updated = db.update_candidate_repeat(best["id"], event.event_id, score, recommended_fix=recommended_fix)
        if repeat_count >= int(config["repeat_threshold"]):
            promote_candidate(db, config, updated, "repeat_threshold")
            return "promoted"
        return "clustered"

    draft_candidate(db, config["project_id"], event, confidence_score(event, 1))
    return "candidate_created"
