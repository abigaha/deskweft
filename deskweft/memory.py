"""Per-key memory: one Markdown file per app@version, plans embedded, trust split.

Storage is local to the user, never in the repository. A record is replaced
whole, so a torn write cannot leave a half plan behind; every write path goes
through one module-level lock covering read -> validate -> modify -> replace.
Only this process may write a memory root:
# shortcut: one memory root, one writing process; switch to an OS file lock
# before a second process (or an outside editor) may write the same directory.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from hashlib import sha256
from pathlib import Path

import yaml

SCHEMA = 1
DEFAULT_MAX_BODY_CHARS = 6000
_PLAN_ID = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")
# A heading close: "## 未解决" may carry trailing spaces but not swallow the
# newline that ends it, or the first line of the section goes missing.
_UNRESOLVED = re.compile(r"^##[ \t]*未解决[ \t]*$", re.M)
_HEADING = re.compile(r"^##[ \t]", re.M)
_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f]")

_write_lock = threading.Lock()


def _real_memory_root() -> Path:
    """The unpatched resolver; tests replace the module attribute `memory_root`."""
    configured = os.environ.get("DESKWEFT_MEMORY_DIR") or os.environ.get("WINMCP_MEMORY_DIR")
    return (Path(configured).expanduser() if configured else
            # Preserve the existing data directory so a rename never hides user memory.
            Path(os.environ["LOCALAPPDATA"]) / "winmcp" / "memory")


def memory_root() -> Path:
    return _real_memory_root()


def make_key(app: str, version: str | None) -> str:
    tag = "unversioned" if version is None else version.strip()
    return app.strip().casefold() + "@" + tag


def record_path(root: Path, key: str) -> Path:
    return root / "playbooks" / (sha256(key.encode("utf-8")).hexdigest() + ".md")


def rank(reviewed: bool, proven: bool) -> int:
    return int(reviewed) + 2 * int(proven)


def plan_revision(key: str, plan: dict) -> str:
    content = {field: plan[field] for field in
               ("id", "summary", "cost", "body", "uses_foreground")}
    content["key"] = key
    payload = json.dumps(content, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()


# ---------- validation ----------


class Invalid(Exception):
    """A record or argument that must not be written or trusted."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _check_name(value, kind: str) -> str:
    if not isinstance(value, str):
        raise Invalid(f"invalid {kind}", repr(value))
    text = value.strip()
    if not text or "@" in text or "/" in text or "\\" in text or _BAD_CHARS.search(text):
        raise Invalid(f"invalid {kind}", repr(value))
    return text


def _check_app(app) -> str:
    return _check_name(app, "app")


def _check_version(version) -> str | None:
    if version is None:
        return None
    text = _check_name(version, "version")
    if text.casefold() == "unversioned":
        raise Invalid("invalid version", "unversioned is reserved; pass None for an unknown version")
    return text


def _check_plan_id(plan_id) -> str:
    if not isinstance(plan_id, str) or not _PLAN_ID.match(plan_id):
        raise Invalid("invalid plan id", repr(plan_id))
    return plan_id


def _check_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Invalid("invalid plan", f"{field} must be a non-empty string")
    return value


