# -*- coding: utf-8 -*-
"""codex_insights.py — Claude Code /insights-style pipeline for Codex sessions.

Pipeline stages (mirrors Claude Code's usage-data architecture):
  extract    Parse Codex session JSONL files into per-session metadata cache
             (insights-data/session-meta/<id>.json). Incremental: existing
             session IDs are skipped unless --force.
  digest     For sessions that have metadata but no LLM facet classification,
             write a compact digest (insights-data/digests/<id>.md) that the
             Codex agent reads to produce facets/<id>.json.
  aggregate  Combine session-meta + facets into insights-data/aggregate.json.
  render     Render a single-file HTML dashboard from aggregate.json plus the
             agent-written narrative.json (placeholders when missing).
  run        extract -> digest -> aggregate -> render in one pass.

All file IO is UTF-8. Korean paths are safe because everything goes through
Python's unicode-native APIs.
"""

import argparse
import html
import io
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

USERPROFILE = os.environ.get("USERPROFILE") or os.path.expanduser("~")
CODEX_HOME = os.path.join(USERPROFILE, ".codex")
SESSIONS_ROOT = os.path.join(CODEX_HOME, "sessions")
DATA_ROOT = os.path.join(CODEX_HOME, "insights-data")
REPORTS_ROOT = os.path.join(CODEX_HOME, "memories", "reports")

META_DIR = os.path.join(DATA_ROOT, "session-meta")
FACETS_DIR = os.path.join(DATA_ROOT, "facets")
DIGESTS_DIR = os.path.join(DATA_ROOT, "digests")
AGGREGATE_PATH = os.path.join(DATA_ROOT, "aggregate.json")
NARRATIVE_PATH = os.path.join(DATA_ROOT, "narrative.json")

NOISE_PATTERNS = [
    r"^# AGENTS\.md instructions",
    r"<task> Run a stop-gate review",
    r"Only review the work from the previous Claude turn",
    r"--- project-doc ---",
    r"^<environment_context>",
    r"^<turn_aborted>",
    r"^<user_interrupt>",
    r"^<system-reminder>",
]
NOISE_RE = [re.compile(p) for p in NOISE_PATTERNS]

LANG_EXT = {
    "py": "Python", "js": "JavaScript", "ts": "TypeScript", "tsx": "TypeScript",
    "jsx": "JavaScript", "html": "HTML", "css": "CSS", "md": "Markdown",
    "json": "JSON", "ps1": "PowerShell", "psm1": "PowerShell", "sh": "Shell",
    "bash": "Shell", "yaml": "YAML", "yml": "YAML", "toml": "TOML",
    "sql": "SQL", "csv": "CSV", "xlsx": "Excel", "hwpx": "HWPX",
    "java": "Java", "rs": "Rust", "go": "Go", "c": "C", "cpp": "C++",
}
LANG_RE = re.compile(r"[\w가-힣./\\-]+\.(" + "|".join(LANG_EXT) + r")\b", re.IGNORECASE)

ERROR_CATEGORY_RULES = [
    ("Permission / Auth", re.compile(r"\b401\b|\b403\b|OAuth|permission denied|unauthorized|forbidden|access (?:is )?denied", re.I)),
    ("Path / Not Found", re.compile(r"cannot find path|no such file|not found|존재하지 않|찾을 수 없", re.I)),
    ("Sandbox / Approval", re.compile(r"sandbox|approval|escalat", re.I)),
    ("Timeout", re.compile(r"timed? ?out", re.I)),
    ("Encoding / Korean", re.compile(r"unicodedecodeerror|encoding|codec|mojibake", re.I)),
]
EXIT_CODE_RE = re.compile(r"(?:exited with code|exit code:?)\s*([0-9]+)", re.I)


def iso_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def is_noise(text):
    if not text or not text.strip():
        return True
    return any(rx.search(text) for rx in NOISE_RE)


def read_jsonl(path):
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def content_text(content):
    if isinstance(content, str):
        return content
    parts = []
    for chunk in content or []:
        if isinstance(chunk, str):
            parts.append(chunk)
        elif isinstance(chunk, dict):
            for key in ("text", "output_text", "message"):
                val = chunk.get(key)
                if isinstance(val, str) and val.strip():
                    parts.append(val)
    return "\n".join(parts)


def categorize_error(output):
    for name, rx in ERROR_CATEGORY_RULES:
        if rx.search(output):
            return name
    return "Command Failed"


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------

def list_session_files(since=None, until=None, limit=0):
    files = []
    for root, _dirs, names in os.walk(SESSIONS_ROOT):
        for name in names:
            if name.endswith(".jsonl"):
                full = os.path.join(root, name)
                files.append((os.path.getmtime(full), full))
    files.sort()
    if since is not None:
        files = [f for f in files if datetime.fromtimestamp(f[0]) >= since]
    if until is not None:
        end = datetime(until.year, until.month, until.day, 23, 59, 59)
        files = [f for f in files if datetime.fromtimestamp(f[0]) <= end]
    if limit > 0:
        files = files[-limit:]
    return [f[1] for f in files]


