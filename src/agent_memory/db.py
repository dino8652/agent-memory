from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import db_path
from .redaction import redact


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class MemoryDb:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, root: Path) -> "MemoryDb":
        path = db_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=10.0)
        # Claude Code can fire hooks for several tool calls close together, each
        # opening its own connection to this file. Wait for a contended write
        # lock instead of immediately raising "database is locked".
        conn.execute("PRAGMA busy_timeout=10000")
        db = cls(conn)
        db.migrate()
        return db

    def migrate(self) -> None:
        self.conn.executescript(
            """
            create table if not exists projects (
              id text primary key,
              root_path text not null,
              repo_remote_hash text,
              project_type text,
              created_at text not null,
              updated_at text not null
            );
            create table if not exists sessions (
              id text primary key,
              project_id text not null,
              started_at text not null,
              ended_at text,
              claude_command text,
              status text not null
            );
            create table if not exists raw_events (
              id text primary key,
              project_id text not null,
              session_id text,
              event_type text not null,
              source text not null,
              summary text not null,
              command text,
              exit_code integer,
              stderr_excerpt text,
              user_text text,
              files_touched_json text not null,
              file_change_state text,
              created_at text not null
            );
            create table if not exists candidate_patterns (
              id text primary key,
              project_id text not null,
              title text not null,
              failure_pattern text not null,
              suspected_cause text not null,
              recommended_fix text not null,
              scope_json text not null,
              trigger_json text not null,
              supporting_event_ids_json text not null,
              repeat_count integer not null,
              confidence_score real not null,
              status text not null,
              merged_into_lesson_id text,
              created_at text not null,
              updated_at text not null,
              last_seen text not null
            );
            create table if not exists lessons (
              id text primary key,
              project_id text not null,
              title text not null,
              lesson text not null,
              scope_json text not null,
              trigger_json text not null,
              project_type text,
              confidence text not null,
              confidence_score real not null,
              promotion_reason text not null,
              supporting_event_ids_json text not null,
              created_at text not null,
              updated_at text not null,
              last_seen text not null,
              validated_at text,
              disabled_at text
            );
            create table if not exists injections (
              id text primary key,
              project_id text not null,
              session_id text,
              lesson_id text not null,
              injection_type text not null,
              reason text not null,
              created_at text not null
            );
            create index if not exists idx_events_project_created
              on raw_events(project_id, created_at);
            create index if not exists idx_candidates_project_status
              on candidate_patterns(project_id, status);
            create index if not exists idx_lessons_project_disabled
              on lessons(project_id, disabled_at);
            create index if not exists idx_injections_lesson
              on injections(lesson_id);
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "MemoryDb":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def table_names(self) -> set[str]:
        rows = self.conn.execute("select name from sqlite_master where type='table'").fetchall()
        return {row["name"] for row in rows}

    def ensure_project(self, project_id: str, root: Path, project_type: str | None = None) -> None:
        timestamp = now_iso()
        self.conn.execute(
            """
            insert into projects (id, root_path, project_type, created_at, updated_at)
            values (?, ?, ?, ?, ?)
            on conflict(id) do update set
              root_path=excluded.root_path,
              project_type=coalesce(excluded.project_type, projects.project_type),
              updated_at=excluded.updated_at
            """,
            (project_id, str(root), project_type, timestamp, timestamp),
        )
        self.conn.commit()

    def start_session(self, project_id: str, claude_command: str) -> str:
        session_id = new_id("ses")
        self.conn.execute(
            """
            insert into sessions (id, project_id, started_at, claude_command, status)
            values (?, ?, ?, ?, 'started')
            """,
            (session_id, project_id, now_iso(), claude_command),
        )
        self.conn.commit()
        return session_id

    def cleanup_open_sessions(self, project_id: str) -> int:
        cursor = self.conn.execute(
            """
            update sessions
            set status='failed_open', ended_at=?
            where project_id=? and status='started'
            """,
            (now_iso(), project_id),
        )
        self.conn.commit()
        return cursor.rowcount

    def finish_session(self, session_id: str, status: str) -> None:
        self.conn.execute(
            "update sessions set status=?, ended_at=? where id=?",
            (status, now_iso(), session_id),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> dict[str, Any]:
        row = self.conn.execute("select * from sessions where id=?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return dict(row)

    def insert_raw_event(
        self,
        *,
        project_id: str,
        session_id: str | None,
        event_type: str,
        source: str,
        summary: str,
        command: str | None,
        exit_code: int | None,
        stderr_excerpt: str | None,
        user_text: str | None,
        files_touched: list[str],
        file_change_state: str,
    ) -> str:
        event_id = new_id("evt")
        self.conn.execute(
            """
            insert into raw_events
            (id, project_id, session_id, event_type, source, summary, command, exit_code,
             stderr_excerpt, user_text, files_touched_json, file_change_state, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                project_id,
                session_id,
                event_type,
                source,
                summary,
                command,
                exit_code,
                redact(stderr_excerpt),
                redact(user_text),
                json.dumps(files_touched),
                file_change_state,
                now_iso(),
            ),
        )
        self.conn.commit()
        return event_id

    def get_raw_event(self, event_id: str) -> dict[str, Any]:
        row = self.conn.execute("select * from raw_events where id=?", (event_id,)).fetchone()
        if row is None:
            raise KeyError(event_id)
        return dict(row)

    def get_raw_events(self, event_ids: list[str]) -> list[dict[str, Any]]:
        if not event_ids:
            return []
        placeholders = ",".join("?" for _ in event_ids)
        rows = self.conn.execute(
            f"select * from raw_events where id in ({placeholders}) order by created_at asc",
            tuple(event_ids),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, project_id: str, limit: int | None = 20, since: str | None = None) -> list[dict[str, Any]]:
        query = "select * from raw_events where project_id=?"
        params: list[Any] = [project_id]
        if since:
            query += " and created_at >= ?"
            params.append(since)
        query += " order by created_at desc"
        if limit is not None:
            query += " limit ?"
            params.append(limit)
        rows = self.conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def insert_candidate(
        self,
        *,
        project_id: str,
        title: str,
        failure_pattern: str,
        suspected_cause: str,
        recommended_fix: str,
        scope: dict[str, Any],
        trigger: dict[str, Any],
        supporting_event_ids: list[str],
        repeat_count: int,
        confidence_score: float,
    ) -> str:
        candidate_id = new_id("can")
        timestamp = now_iso()
        self.conn.execute(
            """
            insert into candidate_patterns
            (id, project_id, title, failure_pattern, suspected_cause, recommended_fix,
             scope_json, trigger_json, supporting_event_ids_json, repeat_count,
             confidence_score, status, created_at, updated_at, last_seen)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                candidate_id,
                project_id,
                title,
                failure_pattern,
                suspected_cause,
                recommended_fix,
                json.dumps(scope),
                json.dumps(trigger),
                json.dumps(supporting_event_ids),
                repeat_count,
                confidence_score,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        self.conn.commit()
        return candidate_id

    def find_pending_candidates(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select * from candidate_patterns where project_id=? and status='pending' order by updated_at desc",
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_candidates(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select * from candidate_patterns where project_id=? order by updated_at desc",
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def candidates_for_lesson(self, lesson_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select * from candidate_patterns where merged_into_lesson_id=? order by updated_at asc",
            (lesson_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("select * from candidate_patterns where id=?", (candidate_id,)).fetchone()
        return dict(row) if row else None

    def update_candidate_repeat(
        self,
        candidate_id: str,
        event_id: str,
        confidence_score: float,
        recommended_fix: str | None = None,
    ) -> dict[str, Any]:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        event_ids = json.loads(candidate["supporting_event_ids_json"])
        if event_id not in event_ids:
            event_ids.append(event_id)
        timestamp = now_iso()
        fix = recommended_fix or candidate["recommended_fix"]
        self.conn.execute(
            """
            update candidate_patterns
            set supporting_event_ids_json=?, repeat_count=?, confidence_score=?, recommended_fix=?, updated_at=?, last_seen=?
            where id=?
            """,
            (json.dumps(event_ids), len(event_ids), confidence_score, fix, timestamp, timestamp, candidate_id),
        )
        self.conn.commit()
        candidate.update(
            supporting_event_ids_json=json.dumps(event_ids),
            repeat_count=len(event_ids),
            confidence_score=confidence_score,
            recommended_fix=fix,
            updated_at=timestamp,
            last_seen=timestamp,
        )
        return candidate

    def reject_candidate(self, candidate_id: str) -> bool:
        cursor = self.conn.execute(
            "update candidate_patterns set status='rejected', updated_at=? where id=? and status='pending'",
            (now_iso(), candidate_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_candidate_merged(self, candidate_id: str, lesson_id: str) -> None:
        self.conn.execute(
            "update candidate_patterns set status='merged', merged_into_lesson_id=?, updated_at=? where id=?",
            (lesson_id, now_iso(), candidate_id),
        )
        self.conn.commit()

    def insert_lesson(
        self,
        *,
        project_id: str,
        title: str,
        lesson: str,
        scope: dict[str, Any],
        trigger: dict[str, Any],
        project_type: str | None,
        confidence: str,
        confidence_score: float,
        promotion_reason: str,
        supporting_event_ids: list[str],
    ) -> str:
        lesson_id = new_id("les")
        timestamp = now_iso()
        self.conn.execute(
            """
            insert into lessons
            (id, project_id, title, lesson, scope_json, trigger_json, project_type, confidence,
             confidence_score, promotion_reason, supporting_event_ids_json, created_at, updated_at,
             last_seen, validated_at, disabled_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null)
            """,
            (
                lesson_id,
                project_id,
                title,
                lesson,
                json.dumps(scope),
                json.dumps(trigger),
                project_type,
                confidence,
                confidence_score,
                promotion_reason,
                json.dumps(supporting_event_ids),
                timestamp,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        self.conn.commit()
        return lesson_id

    def enabled_lessons(self, project_id: str, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select * from lessons
            where project_id=? and disabled_at is null
            order by confidence_score desc, last_seen desc
            limit ?
            """,
            (project_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def merge_lesson(
        self,
        lesson_id: str,
        *,
        lesson: str,
        confidence: str,
        confidence_score: float,
        supporting_event_ids: list[str],
        scope: dict[str, Any] | None = None,
        trigger: dict[str, Any] | None = None,
    ) -> None:
        timestamp = now_iso()
        columns = [
            "lesson=?",
            "confidence=?",
            "confidence_score=?",
            "supporting_event_ids_json=?",
            "updated_at=?",
            "last_seen=?",
            "validated_at=?",
        ]
        params: list[Any] = [
            lesson,
            confidence,
            confidence_score,
            json.dumps(supporting_event_ids),
            timestamp,
            timestamp,
            timestamp,
        ]
        if scope is not None:
            columns.append("scope_json=?")
            params.append(json.dumps(scope))
        if trigger is not None:
            columns.append("trigger_json=?")
            params.append(json.dumps(trigger))
        params.append(lesson_id)
        self.conn.execute(f"update lessons set {', '.join(columns)} where id=?", tuple(params))
        self.conn.commit()

    def get_lesson(self, lesson_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("select * from lessons where id=?", (lesson_id,)).fetchone()
        return dict(row) if row else None

    def disable_lesson(self, lesson_id: str) -> bool:
        cursor = self.conn.execute(
            "update lessons set disabled_at=? where id=? and disabled_at is null",
            (now_iso(), lesson_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def insert_injection(self, *, project_id: str, session_id: str | None, lesson_id: str, injection_type: str, reason: str) -> str:
        injection_id = new_id("inj")
        self.conn.execute(
            """
            insert into injections (id, project_id, session_id, lesson_id, injection_type, reason, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (injection_id, project_id, session_id, lesson_id, injection_type, reason, now_iso()),
        )
        self.conn.commit()
        return injection_id

    def injection_history(self, lesson_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select * from injections where lesson_id=? order by created_at desc",
            (lesson_id,),
        ).fetchall()
        return [dict(row) for row in rows]