def _check_int(value, low: int, high: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Invalid("invalid arguments", f"{field} must be an integer in {low}..{high}")
    return value


def _parse_plan(plan, key: str, app: str, version: str | None, index: int) -> dict:
    if not isinstance(plan, dict):
        raise Invalid("invalid record", f"plan #{index} is not a mapping")
    out = {}
    for field in ("id", "summary", "cost", "body"):
        value = plan.get(field)
        if not isinstance(value, str):
            raise Invalid("invalid record", f"plan #{index} field {field} must be a string")
        out[field] = value
    if not _PLAN_ID.match(out["id"]):
        raise Invalid("invalid record", f"plan id {out['id']!r} is not a valid id")
    for field in ("uses_foreground", "reviewed", "proven"):
        value = plan.get(field)
        if not isinstance(value, bool):
            raise Invalid("invalid record", f"plan {out['id']} field {field} must be a bool")
        out[field] = value
    if version is None and (out["reviewed"] or out["proven"]):
        raise Invalid("invalid record",
                      f"{key} is an unversioned observation; it cannot carry trust")
    return out


def _parse_record(text: str, key: str) -> dict:
    """Parse and strictly validate one record. Raises Invalid, never repairs."""
    try:
        data = yaml.safe_load(_frontmatter(text))
    except yaml.YAMLError as error:
        raise Invalid("invalid record", f"bad YAML: {error}") from None
    if not isinstance(data, dict):
        raise Invalid("invalid record", "frontmatter is not a mapping")
    if data.get("schema") != SCHEMA or isinstance(data.get("schema"), bool):
        raise Invalid("invalid record", f"unsupported schema {data.get('schema')!r}")
    if data.get("key") != key:
        raise Invalid("invalid record", f"key in file is {data.get('key')!r}, expected {key}")
    app, version = data.get("app"), data.get("version")
    if not isinstance(app, str) or not app.strip():
        raise Invalid("invalid record", "app must be a non-empty string")
    if version is not None and not isinstance(version, str):
        raise Invalid("invalid record", "version must be a string or null")
    if data.get("key") != make_key(app, version):
        raise Invalid("invalid record", "key does not match app and version")
    updated = data.get("updated")
    if not isinstance(updated, str):
        raise Invalid("invalid record", "updated must be an ISO date string")
    verified = data.get("verified_with")
    if verified is not None and not isinstance(verified, str):
        raise Invalid("invalid record", "verified_with must be a string")
    record = {"schema": SCHEMA, "key": key, "app": app, "version": version, "updated": updated,
              "verified_with": verified}
    if "see" in data:
        source = data["see"]
        if "plans" in data:
            raise Invalid("invalid record", "see and plans are mutually exclusive")
        if not isinstance(source, str) or source == key:
            raise Invalid("invalid record", f"see {source!r} cannot point at itself")
        record["see"] = source
        return record
    plans = data.get("plans")
    if not isinstance(plans, list) or not plans:
        raise Invalid("invalid record", "plans must be a non-empty list")
    record["plans"] = [_parse_plan(plan, key, app, version, i) for i, plan in enumerate(plans)]
    if version is None and any(plan["reviewed"] or plan["proven"] for plan in record["plans"]):
        raise Invalid("invalid record",
                      f"{key} is an unversioned observation; it cannot carry trust")
    ids = [plan["id"] for plan in record["plans"]]
    if len(set(ids)) != len(ids):
        raise Invalid("invalid record", "duplicate plan id")
    return record


# ---------- storage ----------


class _Str(str):
    """A str subclass so the dumper can pick block style for multi-line text."""


def _represent_str(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


class _Dumper(yaml.SafeDumper):
    pass


# _Str is a str subclass, so represent_data() finds it through this exact class.
_Dumper.add_representer(_Str, _represent_str)


def _serialize(record: dict) -> str:
    data = {"schema": record["schema"], "key": record["key"], "app": record["app"],
            "version": record["version"], "updated": record["updated"]}
    if record.get("verified_with") is not None:
        data["verified_with"] = record["verified_with"]
    if "see" in record:
        data["see"] = record["see"]
    else:
        data["plans"] = [{field: plan[field] for field in
                          ("id", "summary", "cost", "uses_foreground", "reviewed", "proven")}
                         | {"body": _Str(plan["body"])} for plan in record["plans"]]
    text = yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=4096)
    return "---\n" + text + "---\n"


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        raise Invalid("invalid record", "missing leading --- line")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise Invalid("invalid record", "unterminated frontmatter")
    if text[end + 5:].strip():
        raise Invalid("invalid record", "content after the closing --- line")
    # Keep the newline that ends the last line: a block scalar's final break is
    # part of its value, and clipping it here would silently trim every body.
    return text[4:end + 1]


def _read(root: Path, path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise Invalid("plan not found", f"{path.name} does not exist") from None
    except OSError as error:
        raise Invalid("read failed", f"{type(error).__name__}: {error}") from None
    try:
        declared = yaml.safe_load(_frontmatter(text))
    except yaml.YAMLError as error:
        raise Invalid("invalid record", f"bad YAML: {error}") from None
    if not isinstance(declared, dict) or not isinstance(declared.get("key"), str):
        raise Invalid("invalid record", "frontmatter has no string key")
    key = declared["key"]
    if record_path(root, key) != path:
        raise Invalid("invalid record", "record is not stored under its own key's path")
    return _parse_record(text, key)


def _write(path: Path, record: dict) -> None:
    """Serialize and validate first, then one atomic replace. Caller holds the lock."""
    serialized = _serialize(record)
    _parse_record(serialized, record["key"])  # a record that cannot be read back must not be stored
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise Invalid("write failed", f"{type(error).__name__}: {error}") from None
    finally:
        Path(temporary).unlink(missing_ok=True)


def _load_key(root: Path, key: str, level: int = 0) -> dict:
    """Load one key, following `see` exactly once."""
    path = record_path(root, key)
    record = _read(root, path)
    record["_path"] = path
    if "see" not in record:
        return record
    if level:
        raise Invalid("invalid record", "inheritance chains are not followed past one level")
    source_key = record["see"]
    try:
        source = _load_key(root, source_key, level + 1)
    except Invalid as error:
        raise Invalid("invalid record",
                      f"see {source_key!r} is unreadable: {error.reason}: {error.detail}") from None
    if "see" in source:
        raise Invalid("invalid record", f"{source_key} is itself an inherited record")
    record["_source"] = source
    return record


def _scan(root: Path) -> tuple[list[dict], list[dict]]:
    """Every readable record under playbooks/, plus warnings for the rest."""
    folder = root / "playbooks"
    records: list[dict] = []
    warnings: list[dict] = []
    if not folder.is_dir():
        return records, warnings
    for path in sorted(folder.glob("*.md")):
        try:
            record = _read(root, path)
        except Invalid as error:
            warnings.append({"file": path.name, "reason": f"{error.reason}: {error.detail}"})
            continue
        record["_path"] = path
        if "see" in record:
            try:
                source = _load_key(root, record["see"], 1)
            except Invalid as error:
                warnings.append({"file": path.name, "reason": f"{error.reason}: {error.detail}"})
                continue
            record["_source"] = source
        records.append(record)
    return records, warnings


# ---------- unresolved gaps ----------


def _unresolved_text(body: str) -> str | None:
    match = _UNRESOLVED.search(body)
    if match is None:
        return None
    start = match.end()
    following = _HEADING.search(body, start)
    text = (body[start:following.start()] if following else body[start:]).strip()
    return text or None


def unresolved() -> list[dict]:
    """Every `## 未解决` section in stored bodies: (key, plan_id, text)."""
    root = memory_root()
    records, _ = _scan(root)
    gaps: list[dict] = []
    for record in records:
        plans = _plans(record)
        for plan in plans:
            text = _unresolved_text(plan["body"])
            if text is not None:
                gaps.append({"key": record["key"], "plan_id": plan["id"], "text": text})
    return gaps


def _plans(record: dict) -> list[dict]:
    if "see" not in record:
        return record["plans"]
    return record["_source"]["plans"]


# ---------- recall ----------


def _app_of(query: str) -> str | None:
    if "\\" in query or "/" in query or query.casefold().endswith(".exe"):
        from pathlib import PureWindowsPath

        stem = PureWindowsPath(query).stem
        return stem.strip() or None
    return None


def _match_plan(record: dict, plan_id: str) -> dict | None:
    for plan in _plans(record):
        if plan["id"] == plan_id:
            return plan
    return None


def _as_plan(key: str, plan: dict, inherited: bool, budget: list[int], offset: int = 0) -> dict:
    total = len(plan["body"])
    remaining = max(0, budget[0])
    piece = plan["body"][offset:offset + remaining]
    budget[0] -= len(piece)
    end = offset + len(piece)
    revision = plan_revision(key, plan)
    return {
        "id": plan["id"], "summary": plan["summary"], "cost": plan["cost"],
        "uses_foreground": plan["uses_foreground"],
        "reviewed": False if inherited else plan["reviewed"],
        "proven": False if inherited else plan["proven"],
        "rank": 0 if inherited else rank(plan["reviewed"], plan["proven"]),
        "body": piece, "truncated": bool(offset or end < total), "revision": revision,
        "body_offset": offset, "body_total_chars": total,
        "next_body_offset": end if end < total else None,
    }


def _as_match(root: Path, record: dict, budget: list[int], plans: list[dict] | None = None) -> dict:
    inherited = "see" in record
    key = record["key"]
    if plans is None:
        order = sorted(_plans(record), key=lambda p: (
            -rank(p["reviewed"], p["proven"]) if not inherited else 0, p["id"]))
        plans = [_as_plan(key, plan, inherited, budget) for plan in order]
    return {
        "key": key, "app": record["app"], "version": record["version"],
        "version_unknown": record["version"] is None,
        "inherits": record["see"] if inherited else None,
        "plans": plans,
        "unresolved": [],
    }


def recall(query: str, max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
           plan_id: str = "", body_offset: int = 0) -> dict:
    try:
        if not isinstance(query, str):
            raise Invalid("invalid query", repr(query))
        text = query.strip()
        if text.lower().endswith(".exe") and "@" in text:
            raise Invalid("invalid query", repr(query))
        if text.count("@") > 1 or text.startswith("@") or text.endswith("@"):
            raise Invalid("invalid query", repr(query))
        budget = [_check_int(max_body_chars, 1, DEFAULT_MAX_BODY_CHARS, "max_body_chars")]
        if isinstance(body_offset, bool) or not isinstance(body_offset, int) or body_offset < 0:
            raise Invalid("invalid offset", repr(body_offset))
        if plan_id and not text:
            raise Invalid("invalid query", "plan_id needs an exact key")
        if not plan_id and body_offset:
            raise Invalid("invalid offset", "body_offset needs a plan_id to continue from")
        root = memory_root()
        if plan_id:
            return _recall_one(root, text, plan_id, budget, body_offset)
        return _recall_many(root, text, budget)
    except Invalid as error:
        return {"ok": False, "reason": error.reason, "detail": error.detail}


def _recall_one(root: Path, key: str, plan_id: str, budget: list[int], offset: int) -> dict:
    _check_plan_id(plan_id)
    records, _ = _scan(root)
    record = next((r for r in records if r["key"] == key), None)
    if record is None or "see" in record:
        raise Invalid("plan not found", f"{key} has no readable record; continuation needs a stored key")
    plan = _match_plan(record, plan_id)
    if plan is None:
        raise Invalid("plan not found", f"{key} has no plan {plan_id}")
    total = len(plan["body"])
    if offset > total:
        raise Invalid("invalid offset", f"{offset} is past the end of {total} characters")
    match = _as_match(root, record, budget, plans=[_as_plan(key, plan, False, budget, offset)])
    gaps = []
    for plan_ in record["plans"]:
        body = _unresolved_text(plan_["body"])
        if body is not None:
            gaps.append({"plan_id": plan_["id"], "text": body})
    match["unresolved"] = _budget_gaps(gaps, budget)
    return {"ok": True, "matches": [match], "exact": True,
            "truncated": any(p["truncated"] for p in match["plans"]),
            "warnings": []}


def _fail_if_unreadable(root: Path, key: str, chosen: list[dict]) -> None:
    """A stored record that cannot be parsed is an error, not a miss."""
    if chosen or not record_path(root, key).exists():
        return
    _load_key(root, key)  # raises Invalid with the concrete reason


def _exact_record(root: Path, key: str) -> dict | None:
    """Read one key directly, so a broken record reports why instead of vanishing."""
    if not record_path(root, key).exists():
        return None
    return _load_key(root, key)


def _recall_many(root: Path, text: str, budget: list[int]) -> dict:
    if not text:
        records, warnings = _scan(root)
        keys = sorted(record["key"] for record in records)
        return {"ok": True, "keys": keys, "matches": [], "exact": False,
                "truncated": False, "warnings": warnings}
    records, warnings = _scan(root)
    if not records and not (root / "playbooks").exists():
        # A missing root is "nothing stored yet", not a failure.
        return {"ok": True, "matches": [], "exact": False, "truncated": False, "warnings": []}

    app = _app_of(text)
    exact = False
    if app:
        wanted = app.casefold()
        chosen = [r for r in records if r["app"].strip().casefold() == wanted]
        if text.count("@") == 1:
            version = text.rsplit("@", 1)[1]
            key = make_key(app, None if version.casefold() == "unversioned" else version)
            chosen = [r for r in chosen if r["key"] == key]
            exact = bool(chosen)
            _fail_if_unreadable(root, key, chosen)
    elif "@" in text:
        name, version = text.rsplit("@", 1)
        key = make_key(name, None if version.casefold() == "unversioned" else version)
        chosen = [r for r in records if r["key"] == key]
        exact = bool(chosen)
        _fail_if_unreadable(root, key, chosen)
        if not chosen:
            family = name.strip().casefold()
            chosen = [r for r in records if r["app"].strip().casefold() == family]
    else:
        low = text.casefold()
        chosen = [r for r in records if low in r["app"].casefold()]

    chosen.sort(key=lambda record: record["key"])
    matches = [_as_match(root, record, budget) for record in chosen]
    truncated = False
    for match, record in zip(matches, chosen):
        gaps = []
        for plan in _plans(record):
            body = _unresolved_text(plan["body"])
            if body is not None:
                gaps.append({"plan_id": plan["id"], "text": body})
        match["unresolved"] = _budget_gaps(gaps, budget)
        if any(p["truncated"] for p in match["plans"]) or any(u["truncated"] for u in match["unresolved"]):
            truncated = True
    return {"ok": True, "matches": matches, "exact": exact, "truncated": truncated,
            "warnings": warnings}


def _budget_gaps(gaps: list[dict], budget: list[int]) -> list[dict]:
    out = []
    for gap in gaps:
        remaining = max(0, budget[0])
        piece = gap["text"][:remaining]
        budget[0] -= len(piece)
        out.append({"plan_id": gap["plan_id"], "text": piece,
                    "truncated": len(piece) < len(gap["text"])})
    return out


# ---------- writes ----------


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def remember(app: str, version: str | None, plan_id: str, summary: str,
             cost: str, body: str, uses_foreground: bool,
             overwrite: bool = False) -> dict:
    try:
        app = _check_app(app)
        version = _check_version(version)
        plan_id = _check_plan_id(plan_id)
        summary = _check_text(summary, "summary")
        cost = _check_text(cost, "cost")
        body = _check_text(body, "body")
        if not isinstance(uses_foreground, bool):
            raise Invalid("invalid uses_foreground", "pass true when the side effects are unknown")
        if not isinstance(overwrite, bool):
            raise Invalid("invalid arguments", "overwrite must be a bool")
        key = make_key(app, version)
        root = memory_root()
        path = record_path(root, key)
        with _write_lock:
            if path.exists():
                record = _load_key(root, key)
                if "see" in record and not overwrite:
                    raise Invalid("inherited record",
                                  "pass overwrite=true to materialize this version's own record")
            else:
                record = {"schema": SCHEMA, "key": key, "app": app, "version": version,
                          "updated": _today(), "plans": []}
            if "see" in record:
                # Materialising: copy the source plans, then drop all trust.
                plans = [{field: plan[field] for field in
                          ("id", "summary", "cost", "body", "uses_foreground")}
                         for plan in record["_source"]["plans"]]
                record = {"schema": SCHEMA, "key": key, "app": app, "version": version,
                          "updated": _today(), "plans": plans}
                for plan in record["plans"]:
                    plan["reviewed"] = plan["proven"] = False
            existing = next((p for p in record["plans"] if p["id"] == plan_id), None)
            if existing is None:
                record["plans"].append({"id": plan_id, "summary": summary, "cost": cost,
                                        "body": body, "uses_foreground": uses_foreground,
                                        "reviewed": False, "proven": False})
            else:
                if not overwrite:
                    raise Invalid("plan exists", "pass overwrite=true to replace this plan")
                same = all(existing[field] == value for field, value in
                           (("summary", summary), ("cost", cost),
                            ("body", body), ("uses_foreground", uses_foreground)))
                record["plans"][record["plans"].index(existing)] = {
                    "id": plan_id, "summary": summary, "cost": cost, "body": body,
                    "uses_foreground": uses_foreground,
                    "reviewed": existing["reviewed"] if same else False,
                    "proven": existing["proven"] if same else False,
                }
            record["updated"] = _today()
            plan = next(p for p in record["plans"] if p["id"] == plan_id)
            _write(path, record)
            return {"ok": True, "key": key, "plan_id": plan_id,
                    "rank": rank(plan["reviewed"], plan["proven"]),
                    "revision": plan_revision(key, plan)}
    except Invalid as error:
        return {"ok": False, "reason": error.reason, "detail": error.detail}


def _set_trust(app, version, plan_id, expected_revision, field: str, value: bool) -> dict:
    try:
        app = _check_app(app)
        version = _check_version(version)
        plan_id = _check_plan_id(plan_id)
        if not isinstance(expected_revision, str) or not expected_revision:
            raise Invalid("invalid revision", "expected_revision is required")
        if not isinstance(value, bool):
            raise Invalid("invalid arguments", f"{field} must be a bool")
        key = make_key(app, version)
        root = memory_root()
        path = record_path(root, key)
        with _write_lock:
            record = _load_key(root, key)
            if "see" in record:
                raise Invalid("inherited record",
                              "materialize this version with remember(overwrite=true) first")
            plan = _match_plan(record, plan_id)
            if plan is None:
                raise Invalid("plan not found", f"{key} has no plan {plan_id}")
            if plan_revision(key, plan) != expected_revision:
                raise Invalid("stale plan",
                              "the plan changed since it was read; read it again and re-confirm")
            if version is None and value:
                raise Invalid("version unconfirmed",
                              "an app@unversioned observation cannot be marked verified")
            plan[field] = value
            record["updated"] = _today()
            _write(path, record)
            return {"ok": True, "key": key, "plan_id": plan_id,
                    "rank": rank(plan["reviewed"], plan["proven"]),
                    "revision": plan_revision(key, plan)}
    except Invalid as error:
        return {"ok": False, "reason": error.reason, "detail": error.detail}


def approve(app: str, version: str | None, plan_id: str, expected_revision: str,
            reviewed: bool = True) -> dict:
    return _set_trust(app, version, plan_id, expected_revision, "reviewed", reviewed)


def confirm_proven(app: str, version: str | None, plan_id: str, expected_revision: str,
                   proven: bool = True) -> dict:
    return _set_trust(app, version, plan_id, expected_revision, "proven", proven)