def session_id_from_path(path):
    base = os.path.basename(path).rsplit(".", 1)[0]
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", base)
    return m.group(1) if m else base


def extract_session(path):
    sid = session_id_from_path(path)
    meta = {
        "session_id": sid,
        "source_file": path,
        "project_path": None,
        "model": None,
        "cli_version": None,
        "start_time": None,
        "end_time": None,
        "duration_minutes": 0,
        "user_message_count": 0,
        "assistant_message_count": 0,
        "tool_counts": {},
        "command_heads": {},
        "languages": {},
        "git_commits": 0,
        "git_pushes": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "first_prompt": None,
        "user_interruptions": 0,
        "user_response_times": [],
        "tool_errors": 0,
        "tool_error_categories": {},
        "error_snippets": [],
        "uses_mcp": False,
        "uses_web": False,
        "lines_added": 0,
        "lines_removed": 0,
        "files_modified": 0,
        "message_hours": [],
        "user_messages": [],
        "last_agent_message": None,
    }
    tool_counts = Counter()
    command_heads = Counter()
    languages = Counter()
    error_categories = Counter()
    modified_files = set()
    first_ts = last_ts = None
    last_agent_ts = None
    # event_msg counts are canonical; response_item kept as fallback for old schemas
    ev_user = ev_assistant = ri_user = ri_assistant = 0
    ri_user_texts = []

    for obj in read_jsonl(path):
        otype = obj.get("type")
        payload = obj.get("payload") or {}
        ptype = payload.get("type")
        ts = parse_ts(obj.get("timestamp"))
        if ts:
            first_ts = ts if first_ts is None or ts < first_ts else first_ts
            last_ts = ts if last_ts is None or ts > last_ts else last_ts

        if otype == "session_meta":
            meta["project_path"] = payload.get("cwd")
            meta["cli_version"] = payload.get("cli_version")
        elif otype == "turn_context":
            meta["model"] = payload.get("model") or meta["model"]
        elif otype == "event_msg" and ptype == "user_message":
            text = str(payload.get("message") or "")
            if "<turn_aborted>" in text or "<user_interrupt>" in text:
                meta["user_interruptions"] += 1
            if not is_noise(text):
                ev_user += 1
                clean = re.sub(r"\s+", " ", text).strip()
                meta["user_messages"].append(clean[:300])
                if meta["first_prompt"] is None:
                    meta["first_prompt"] = clean[:300]
                if ts:
                    meta["message_hours"].append(ts.astimezone().hour)
                    if last_agent_ts:
                        gap = (ts - last_agent_ts).total_seconds()
                        if 0 < gap < 3600:
                            meta["user_response_times"].append(round(gap, 1))
        elif otype == "event_msg" and ptype == "agent_message":
            text = str(payload.get("message") or "")
            if text.strip():
                ev_assistant += 1
                meta["last_agent_message"] = re.sub(r"\s+", " ", text).strip()[:600]
                if ts:
                    last_agent_ts = ts
        elif otype == "event_msg" and ptype == "token_count":
            usage = (payload.get("info") or {}).get("total_token_usage") or {}
            meta["input_tokens"] = usage.get("input_tokens", meta["input_tokens"])
            meta["output_tokens"] = usage.get("output_tokens", meta["output_tokens"])
            meta["total_tokens"] = usage.get("total_tokens", meta["total_tokens"])
        elif otype == "response_item" and ptype == "message":
            role = payload.get("role")
            text = content_text(payload.get("content"))
            if role == "user" and not is_noise(text):
                ri_user += 1
                ri_user_texts.append(re.sub(r"\s+", " ", text).strip()[:300])
            elif role == "assistant" and text.strip():
                ri_assistant += 1
        elif otype == "response_item" and ptype == "function_call":
            name = payload.get("name") or "unknown_tool"
            tool_counts[name] += 1
            if name.startswith("mcp__") or "." in name and name not in ("apply_patch",):
                meta["uses_mcp"] = True
            if "web" in name.lower() or "search" in name.lower():
                meta["uses_web"] = True
            args = str(payload.get("arguments") or "")
            try:
                parsed = json.loads(args) if args else {}
            except json.JSONDecodeError:
                parsed = {}
            cmd = ""
            if isinstance(parsed, dict):
                cmd = parsed.get("cmd") or parsed.get("command") or ""
                if isinstance(cmd, list):
                    cmd = " ".join(str(c) for c in cmd)
            cmd = str(cmd)
            if cmd.strip():
                head = cmd.strip().split()[0]
                head = os.path.basename(head.strip('"\''))
                # drop PS variables, keywords, and statement fragments
                if re.fullmatch(r"[A-Za-z][\w.-]*", head) and head.lower() not in (
                        "if", "foreach", "while", "try", "do", "function", "param", "set", "echo"):
                    command_heads[head] += 1
                if re.search(r"\bgit\b.*\bcommit\b", cmd):
                    meta["git_commits"] += 1
                if re.search(r"\bgit\b.*\bpush\b", cmd):
                    meta["git_pushes"] += 1
            scan_text = cmd or args
            for m in LANG_RE.finditer(scan_text):
                languages[LANG_EXT[m.group(1).lower()]] += 1
            if "*** Begin Patch" in args or name == "apply_patch":
                patch = parsed.get("input") or parsed.get("patch") or args if isinstance(parsed, dict) else args
                patch = str(patch)
                for fm in re.finditer(r"\*\*\* (?:Update|Add|Delete) File: (.+)", patch):
                    modified_files.add(fm.group(1).strip())
                meta["lines_added"] += len(re.findall(r"(?:^|\\n|\n)\+(?!\+\+)", patch))
                meta["lines_removed"] += len(re.findall(r"(?:^|\\n|\n)-(?!--)", patch))
        elif otype == "response_item" and ptype == "function_call_output":
            output = str(payload.get("output") or "")
            em = EXIT_CODE_RE.search(output)
            if em and em.group(1) != "0":
                meta["tool_errors"] += 1
                error_categories[categorize_error(output)] += 1
                snippet = re.sub(r"\s+", " ", output).strip()[:200]
                if len(meta["error_snippets"]) < 8:
                    meta["error_snippets"].append(snippet)
            elif re.search(r"\b(error|exception|failed|denied)\b", output, re.I) and not em:
                cat = categorize_error(output)
                if cat != "Command Failed":
                    error_categories[cat] += 1

    meta["user_message_count"] = ev_user if ev_user else ri_user
    meta["assistant_message_count"] = ev_assistant if ev_assistant else ri_assistant
    if not meta["user_messages"] and ri_user_texts:
        meta["user_messages"] = ri_user_texts[:20]
        meta["first_prompt"] = ri_user_texts[0] if ri_user_texts else None
    meta["user_messages"] = meta["user_messages"][:20]
    if first_ts and last_ts:
        meta["start_time"] = first_ts.isoformat()
        meta["end_time"] = last_ts.isoformat()
        meta["duration_minutes"] = round((last_ts - first_ts).total_seconds() / 60)
    meta["tool_counts"] = dict(tool_counts)
    meta["command_heads"] = dict(command_heads)
    meta["languages"] = dict(languages)
    meta["tool_error_categories"] = dict(error_categories)
    meta["files_modified"] = len(modified_files)
    return meta


