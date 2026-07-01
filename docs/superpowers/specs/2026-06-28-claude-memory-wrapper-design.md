# Claude Code Memory Wrapper Design

## Summary

Build a local-only CLI wrapper for Claude Code that remembers validated coding mistakes in a project, turns repeated or approved failures into scoped lessons, and injects only relevant lessons back into future Claude Code sessions.

The product principle is:

> Log generously, teach selectively.

The tool should feel intentionally boring. The magic is not the interface; the magic is Claude making fewer repeated mistakes in the same codebase.

## Goals

- Run entirely on the developer's machine.
- Start as a Claude Code-first wrapper, not a cloud service or team platform.
- Capture two trusted v1 failure sources:
  - failed commands, including tests, lint, typecheck, build, and runtime commands
  - user corrections, rejected suggestions, and explicit "do not do that again" feedback
- Convert raw failures into candidate patterns.
- Promote only validated patterns into injectable lessons.
- Generate a separate `.agent-memory/claude-context.md` file instead of directly mixing generated memory into human-authored instructions.
- Append a stable pointer to the bottom of `CLAUDE.md`.
- Provide power-user commands for inspecting, approving, rejecting, recalling, and disabling memory.

## Non-Goals For V1

- No cloud sync.
- No team memory.
- No MCP server.
- No API exposure.
- No always-on background daemon.
- No Codex adapter.
- No cross-project shared memory.
- No automatic semantic diff-based lesson promotion.
- No aggressive live session intervention.
- No advanced secret scanning beyond the basic v1 redaction rules.

V1 proves the local learning loop. V2 improves signal quality. V3 expands reach.

## User Model

The main user flow is a wrapper command:

```bash
memory-claude
```

Power users can inspect and control memory explicitly:

```bash
memory status
memory lessons
memory events
memory events --all
memory events --since 7d
memory recall "auth middleware JWT failure"
memory approve <candidate-id>
memory reject <candidate-id>
memory forget <lesson-id>
memory why <lesson-id>
memory config
```

`memory events` defaults to the last 20 events.

## Setup Flow

The project is initialized with:

```bash
memory init
```

Setup asks for the git storage mode:

- `local_only`: default; `.agent-memory/` is ignored by git.
- `commit_lessons`: promoted lessons may be versioned, but raw events remain local.

The CLI records this choice in `.agent-memory/config.json`.

## Project Files

SQLite is the source of truth. Generated files are projections.

```text
.agent-memory/
  config.json
  index.sqlite
  claude-context.md
  exports/
    candidates/
    lessons/
```

`exports/candidates/` and `exports/lessons/` are generated on demand, for example through:

```bash
memory lessons --export
```

They are not a second source of truth.

The wrapper appends this pointer to the bottom of `CLAUDE.md`:

```md
Before starting work, read .agent-memory/claude-context.md for learned project-specific failure patterns.
```

The pointer is appended rather than prepended so it does not displace human-authored project instructions.
The wrapper checks for the pointer string before appending. It is written at most once.

## Pre-Launch Behavior

Before launching Claude Code, `memory-claude`:

1. Detects the current project.
2. Refreshes `.agent-memory/claude-context.md` from promoted lessons.
3. Ensures `CLAUDE.md` references the generated context file.
4. Launches Claude Code normally.

The wrapper must fail open. If `memory-claude` crashes, hangs, or cannot prepare memory before launch, the developer must still be able to run `claude` normally. Memory failure must not block development.
If the wrapper crashes after a session starts, a cleanup process on the next invocation marks the previous open session `failed_open` and closes it.

## Injection Order

Memory injection is built in this order:

1. Before session start: prepare Claude with stable project lessons.
2. After failed command: retrieve similar past failures and show focused recall.
3. During session: eventually provide live nudges when the signal is reliable enough.

V1 includes before-session injection and after-failure recall. During-session nudges are later work and should use higher thresholds to avoid noise.

## Example Recall Block

After a failure, the wrapper can show:

```text
Memory recall:
A similar auth middleware failure happened twice before.

Known lesson:
Do not rely on cached session state in middleware. Verify the user directly before authorization checks.

Confidence: medium
Last seen: 2026-06-21
Lesson ID: les_123
```

The recall block is concise, attributed, and confidence-ranked.

## Memory Lifecycle

Memory has three layers:

```text
raw event -> candidate pattern -> promoted lesson
```

Raw events are evidence. Promoted lessons are instructions.

### Raw Event

A raw event records a trustworthy failure signal:

```text
event type: failed_command | user_correction | rejected_change
command: npm test
exit code: 1
stderr summary: ...
files touched: ...
agent action before failure: ...
user correction: ...
```

