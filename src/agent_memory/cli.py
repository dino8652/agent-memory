from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import init_project, load_config


def _force_utf8_io() -> None:
    """Make stdout/stderr emit UTF-8 regardless of the OS locale code page.

    On Windows a piped/redirected process gets a legacy code page (e.g. cp1252)
    for stdout, so printing any non-ASCII character a user typed into a
    correction or that appeared in stderr (smart quotes, em dashes, arrows,
    accents, emoji) raises UnicodeEncodeError and crashes the command. Decoding
    output as UTF-8 with replacement keeps the CLI from dying on real input.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _add_list_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--since")
    parser.add_argument("--limit", type=int, default=20)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--git-mode", choices=["local_only", "commit_lessons"], default="local_only")

    subparsers.add_parser("status")

    lessons = subparsers.add_parser("lessons")
    _add_list_filters(lessons)
    lessons.add_argument("--export", action="store_true")

    events = subparsers.add_parser("events")
    _add_list_filters(events)

    recall = subparsers.add_parser("recall")
    recall.add_argument("query")

    review = subparsers.add_parser("review")
    review.add_argument("--json", action="store_true")
    review.add_argument("--limit", type=int, default=10)

    for command in ("approve", "reject", "forget", "why"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("id")

    record_failure = subparsers.add_parser("record-failure")
    record_failure.add_argument("--command", dest="shell_command", required=True)
    record_failure.add_argument("--exit-code", type=int, default=1)
    record_failure.add_argument("--stderr", default="")
    record_failure.add_argument("--file", action="append", default=[])

    record_correction = subparsers.add_parser("record-correction")
    record_correction.add_argument("text")
    record_correction.add_argument("--file", action="append", default=[])

    install_hooks = subparsers.add_parser("install-hooks")
    install_hooks.add_argument("--python", dest="python_executable")

    install_claude = subparsers.add_parser("install-claude")
    install_claude.add_argument("--global", action="store_true", dest="global_install")
    install_claude.add_argument("--python", dest="python_executable")

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--fix", action="store_true")
    doctor.add_argument("--json", action="store_true")

    subparsers.add_parser("hook")

    subparsers.add_parser("config")
    return parser


def load_project(root: Path):
    from .db import MemoryDb

    try:
        config = load_config(root)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        config = init_project(root)
    db = MemoryDb.open(root)
    db.ensure_project(config["project_id"], root)
    return config, db


def _since_value(value: str | None) -> str | None:
    if not value:
        return None
    if value[:4].isdigit():
        return value
    unit = value[-1]
    amount = value[:-1]
    if not amount.isdigit() or unit not in {"d", "h", "m"}:
        return None
    delta = {
        "d": timedelta(days=int(amount)),
        "h": timedelta(hours=int(amount)),
        "m": timedelta(minutes=int(amount)),
    }[unit]
    return (datetime.now(timezone.utc) - delta).isoformat()


def _jsonable_row(row: dict) -> dict:
    result = dict(row)
    for key in ("scope_json", "trigger_json", "supporting_event_ids_json", "files_touched_json"):
        if key in result and isinstance(result[key], str):
            try:
                result[key.removesuffix("_json")] = json.loads(result[key])
            except json.JSONDecodeError:
                pass
    return result


def export_memory(root: Path, db, config: dict) -> Path:
    export_root = root / ".agent-memory" / "exports"
    lessons_dir = export_root / "lessons"
    candidates_dir = export_root / "candidates"
    lessons_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)

    for lesson in db.enabled_lessons(config["project_id"], 10_000):
        (lessons_dir / f"{lesson['id']}.json").write_text(
            json.dumps(_jsonable_row(lesson), indent=2) + "\n",
            encoding="utf-8",
        )
    for candidate in db.list_candidates(config["project_id"]):
        (candidates_dir / f"{candidate['id']}.json").write_text(
            json.dumps(_jsonable_row(candidate), indent=2) + "\n",
            encoding="utf-8",
        )
    return export_root


def matching_lessons(db, config: dict, query: str, limit: int = 5) -> list[tuple[int, dict]]:
    query_terms = set(query.lower().split())
    matches = []
    for lesson in db.enabled_lessons(config["project_id"], 100):
        haystack = f"{lesson['title']} {lesson['lesson']} {lesson['trigger_json']}".lower()
        score = sum(1 for term in query_terms if term in haystack)
        if score:
            matches.append((score, lesson))
    return sorted(matches, key=lambda item: item[0], reverse=True)[:limit]


def print_recall_block(matches: list[tuple[int, dict]]) -> None:
    if not matches:
        return
    _score, lesson = matches[0]
    print("")
    print("Memory recall:")
    print("A similar failure has been seen before.")
    print("")
    print("Known lesson:")
    print(lesson["lesson"])
    print("")
    print(f"Confidence: {lesson['confidence']}")
    print(f"Last seen: {lesson['last_seen'][:10]}")
    print(f"Lesson ID: {lesson['id']}")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_io()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        config = init_project(Path.cwd(), git_mode=args.git_mode)
        print(f"initialized project {config['project_id']}")
        return 0

    if args.command == "status":
        config, db = load_project(Path.cwd())
        lessons = db.enabled_lessons(config["project_id"], config["max_lessons_injected"])
        events = db.list_events(config["project_id"], 20)
        candidates = db.list_candidates(config["project_id"])
        print(f"Project: {config['project_id']}")
        print(f"Git mode: {config['git_mode']}")
        print(f"Enabled lessons: {len(lessons)}")
        print(f"Candidates: {len(candidates)}")
        print(f"Recent events: {len(events)}")
        db.close()
        return 0

    if args.command == "events":
        config, db = load_project(Path.cwd())
        limit = None if args.all else args.limit
        for event in db.list_events(config["project_id"], limit=limit, since=_since_value(args.since)):
            print(f"{event['id']} {event['event_type']} {event['summary']}")
        db.close()
        return 0

    if args.command == "lessons":
        config, db = load_project(Path.cwd())
        limit = 10_000 if args.all else args.limit
        for lesson in db.enabled_lessons(config["project_id"], limit):
            print(f"{lesson['id']} [{lesson['confidence']}] {lesson['title']}")
        for candidate in db.list_candidates(config["project_id"]):
            if candidate["status"] == "pending":
                print(f"{candidate['id']} [candidate] {candidate['title']}")
        if args.export:
            export_root = export_memory(Path.cwd(), db, config)
            print(f"Exported memory to {export_root}")
        db.close()
        return 0

    if args.command == "recall":
        config, db = load_project(Path.cwd())
        for _score, lesson in matching_lessons(db, config, args.query):
            print(f"{lesson['id']} [{lesson['confidence']}] {lesson['title']}")
            print(lesson["lesson"])
        db.close()
        return 0

    if args.command == "review":
        from .review import build_review, format_review

        config, db = load_project(Path.cwd())
        review = build_review(db, config, limit=args.limit)
        if args.json:
            print(json.dumps(review, indent=2))
        else:
            print(format_review(review))
        db.close()
        return 0

    if args.command == "approve":
        from .extractor import approve_candidate

        config, db = load_project(Path.cwd())
        lesson_id = approve_candidate(db, config, args.id)
        if lesson_id is None:
            print(f"No pending candidate found: {args.id}")
            db.close()
            return 1
        print(f"Promoted {args.id} -> {lesson_id}")
        db.close()
        return 0

    if args.command == "reject":
        _config, db = load_project(Path.cwd())
        if db.reject_candidate(args.id):
            print(f"Rejected {args.id}")
            db.close()
            return 0
        print(f"No pending candidate found: {args.id}")
        db.close()
        return 1

    if args.command == "forget":
        _config, db = load_project(Path.cwd())
        if db.disable_lesson(args.id):
            print(f"Disabled {args.id}")
            db.close()
            return 0
        print(f"No enabled lesson found: {args.id}")
        db.close()
        return 1

    if args.command == "why":
        _config, db = load_project(Path.cwd())
        lesson = db.get_lesson(args.id)
        if not lesson:
            print(f"No lesson found: {args.id}")
            db.close()
            return 1
        print(f"Lesson: {lesson['title']}")
        print(lesson["lesson"])
        print(f"Promotion: {lesson['promotion_reason']}")
        candidates = db.candidates_for_lesson(args.id)
        print(f"Candidates: {len(candidates)}")
        for candidate in candidates:
            print(f"{candidate['id']} {candidate['status']} {candidate['title']}")
            print(f"Pattern: {candidate['failure_pattern']}")
        event_ids = json.loads(lesson["supporting_event_ids_json"])
        events = db.get_raw_events(event_ids)
        print(f"Supporting events: {len(events)}")
        for event in events:
            print(f"{event['id']} {event['event_type']} {event['summary']}")
        injections = db.injection_history(args.id)
        print(f"Injections: {len(injections)}")
        for injection in injections[:5]:
            print(f"{injection['created_at']} {injection['injection_type']} {injection['reason']}")
        db.close()
        return 0

    if args.command == "config":
        config, _db = load_project(Path.cwd())
        print(json.dumps(config, indent=2))
        _db.close()
        return 0

    if args.command in {"record-failure", "record-correction"}:
        from .extractor import process_raw_event
        from .redaction import redact

        config, db = load_project(Path.cwd())
        if args.command == "record-failure":
            event_id = db.insert_raw_event(
                project_id=config["project_id"],
                session_id=None,
                event_type="failed_command",
                source="manual",
                summary=f"{args.shell_command} failed",
                command=args.shell_command,
                exit_code=args.exit_code,
                stderr_excerpt=redact(args.stderr),
                user_text=None,
                files_touched=args.file,
                file_change_state="unknown",
            )
        else:
            event_id = db.insert_raw_event(
                project_id=config["project_id"],
                session_id=None,
                event_type="user_correction",
                source="manual",
                summary=args.text[:120],
                command=None,
                exit_code=None,
                stderr_excerpt=None,
                user_text=redact(args.text),
                files_touched=args.file,
                file_change_state="unknown",
            )
        result = process_raw_event(db, config, event_id)
        print(f"Recorded {event_id}: {result}")
        if args.command == "record-failure":
            print_recall_block(matching_lessons(db, config, f"{args.shell_command} {args.stderr} {' '.join(args.file)}", limit=1))
        db.close()
        return 0

    if args.command == "install-hooks":
        import sys

        from .hooks import install_hooks

        python_executable = args.python_executable or sys.executable
        settings_path = install_hooks(Path.cwd(), python_executable=python_executable)
        print(f"Installed Claude Code hooks in {settings_path}")
        print("Restart Claude Code for hook settings to load.")
        return 0

    if args.command == "install-claude":
        import sys

        from .hooks import install_claude_global, install_hooks

        python_executable = args.python_executable or sys.executable
        if args.global_install:
            settings_path = install_claude_global(python_executable=python_executable)
            print(f"Installed global Claude Code Agent Memory in {settings_path}")
        else:
            settings_path = install_hooks(Path.cwd(), python_executable=python_executable)
            print(f"Installed project Claude Code Agent Memory in {settings_path}")
        print("Restart Claude Code for hook settings to load.")
        return 0

    if args.command == "doctor":
        import sys

        from .doctor import exit_code_for_report, format_doctor_report, repair_doctor, run_doctor

        report = repair_doctor(Path.cwd(), sys.executable) if args.fix else run_doctor(Path.cwd())
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(format_doctor_report(report))
        return exit_code_for_report(report)

    if args.command == "hook":
        from .hooks import handle_stdin

        return handle_stdin()

    return 0