def cmd_extract(args):
    os.makedirs(META_DIR, exist_ok=True)
    files = list_session_files(args.since, args.until, args.limit)
    written = skipped = empty = 0
    for path in files:
        sid = session_id_from_path(path)
        out = os.path.join(META_DIR, sid + ".json")
        if os.path.exists(out) and not args.force:
            # refresh if the session file grew since extraction
            if os.path.getmtime(out) >= os.path.getmtime(path):
                skipped += 1
                continue
        meta = extract_session(path)
        if meta["user_message_count"] == 0 and meta["assistant_message_count"] == 0:
            empty += 1
            continue
        with io.open(out, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
        written += 1
    print(json.dumps({
        "stage": "extract", "scanned": len(files), "written": written,
        "skipped_cached": skipped, "skipped_empty": empty,
        "meta_dir": META_DIR,
    }, ensure_ascii=False))


# --------------------------------------------------------------------------
# digest
# --------------------------------------------------------------------------

def load_meta_in_scope(limit=0):
    metas = []
    if not os.path.isdir(META_DIR):
        return metas
    for name in os.listdir(META_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with io.open(os.path.join(META_DIR, name), encoding="utf-8") as fh:
                metas.append(json.load(fh))
        except (json.JSONDecodeError, OSError):
            continue
    metas.sort(key=lambda m: m.get("start_time") or "")
    if limit > 0:
        metas = metas[-limit:]
    return metas


def cmd_digest(args):
    os.makedirs(DIGESTS_DIR, exist_ok=True)
    os.makedirs(FACETS_DIR, exist_ok=True)
    metas = load_meta_in_scope(args.limit)
    pending = []
    done = 0
    for meta in metas:
        sid = meta["session_id"]
        if os.path.exists(os.path.join(FACETS_DIR, sid + ".json")):
            done += 1
            continue
        if meta.get("user_message_count", 0) == 0:
            continue
        lines = [
            "# Session digest: " + sid,
            "- project: " + str(meta.get("project_path")),
            "- start: " + str(meta.get("start_time")),
            "- duration_minutes: " + str(meta.get("duration_minutes")),
            "- user/assistant messages: %s/%s" % (meta.get("user_message_count"), meta.get("assistant_message_count")),
            "- tool calls: " + json.dumps(meta.get("tool_counts", {}), ensure_ascii=False),
            "- tool errors: %s %s" % (meta.get("tool_errors"), json.dumps(meta.get("tool_error_categories", {}), ensure_ascii=False)),
            "- interruptions: " + str(meta.get("user_interruptions")),
            "",
            "## User messages",
        ]
        for um in meta.get("user_messages", [])[:15]:
            lines.append("- " + um[:200])
        if meta.get("last_agent_message"):
            lines += ["", "## Final assistant message", meta["last_agent_message"][:500]]
        if meta.get("error_snippets"):
            lines += ["", "## Error snippets"]
            for es in meta["error_snippets"][:5]:
                lines.append("- " + es)
        with io.open(os.path.join(DIGESTS_DIR, sid + ".md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        pending.append(sid)
    print(json.dumps({
        "stage": "digest", "sessions_in_scope": len(metas),
        "facets_done": done, "facets_pending": len(pending),
        "pending_ids": pending, "digests_dir": DIGESTS_DIR, "facets_dir": FACETS_DIR,
    }, ensure_ascii=False, indent=1))


# --------------------------------------------------------------------------
# aggregate
# --------------------------------------------------------------------------

def load_facets():
    facets = {}
    if not os.path.isdir(FACETS_DIR):
        return facets
    for name in os.listdir(FACETS_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with io.open(os.path.join(FACETS_DIR, name), encoding="utf-8") as fh:
                data = json.load(fh)
            facets[data.get("session_id") or name[:-5]] = data
        except (json.JSONDecodeError, OSError):
            continue
    return facets


def top_n(counter, n):
    return [{"name": k, "count": v} for k, v in counter.most_common(n)]


def cmd_aggregate(args):
    metas = load_meta_in_scope(args.limit)
    facets = load_facets()
    if not metas:
        print(json.dumps({"stage": "aggregate", "error": "no session metadata; run extract first"}))
        return

    tools = Counter()
    heads = Counter()
    langs = Counter()
    err_cats = Counter()
    goal_cats = Counter()
    session_types = Counter()
    outcomes = Counter()
    satisfaction = Counter()
    friction = Counter()
    hours = Counter()
    weekdays = Counter()
    projects = Counter()
    summaries = []
    total = {
        "sessions": len(metas), "user_messages": 0, "assistant_messages": 0,
        "lines_added": 0, "lines_removed": 0, "files_modified": 0,
        "git_commits": 0, "git_pushes": 0, "tool_errors": 0,
        "interruptions": 0, "tool_calls": 0, "output_tokens": 0,
        "duration_minutes": 0,
    }
    dates = []
    response_times = []

    for m in metas:
        total["user_messages"] += m.get("user_message_count", 0)
        total["assistant_messages"] += m.get("assistant_message_count", 0)
        total["lines_added"] += m.get("lines_added", 0)
        total["lines_removed"] += m.get("lines_removed", 0)
        total["files_modified"] += m.get("files_modified", 0)
        total["git_commits"] += m.get("git_commits", 0)
        total["git_pushes"] += m.get("git_pushes", 0)
        total["tool_errors"] += m.get("tool_errors", 0)
        total["interruptions"] += m.get("user_interruptions", 0)
        total["output_tokens"] += m.get("output_tokens", 0)
        total["duration_minutes"] += m.get("duration_minutes", 0)
        tools.update(m.get("tool_counts", {}))
        total["tool_calls"] += sum(m.get("tool_counts", {}).values())
        heads.update(m.get("command_heads", {}))
        langs.update(m.get("languages", {}))
        err_cats.update(m.get("tool_error_categories", {}))
        for h in m.get("message_hours", []):
            hours[h] += 1
        ts = parse_ts(m.get("start_time"))
        if ts:
            dates.append(ts)
            weekdays[ts.astimezone().strftime("%a")] += 1
        proj = m.get("project_path") or "unknown"
        projects[proj] += 1
        response_times.extend(m.get("user_response_times", []))

        facet = facets.get(m["session_id"])
        if facet:
            goal_cats.update(facet.get("goal_categories", {}))
            if facet.get("session_type"):
                session_types[facet["session_type"]] += 1
            if facet.get("outcome"):
                outcomes[facet["outcome"]] += 1
            sat = facet.get("user_satisfaction")
            if isinstance(sat, str) and sat:
                satisfaction[sat] += 1
            elif isinstance(facet.get("user_satisfaction_counts"), dict):
                satisfaction.update(facet["user_satisfaction_counts"])
            friction.update(facet.get("friction_counts", {}))
            if facet.get("brief_summary"):
                summaries.append({
                    "session_id": m["session_id"],
                    "start_time": m.get("start_time"),
                    "summary": facet["brief_summary"],
                    "goal": facet.get("underlying_goal"),
                    "outcome": facet.get("outcome"),
                })

    dates.sort()
    date_min = dates[0].astimezone().strftime("%Y-%m-%d") if dates else None
    date_max = dates[-1].astimezone().strftime("%Y-%m-%d") if dates else None
    active_days = len({d.astimezone().strftime("%Y-%m-%d") for d in dates})
    days_span = max(1, (dates[-1] - dates[0]).days + 1) if dates else 1
    total_msgs = total["user_messages"] + total["assistant_messages"]
    avg_rt = round(sum(response_times) / len(response_times), 1) if response_times else None

    facet_coverage = sum(1 for m in metas if m["session_id"] in facets)
    aggregate = {
        "generated": iso_now(),
        "scope": {"sessions": len(metas), "date_min": date_min, "date_max": date_max,
                  "active_days": active_days, "days_span": days_span,
                  "facet_coverage": facet_coverage,
                  "facet_coverage_pct": round(100.0 * facet_coverage / len(metas), 1)},
        "totals": total,
        "derived": {
            "total_messages": total_msgs,
            "messages_per_active_day": round(total_msgs / max(1, active_days), 1),
            "avg_tool_calls_per_session": round(total["tool_calls"] / len(metas), 1),
            "avg_session_minutes": round(total["duration_minutes"] / len(metas), 1),
            "avg_user_response_seconds": avg_rt,
            "error_rate_per_session": round(total["tool_errors"] / len(metas), 1),
            "interruption_rate_pct": round(100.0 * total["interruptions"] / max(1, len(metas)), 1),
        },
        "top_tools": top_n(tools, 12),
        "command_heads": top_n(heads, 12),
        "languages": top_n(langs, 10),
        "error_categories": top_n(err_cats, 10),
        "goal_categories": top_n(goal_cats, 12),
        "session_types": top_n(session_types, 8),
        "outcomes": top_n(outcomes, 6),
        "satisfaction": top_n(satisfaction, 6),
        "friction_counts": top_n(friction, 10),
        "hour_histogram": [{"hour": h, "count": hours.get(h, 0)} for h in range(24)],
        "weekday_histogram": [{"day": d, "count": weekdays.get(d, 0)}
                              for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]],
        "projects": top_n(projects, 10),
        "session_summaries": summaries[-60:],
    }
    os.makedirs(DATA_ROOT, exist_ok=True)
    with io.open(AGGREGATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(aggregate, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"stage": "aggregate", "path": AGGREGATE_PATH,
                      "sessions": len(metas), "facet_coverage": facet_coverage},
                     ensure_ascii=False))


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------

CSS = """
:root{--bg:#faf9f5;--card:#ffffff;--ink:#1f1e1d;--muted:#6e6b64;--accent:#c96442;
--accent2:#2f7e6d;--line:#e8e5de;--bar:#d97757;--barbg:#f0ede6;--code:#f4f1ea;}
*{box-sizing:border-box}
body{margin:0;font-family:'Segoe UI','Malgun Gothic',system-ui,sans-serif;background:var(--bg);color:var(--ink);line-height:1.55}
.container{max-width:980px;margin:0 auto;padding:32px 24px 80px}
h1{font-size:30px;margin:0 0 4px}
h2{font-size:21px;margin:44px 0 14px;padding-top:18px;border-top:1px solid var(--line)}
.meta-line{color:var(--muted);font-size:14px;margin-bottom:24px}
.nav-toc{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 6px}
.nav-toc a{font-size:13px;color:var(--accent);text-decoration:none;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:4px 12px}
.stats-bar{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0}
.stat{flex:1 1 120px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;text-align:center}
.stat .v{font-size:22px;font-weight:700}
.stat .k{font-size:12px;color:var(--muted)}
.glance{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:12px 0}
.glance h3{margin:0 0 6px;font-size:15px;color:var(--accent)}
.glance p{margin:0;font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}
.card h3{margin:0 0 6px;font-size:15px}
.card .sub{color:var(--muted);font-size:12px;margin-bottom:6px}
.card p{margin:4px 0;font-size:14px}
.charts-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.chart-card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.chart-title{font-size:14px;font-weight:700;margin-bottom:10px}
.bar-row{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:13px}
.bar-label{flex:0 0 140px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-track{flex:1;background:var(--barbg);border-radius:4px;height:14px;overflow:hidden}
.bar-fill{background:var(--bar);height:100%;border-radius:4px}
.bar-value{flex:0 0 44px;text-align:right;color:var(--muted)}
.hourchart{display:flex;align-items:flex-end;gap:2px;height:90px;margin-top:8px}
.hourchart .hbar{flex:1;background:var(--bar);border-radius:2px 2px 0 0;min-height:2px}
.hourlabels{display:flex;gap:2px;font-size:9px;color:var(--muted)}
.hourlabels span{flex:1;text-align:center}
.placeholder{border:1px dashed var(--accent);background:#fdf6f2;color:#8a5a44;border-radius:12px;padding:14px 18px;font-size:13px;margin:12px 0}
.example-code,.cmd-code{background:var(--code);border-radius:6px;padding:8px 10px;font-family:Consolas,monospace;font-size:12px;white-space:pre-wrap;word-break:break-all;margin:6px 0}
.copy-btn{font-size:11px;border:1px solid var(--line);background:var(--card);border-radius:6px;padding:2px 8px;cursor:pointer;color:var(--muted)}
.copy-btn:hover{color:var(--accent);border-color:var(--accent)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--barbg)}
.foot{margin-top:40px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:14px}
.badge{display:inline-block;font-size:11px;border-radius:10px;padding:1px 8px;background:var(--barbg);color:var(--muted);margin-left:6px}
"""

COPY_JS = """
function copyText(btn){var code=btn.parentElement.querySelector('.cmd-code,.example-code');
if(!code)return;navigator.clipboard.writeText(code.innerText).then(function(){
btn.textContent='copied';setTimeout(function(){btn.textContent='copy';},1200);});}
"""


def esc(text):
    return html.escape(str(text)) if text is not None else ""


def bar_chart(title, items, total_width=None):
    if not items:
        return ""
    maxv = max(i["count"] for i in items) or 1
    rows = []
    for i in items:
        pct = max(2, round(100.0 * i["count"] / maxv))
        rows.append(
            '<div class="bar-row"><div class="bar-label" title="%s">%s</div>'
            '<div class="bar-track"><div class="bar-fill" style="width:%d%%"></div></div>'
            '<div class="bar-value">%s</div></div>'
            % (esc(i["name"]), esc(i["name"]), pct, i["count"]))
    return ('<div class="chart-card"><div class="chart-title">%s</div>%s</div>'
            % (esc(title), "".join(rows)))


def hour_chart(hist):
    maxv = max((h["count"] for h in hist), default=0) or 1
    bars = "".join(
        '<div class="hbar" style="height:%d%%" title="%02d시: %d"></div>'
        % (max(2, round(100.0 * h["count"] / maxv)), h["hour"], h["count"])
        for h in hist)
    labels = "".join("<span>%s</span>" % (h["hour"] if h["hour"] % 3 == 0 else "")
                     for h in hist)
    return ('<div class="chart-card"><div class="chart-title">Activity by Hour</div>'
            '<div class="hourchart">%s</div><div class="hourlabels">%s</div></div>'
            % (bars, labels))


def placeholder(section, hint):
    return ('<div class="placeholder"><b>%s</b> — narrative not generated yet. %s</div>'
            % (esc(section), esc(hint)))


def render_html(agg, narrative):
    n = narrative or {}
    scope = agg["scope"]
    t = agg["totals"]
    d = agg["derived"]
    parts = []
    parts.append("<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>")
    parts.append("<title>Codex Insights</title><style>%s</style></head><body>" % CSS)
    parts.append("<div class='container'>")
    parts.append("<h1>Codex Insights</h1>")
    parts.append("<div class='meta-line'>%s messages across %s sessions | %s to %s "
                 "<span class='badge'>facets %s/%s</span>"
                 "<span class='badge'>generated %s</span></div>"
                 % (d["total_messages"], scope["sessions"], esc(scope["date_min"]),
                    esc(scope["date_max"]), scope["facet_coverage"], scope["sessions"],
                    esc(agg["generated"])))

    parts.append("<div class='nav-toc'>")
    for anchor, label in [("glance", "At a Glance"), ("work", "What You Work On"),
                          ("how", "How You Use Codex"), ("wins", "Impressive Things"),
                          ("friction", "Where Things Go Wrong"),
                          ("features", "Features to Try"), ("patterns", "New Patterns"),
                          ("horizon", "On the Horizon"), ("presets", "Presets")]:
        parts.append("<a href='#%s'>%s</a>" % (anchor, label))
    parts.append("</div>")

    # stats bar
    stats = [
        (d["total_messages"], "Messages"),
        ("+%s/-%s" % (t["lines_added"], t["lines_removed"]), "Lines"),
        (t["files_modified"], "Files"),
        (scope["active_days"], "Days"),
        (d["messages_per_active_day"], "Msgs/Day"),
        (d["avg_tool_calls_per_session"], "Tools/Session"),
        (t["git_commits"], "Commits"),
        ("{:,}".format(t["output_tokens"]), "Output Tokens"),
    ]
    parts.append("<div class='stats-bar'>")
    for v, k in stats:
        parts.append("<div class='stat'><div class='v'>%s</div><div class='k'>%s</div></div>" % (esc(v), esc(k)))
    parts.append("</div>")

    # At a Glance
    parts.append("<h2 id='glance'>At a Glance</h2>")
    glance = n.get("at_a_glance") or {}
    glance_keys = [("whats_working", "What's working"),
                   ("whats_hindering", "What's hindering you"),
                   ("quick_wins", "Quick wins to try"),
                   ("ambitious", "Ambitious workflows")]
    if any(glance.get(k) for k, _ in glance_keys):
        for key, label in glance_keys:
            if glance.get(key):
                parts.append("<div class='glance'><h3>%s</h3><p>%s</p></div>"
                             % (esc(label), esc(glance[key])))
    else:
        parts.append(placeholder("At a Glance",
                                 "narrative.json의 at_a_glance를 작성하면 표시됩니다."))

    # What You Work On
    parts.append("<h2 id='work'>What You Work On</h2>")
    if n.get("work_areas"):
        for area in n["work_areas"]:
            parts.append("<div class='card'><h3>%s <span class='badge'>%s</span></h3><p>%s</p></div>"
                         % (esc(area.get("name")), esc(area.get("sessions", "")),
                            esc(area.get("description"))))
    else:
        parts.append(placeholder("Work areas",
                                 "narrative.json의 work_areas를 작성하면 표시됩니다."))

    # charts
    parts.append("<div class='charts-row'>")
    parts.append(bar_chart("What You Wanted", agg.get("goal_categories")[:8])
                 or placeholder("What You Wanted", "facet 분류 후 표시됩니다."))
    parts.append(bar_chart("Top Tools Used", agg.get("top_tools")[:8]))
    parts.append(bar_chart("Languages", agg.get("languages")[:8]))
    parts.append(bar_chart("Session Types", agg.get("session_types")[:6])
                 or placeholder("Session Types", "facet 분류 후 표시됩니다."))
    parts.append(bar_chart("Command Heads", agg.get("command_heads")[:8]))
    parts.append(bar_chart("Outcomes", agg.get("outcomes")[:6]) or "")
    parts.append(hour_chart(agg.get("hour_histogram", [])))
    parts.append(bar_chart("Weekday Activity", [
        {"name": w["day"], "count": w["count"]} for w in agg.get("weekday_histogram", [])]))
    parts.append("</div>")

    # How You Use
    parts.append("<h2 id='how'>How You Use Codex</h2>")
    if n.get("how_you_use"):
        parts.append("<div class='card'><p>%s</p></div>" % esc(n["how_you_use"]))
    else:
        parts.append(placeholder("How You Use Codex",
                                 "narrative.json의 how_you_use를 작성하면 표시됩니다."))

    # Impressive Things
    parts.append("<h2 id='wins'>Impressive Things You Did</h2>")
    if n.get("big_wins"):
        for win in n["big_wins"]:
            parts.append("<div class='card'><h3>%s</h3><p>%s</p></div>"
                         % (esc(win.get("title")), esc(win.get("description"))))
    else:
        parts.append(placeholder("Big wins",
                                 "narrative.json의 big_wins를 작성하면 표시됩니다."))

    # Where Things Go Wrong
    parts.append("<h2 id='friction'>Where Things Go Wrong</h2>")
    if n.get("friction_categories"):
        for fc in n["friction_categories"]:
            ex = "".join("<div class='example-code'>%s</div>" % esc(e)
                         for e in fc.get("examples", [])[:3])
            parts.append("<div class='card'><h3>%s</h3><p>%s</p>%s</div>"
                         % (esc(fc.get("title")), esc(fc.get("description")), ex))
    else:
        parts.append(placeholder("Friction narrative",
                                 "narrative.json의 friction_categories를 작성하면 표시됩니다."))
    det = agg.get("error_categories") or []
    fr = agg.get("friction_counts") or []
    if det or fr:
        parts.append("<div class='charts-row'>")
        parts.append(bar_chart("Deterministic Error Categories", det[:8]))
        if fr:
            parts.append(bar_chart("Facet Friction Signals", fr[:8]))
        parts.append("</div>")

    # Features to Try
    parts.append("<h2 id='features'>Existing Codex Features to Try</h2>")
    if n.get("features_to_try"):
        for f in n["features_to_try"]:
            parts.append("<div class='card'><h3>%s</h3><p>%s</p>" %
                         (esc(f.get("title")), esc(f.get("why"))))
            if f.get("example"):
                parts.append("<div class='example-code'>%s</div>"
                             "<button class='copy-btn' onclick='copyText(this)'>copy</button>"
                             % esc(f["example"]))
            parts.append("</div>")
    else:
        parts.append(placeholder("Features to try",
                                 "narrative.json의 features_to_try를 작성하면 표시됩니다."))

    # New Patterns
    parts.append("<h2 id='patterns'>New Ways to Use Codex</h2>")
    if n.get("new_patterns"):
        for p in n["new_patterns"]:
            parts.append("<div class='card'><h3>%s</h3><p>%s</p>"
                         % (esc(p.get("title")), esc(p.get("detail"))))
            if p.get("prompt"):
                parts.append("<div class='example-code'>%s</div>"
                             "<button class='copy-btn' onclick='copyText(this)'>copy</button>"
                             % esc(p["prompt"]))
            parts.append("</div>")
    else:
        parts.append(placeholder("New patterns",
                                 "narrative.json의 new_patterns를 작성하면 표시됩니다."))

    # Horizon
    parts.append("<h2 id='horizon'>On the Horizon</h2>")
    if n.get("horizon"):
        for hz in n["horizon"]:
            parts.append("<div class='card'><h3>%s</h3><p>%s</p><p class='sub'>%s</p></div>"
                         % (esc(hz.get("title")), esc(hz.get("possible")), esc(hz.get("tip", ""))))
    else:
        parts.append(placeholder("Horizon",
                                 "narrative.json의 horizon을 작성하면 표시됩니다."))

    # Presets (deterministic, kept from v1 strengths)
    parts.append("<h2 id='presets'>Copy/Paste Command Presets</h2>")
    presets = [
        ("Refresh insights", 'python "%USERPROFILE%\\.codex\\skills\\codex-insights\\scripts\\codex_insights.py" run --limit 50'),
        ("Weekly window", 'python "%USERPROFILE%\\.codex\\skills\\codex-insights\\scripts\\codex_insights.py" run --since 7d'),
        ("Re-render only", 'python "%USERPROFILE%\\.codex\\skills\\codex-insights\\scripts\\codex_insights.py" render'),
        ("Legacy markdown report", 'powershell -ExecutionPolicy Bypass -File "%USERPROFILE%\\.codex\\skills\\codex-insights\\scripts\\New-CodexInsightsReport.ps1" -Limit 30'),
    ]
    parts.append("<table><tr><th>Preset</th><th>Copy/paste</th><th></th></tr>")
    for name, cmd in presets:
        parts.append("<tr><td>%s</td><td><div class='cmd-code'>%s</div></td>"
                     "<td><button class='copy-btn' onclick='copyText(this.parentElement.previousElementSibling)'>copy</button></td></tr>"
                     % (esc(name), esc(cmd)))
    parts.append("</table>")

    parts.append("<div class='foot'>Counts are directional; Codex session schemas may evolve. "
                 "Facet coverage: %s/%s sessions. Narratives are written by the Codex agent from "
                 "aggregate.json + session facets; deterministic stats come from session logs only. "
                 "No secrets are echoed into this report.</div>" %
                 (scope["facet_coverage"], scope["sessions"]))
    parts.append("</div><script>%s</script></body></html>" % COPY_JS)
    return "".join(parts)


def parse_since(value):
    if value is None:
        return None
    m = re.fullmatch(r"(\d+)d", value.strip())
    if m:
        from datetime import timedelta
        return datetime.now() - timedelta(days=int(m.group(1)))
    return datetime.strptime(value, "%Y-%m-%d")


def cmd_render(args):
    if not os.path.exists(AGGREGATE_PATH):
        print(json.dumps({"stage": "render", "error": "aggregate.json missing; run aggregate first"}))
        sys.exit(1)
    with io.open(AGGREGATE_PATH, encoding="utf-8") as fh:
        agg = json.load(fh)
    narrative = None
    if os.path.exists(NARRATIVE_PATH):
        try:
            with io.open(NARRATIVE_PATH, encoding="utf-8") as fh:
                narrative = json.load(fh)
        except json.JSONDecodeError:
            narrative = None
    out_dir = args.out_dir or REPORTS_ROOT
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(out_dir, "codex-insights-%s.html" % stamp)
    html_text = render_html(agg, narrative)
    with io.open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_text)
    latest = os.path.join(out_dir, "codex-insights-report.html")
    with io.open(latest, "w", encoding="utf-8") as fh:
        fh.write(html_text)
    print(json.dumps({"stage": "render", "report": out_path, "alias": latest,
                      "narrative_present": narrative is not None,
                      "facet_coverage": agg["scope"]["facet_coverage"],
                      "sessions": agg["scope"]["sessions"]}, ensure_ascii=False))


def cmd_run(args):
    cmd_extract(args)
    cmd_digest(args)
    cmd_aggregate(args)
    cmd_render(args)


def main():
    ap = argparse.ArgumentParser(description="Codex insights pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("extract", cmd_extract), ("digest", cmd_digest),
                     ("aggregate", cmd_aggregate), ("render", cmd_render),
                     ("run", cmd_run)]:
        p = sub.add_parser(name)
        p.add_argument("--limit", type=int, default=50,
                       help="most recent N sessions in scope (0 = all)")
        p.add_argument("--since", type=parse_since, default=None,
                       help="YYYY-MM-DD or Nd (e.g. 7d)")
        p.add_argument("--until", type=parse_since, default=None)
        p.add_argument("--force", action="store_true",
                       help="re-extract even if cached")
        p.add_argument("--out-dir", default=None, help="report output directory")
        p.set_defaults(func=fn)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