### Candidate Pattern

The extractor groups related raw events into a candidate:

```text
Pattern: Agent keeps using cached session state in middleware.
Cause: It assumes session data is authoritative.
Fix: In this codebase, call getUser() before authorization checks.
Evidence: 2 similar failures, 1 explicit user correction.
```

Candidates are not injected.

### Promoted Lesson

A candidate becomes a lesson only through:

- manual approval
- repeat threshold

Automatic semantic diff-based promotion is v2. A failed command followed by a passing command after code changes may suggest a candidate in the future, but it must not silently promote a lesson in v1.

Repetition without a correction is evidence of a pattern, not proof of the right fix.

## Lesson Shape

Lessons are compact, scoped, and confidence-ranked:

```yaml
scope:
  files: ["src/auth/**", "middleware.ts"]
  commands: ["npm test", "npm run typecheck"]
trigger:
  errors: ["session", "JWT", "auth middleware"]
project_type: "next.js"
lesson: "Do not trust cached session state in middleware. Verify the user before authorization checks."
confidence: medium
last_seen: "2026-06-21"
validated_at: "2026-06-21"
```

`project_type`, `last_seen`, and `validated_at` exist from v1 so future versions can support confidence decay and cross-project pattern matching without a schema rethink.

## Generated Context File

`.agent-memory/claude-context.md` is generated from the currently selected lessons:

```md
# Learned Failure Patterns

Generated by memory-claude. Do not edit directly.

## Auth Middleware

When working in `src/auth/**` or `middleware.ts`:
Do not rely on cached session state in middleware. Verify the user directly before authorization checks.

Confidence: medium
Last seen: 2026-06-21
Lesson ID: les_123
```

Invariant:

> SQLite owns memory. `claude-context.md` is just the currently selected projection of that memory.

## Data Model

Use SQLite as the single source of truth.

### `projects`

Tracks local project identity.

```text
id
root_path
repo_remote_hash nullable
project_type nullable
created_at
updated_at
```

### `sessions`

Tracks one `memory-claude` invocation.

```text
id
project_id
started_at
ended_at nullable
claude_command nullable
status                       -- started | completed | failed_open | crashed
```

### `raw_events`

Append-only evidence log, except for explicit privacy deletion.

```text
id
project_id
session_id nullable
event_type                   -- failed_command | user_correction | rejected_change
source                       -- claude_hook | wrapper | manual
summary
command nullable
exit_code nullable
stderr_excerpt nullable
user_text nullable
files_touched_json
file_change_state nullable   -- changed_since_last_failure | unchanged | unknown
created_at
```

`file_change_state` is populated by the wrapper by comparing git status between the previous failure and the current one. If there is no git repo, it defaults to `unknown`.

### `candidate_patterns`

Possible lessons not yet trusted enough to inject.

```text
id
project_id
title
failure_pattern
suspected_cause
recommended_fix
scope_json
trigger_json
supporting_event_ids_json
repeat_count
confidence_score             -- numeric 0.0 to 1.0
status                       -- pending | approved | rejected | merged
merged_into_lesson_id nullable
created_at
updated_at
last_seen
```

### `lessons`

Promoted, injectable memory.

```text
id
project_id
title
lesson
scope_json
trigger_json
project_type nullable
confidence                   -- low | medium | high
confidence_score             -- numeric 0.0 to 1.0
promotion_reason             -- manual_approval | repeat_threshold
supporting_event_ids_json
created_at
updated_at
last_seen
validated_at nullable
disabled_at nullable
```

`disabled_at` soft-disables a lesson instead of deleting it.

### `injections`

Audit log of what memory was shown to Claude and why.

```text
id
project_id
session_id
lesson_id
injection_type               -- before_session | after_failure | live_nudge
reason
created_at
```

This table powers `memory why <lesson-id>` and `memory status`.

### Future Join Tables

For v1, `supporting_event_ids_json` is acceptable. In v1.5, add queryable join tables:

```text
candidate_events
lesson_events
```

These will answer questions like "which lessons does this event support?" without scanning JSON arrays.

## Config Schema

`.agent-memory/config.json`:

```json
{
  "version": 1,
  "project_id": "proj_123",
  "git_mode": "local_only",
  "repeat_threshold": 2,
  "max_lessons_injected": 10,
  "max_context_tokens": 800,
  "min_signal_threshold": 0.4
}
```

`git_mode` values:

- `local_only`
- `commit_lessons`

## Extraction Pipeline

The v1 extractor is conservative:

```text
raw event
-> normalize
-> fingerprint
-> signal check
-> cluster
-> candidate pattern
-> rank
-> promote if approved or repeated
-> inject if relevant
```

### Normalize

Convert noisy raw events into stable summaries:

```text
command: npm test
exit_code: 1
stderr_signature: "Auth middleware rejects valid session"
files_touched: ["src/auth/middleware.ts", "src/auth/session.ts"]
user_correction: "Don't use cached session state here"
```

Remove timestamps, temp paths, unstable line numbers, ANSI output, stack trace noise, and huge stderr bodies.

### Basic Redaction

Before storing stderr or user text, v1 strips obvious secrets matching:

- `sk-`
- `ghp_`
- `Bearer `
- `password=`
- `secret=`

Broader redaction is v2.

### Fingerprint

Generate a repeatable fingerprint from:

```text
event_type
command family
error signature
top relevant files
user correction keywords
project_type
```

Example:

```text
failed_command:npm-test:auth-middleware-valid-session:src/auth:next.js
```

Fingerprints are useful but brittle. Clustering uses exact fingerprint match first, then fuzzy fallback with overlapping files, command family, and error terms.

### Signal Check

If the event has too little signal, log it but do not cluster it.

Low-signal cases include:

- empty stderr
- unknown command with no touched files
- interrupted command
- external service unavailable
- network outage
- missing dependency install

Flaky test guardrail:

If the same failure appears multiple times with no file changes between runs, treat it as likely flaky or environmental. Log the raw event, but do not promote or cluster it into a lesson without manual approval.

### Cluster

Cluster events when they show:

- exact or near-exact fingerprint match
- overlapping files
- overlapping error terms
- same command family
- same user correction theme

If similarity crosses the threshold, increment `repeat_count` and update `last_seen`. Otherwise create a new pending candidate.

### Candidate Drafting

Draft a compact candidate:

```text
Title: Avoid cached session state in auth middleware
Failure pattern: Tests fail around valid session handling in middleware.
Suspected cause: The agent reaches for cached session state even though this project requires direct user verification.
Recommended fix: Verify the user directly before authorization checks.
Evidence: 2 failed test runs, 1 user correction.
```

## Ranking

The extractor computes a numeric score from `0.0` to `1.0`, capped at `1.0`.

Display mapping:

```text
0.00-0.39 = low
0.40-0.74 = medium
0.75-1.00 = high
```

Initial additive score factors:

```text
+ repeated failure count
+ explicit user correction
+ same files involved repeatedly
+ same command family repeatedly
+ recent validation
+ manual approval
- old or stale lesson
- disabled or rejected related candidate
- overly broad scope
- repeated injections without recurring failures
```

Injection history matters. If a lesson has been injected repeatedly and the failure has not recurred, it should be deprioritized.

## Promotion

V1 promotion rules:

```text
manual approval
repeat_count >= config.repeat_threshold
```

Default `repeat_threshold` is `2`.

Manual approval can promote immediately. Repeat-threshold promotion should use modest wording unless an explicit user correction exists.

## Injection Ranking

Before session start, select lessons by:

```text
enabled only
same project
matching project_type if known
scope relevance
confidence score
recency
injection history
max_lessons_injected
max_context_tokens
```

After a failure, retrieve more narrowly:

```text
same command family
similar stderr signature
overlapping files
recent/high-confidence lessons first
```

The extractor may suggest memory. Only promoted lessons may instruct Claude.

## Inspectability

Memory must be inspectable and reversible.

The developer can ask:

- What did you remember?
- Why are you injecting this?
- Where did this lesson come from?
- How do I remove it?

`memory why <lesson-id>` traces:

```text
raw event -> candidate pattern -> promoted lesson -> injection history
```

## Risks And Mitigations

### Bad Memory Becomes Bad Instruction

This is the highest-risk failure mode. V1 mitigates it with:

- raw event / candidate / lesson separation
- manual approval or repeat threshold
- conservative signal checks
- `memory why`
- soft disabling through `disabled_at`

### Context Pollution

True lessons can still be harmful if injected everywhere. V1 mitigates this with:

- scoped triggers
- confidence ranking
- `max_lessons_injected`
- `max_context_tokens`
- injection-history decay

### Privacy Leakage

Raw events may include private paths, stderr, or user corrections. V1 mitigates this with:

- local-only default
- raw events never committed
- optional promoted lesson export only
- basic secret redaction before storage

## V2 Direction

V2 can add:

- Claude Code hooks for richer capture
- semantic diff-assisted candidate suggestions
- confidence decay
- lesson revalidation
- stronger redaction
- better project-type inference
- queryable `candidate_events` and `lesson_events` join tables

## V3 Direction

V3 can add:

- live session nudges
- optional team sharing
- cross-project anonymized pattern libraries
- Codex adapter support
- network-effect lessons by `project_type`
