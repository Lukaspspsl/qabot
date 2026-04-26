#!/usr/bin/env python3
"""
trsync — TestRail sync CLI for CellarHand QA

YAML/CSV test cases <-> TestRail Cloud/Server via API v2.
Source of truth: your YAML/CSV files. TestRail is a projection.

Commands:
    validate     Schema-check local YAML/CSV. No API calls.
    refresh-map  Pull all cases from TestRail and build local ID cache.
    diff         Show per-field diff between local and remote.
    push         Create/update cases. Dry-run by default.

Config: .env file in cwd, or environment variables.
    TR_URL          e.g. https://acme.testrail.io
    TR_USER         your TestRail email
    TR_API_KEY      from My Settings > API Keys
    TR_PROJECT_ID   numeric
    TR_SUITE_ID     numeric (required for multi-suite projects)
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
console = Console()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MAPPING_FILE = Path(".trsync/mapping.json")
LOG_DIR = Path(".trsync/logs")
TC_ID_RE = re.compile(r"^\[?(TC-(?:[A-Z]+-)?\d+(?:\.\d+)+)\]?\s+(.*)$")


@dataclass
class Config:
    url: str
    user: str
    api_key: str
    password: str
    project_id: int
    suite_id: int | None = None  # optional; only used in multi-suite projects

    @classmethod
    def load(cls) -> "Config":
        load_dotenv()
        missing = [
            k for k in ("TR_URL", "TR_USER", "TR_API_KEY", "TR_PASSWORD", "TR_PROJECT_ID")
            if not os.getenv(k)
        ]
        if missing:
            console.print(f"[red]Missing env vars: {', '.join(missing)}[/red]")
            console.print("Copy .env.example to .env and fill it in.")
            raise typer.Exit(1)
        suite_raw = os.getenv("TR_SUITE_ID", "").strip()
        return cls(
            url=os.environ["TR_URL"].rstrip("/"),
            user=os.environ["TR_USER"],
            api_key=os.environ["TR_API_KEY"],
            password=os.environ["TR_PASSWORD"],
            project_id=int(os.environ["TR_PROJECT_ID"]),
            suite_id=int(suite_raw) if suite_raw else None,
        )


# ---------------------------------------------------------------------------
# Local schema (YAML source of truth)
# ---------------------------------------------------------------------------


class TestCase(BaseModel):
    """Canonical YAML schema for CellarHand TCs.

    Steps and preconditions accept either plain strings (canonical) or dicts
    with an `action`/`content`/`step`/`text` key (legacy form, coerced to
    string so migration doesn't block validation).
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^TC-[A-Z]+-\d+(\.\d+)+$")
    title: str
    section: str | None = None       # optional locally; required to CREATE a new TC
    priority: str                    # P1|P2|P3 (P4 tolerated for legacy)
    platform: str | None = None      # api|mobile|web
    type: str                        # functional|integration|unit|e2e|manual|smoke
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    expected_result: str = ""
    jira_key: str = ""               # Jira keys, comma-separated if multiple
    automation_status: str = "manual"
    automation_id: str = ""
    source_docs: list[str] = Field(default_factory=list)

    @field_validator("priority")
    @classmethod
    def _prio_shape(cls, v: str) -> str:
        if not re.match(r"^P[1-4]$", v):
            raise ValueError("priority must be P1..P4")
        return v

    @field_validator("steps", "preconditions", mode="before")
    @classmethod
    def _coerce_string_list(cls, v: Any) -> Any:
        """Accept list of strings OR list of dicts (legacy form). Extract the
        first plausible string key from each dict item."""
        if not isinstance(v, list):
            return v
        out: list[str] = []
        for item in v:
            if isinstance(item, str):
                out.append(item)
                continue
            if isinstance(item, dict):
                for key in ("action", "content", "step", "text", "description"):
                    val = item.get(key)
                    if isinstance(val, str) and val.strip():
                        out.append(val)
                        break
                else:
                    # No recognised key — keep as JSON so validation fails loud
                    # rather than silently dropping content.
                    raise ValueError(
                        f"list item is a dict with no recognised key "
                        f"(action/content/step/text/description): {item!r}"
                    )
                continue
            raise ValueError(f"list item must be string or dict, got {type(item).__name__}: {item!r}")
        return out

    def full_title(self) -> str:
        """Title as stored in TestRail: '{id} {title}'."""
        return f"{self.id} {self.title}"


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class TR:
    """Thin TestRail client. Handles 429 backoff and pagination."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        # No base_url: TestRail's query-string routing (`?/api/v2/...&foo=bar`)
        # does not survive httpx's URL merge/normalization cleanly. We build
        # full URLs as plain strings instead.
        self.client = httpx.Client(
            headers={"Content-Type": "application/json"},
            timeout=30.0,
            follow_redirects=False,
        )
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.log = (LOG_DIR / f"run-{int(time.time())}.jsonl").open("a")
        self._suite_mode: int | None = None  # lazily fetched
        self._login()

    def _login(self) -> None:
        # TestRail instances with "Enable session authentication for API"
        # reject Basic auth on /api/v2. Log in via the web form to obtain
        # tr_session cookie and let httpx persist it for API calls.
        url = f"{self.cfg.url}/index.php?/auth/login/"
        r = self.client.post(
            url,
            data={
                "name": self.cfg.user,
                "password": self.cfg.password,
                "rememberme": "1",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        cookie_names = {c.name for c in self.client.cookies.jar}
        has_session = any("session" in n.lower() or n.lower() == "tr_session" for n in cookie_names)
        if r.status_code not in (200, 302) or not has_session:
            raise RuntimeError(
                "TestRail login failed — check TR_USER / TR_PASSWORD "
                f"(status={r.status_code}, cookies={sorted(cookie_names)})"
            )

    def _url(self, path: str) -> str:
        return f"{self.cfg.url}/index.php?/api/v2/{path}"

    def suite_mode(self) -> int:
        """TestRail project suite_mode: 1=single, 2=single+baselines, 3=multiple."""
        if self._suite_mode is None:
            proj = self.get(f"get_project/{self.cfg.project_id}")
            self._suite_mode = int(proj.get("suite_mode", 1))
            if self._suite_mode == 1 and self.cfg.suite_id:
                console.print(
                    "[dim]note: project is single-suite; ignoring TR_SUITE_ID[/dim]"
                )
            if self._suite_mode != 1 and not self.cfg.suite_id:
                raise RuntimeError(
                    f"project {self.cfg.project_id} is multi-suite (mode={self._suite_mode}); "
                    "set TR_SUITE_ID in .env"
                )
        return self._suite_mode

    def suite_q(self) -> str:
        """Return '&suite_id=X' only when the project actually needs it."""
        if self.suite_mode() == 1:
            return ""
        return f"&suite_id={self.cfg.suite_id}"

    def _call(self, method: str, path: str, json_body: dict | None = None) -> Any:
        url = self._url(path)
        relogged = False
        for attempt in range(5):
            r = self.client.request(method, url, json=json_body)
            self._log(method, path, json_body, r)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 2 ** attempt))
                console.print(f"[yellow]429 rate-limited, sleeping {wait}s[/yellow]")
                time.sleep(wait)
                continue
            if r.status_code == 401 and not relogged:
                relogged = True
                console.print("[yellow]401 — session expired, re-logging in[/yellow]")
                self._login()
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text}")
            return r.json() if r.text else None
        raise RuntimeError(f"{method} {path} exhausted retries")

    def _log(self, method: str, path: str, body: dict | None, r: httpx.Response) -> None:
        redacted = dict(body) if body else None
        self.log.write(json.dumps({
            "t": time.time(),
            "method": method,
            "path": path,
            "status": r.status_code,
            "body": redacted,
            "resp_bytes": len(r.content),
        }) + "\n")
        self.log.flush()

    def get(self, path: str) -> Any:
        return self._call("GET", path)

    def post(self, path: str, body: dict) -> Any:
        return self._call("POST", path, body)

    def paged(self, path: str, list_key: str) -> list[dict]:
        """Handle both old (bare array) and new (offset/_links) pagination."""
        out: list[dict] = []
        next_path: str | None = path
        while next_path:
            resp = self.get(next_path)
            if isinstance(resp, list):
                out.extend(resp)
                return out
            out.extend(resp.get(list_key, []))
            nxt = (resp.get("_links") or {}).get("next")
            next_path = nxt.replace("/api/v2/", "") if nxt else None
        return out

    def close(self) -> None:
        self.client.close()
        self.log.close()


# ---------------------------------------------------------------------------
# Field resolution (priorities, types, dropdowns, sections)
# ---------------------------------------------------------------------------


class Resolver:
    """Caches label->id lookups for priorities, types, and automation_status dropdown."""

    def __init__(self, tr: TR):
        self.tr = tr
        self._priorities: dict[str, int] = {}
        self._types: dict[str, int] = {}
        self._automation: dict[str, int] = {}
        self._sections: dict[str, int] = {}  # "a > b > c" -> section_id

    def load(self) -> None:
        # P1..P4 => prio id (TestRail uses 1=Low..4=Critical by default; we match by name)
        prios = self.tr.get("get_priorities")
        for p in prios:
            short = p.get("short_name", "").strip()
            name = p.get("name", "").strip()
            if short:
                self._priorities[short] = p["id"]
            self._priorities[name] = p["id"]

        types = self.tr.get(f"get_case_types")
        for t in types:
            self._types[t["name"].lower()] = t["id"]

        # Automation Status dropdown values
        for f in self.tr.get("get_case_fields"):
            if f.get("system_name") != "custom_automation_status":
                continue
            for cfg in f.get("configs", []):
                items = cfg.get("options", {}).get("items", "")
                for line in items.splitlines():
                    m = re.match(r"\s*(\d+)\s*,\s*(.+)$", line)
                    if m:
                        self._automation[m.group(2).strip()] = int(m.group(1))

        # Sections (suite_id appended only for multi-suite projects)
        sections = self.tr.paged(
            f"get_sections/{self.tr.cfg.project_id}{self.tr.suite_q()}",
            "sections",
        )
        by_id = {s["id"]: s for s in sections}
        for s in sections:
            path, cur = [s["name"]], s
            while cur.get("parent_id"):
                cur = by_id[cur["parent_id"]]
                path.append(cur["name"])
            self._sections[" > ".join(reversed(path))] = s["id"]

    def priority_id(self, p: str) -> int:
        if p not in self._priorities:
            raise ValueError(f"Priority {p!r} not found in TestRail. Known: {list(self._priorities)}")
        return self._priorities[p]

    def type_id(self, t: str) -> int:
        aliases = {"e2e": "functional", "smoke": "smoke & sanity"}
        key = aliases.get(t.lower(), t.lower())
        if key not in self._types:
            raise ValueError(f"Type {t!r} not found. Known: {list(self._types)}")
        return self._types[key]

    def automation_id(self, s: str) -> int | None:
        if not self._automation:
            return None
        if s not in self._automation:
            raise ValueError(
                f"automation_status {s!r} not in dropdown. Known: {list(self._automation)}"
            )
        return self._automation[s]

    def section_id(self, path: str, create: bool = True) -> int:
        if path in self._sections:
            return self._sections[path]
        if not create:
            raise KeyError(path)
        # Create missing sections step by step
        parts = [p.strip() for p in path.split(">")]
        parent_id: int | None = None
        accum: list[str] = []
        for part in parts:
            accum.append(part)
            key = " > ".join(accum)
            if key in self._sections:
                parent_id = self._sections[key]
                continue
            body: dict[str, Any] = {"name": part}
            if self.tr.suite_mode() != 1 and self.tr.cfg.suite_id:
                body["suite_id"] = self.tr.cfg.suite_id
            if parent_id is not None:
                body["parent_id"] = parent_id
            created = self.tr.post(f"add_section/{self.tr.cfg.project_id}", body)
            parent_id = created["id"]
            self._sections[key] = parent_id
            console.print(f"  [dim]+ created section {key!r} -> {parent_id}[/dim]")
        return parent_id  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Loaders (YAML + CSV)
# ---------------------------------------------------------------------------


TC_ID_PAT = re.compile(r"^TC-[A-Z]+-\d+(\.\d+)+$")


def _looks_like_tc_dict(d: Any) -> bool:
    return isinstance(d, dict) and isinstance(d.get("id"), str) and bool(TC_ID_PAT.match(d["id"]))


def _extract_tc_dicts(data: Any) -> tuple[list[dict], str | None]:
    """Return (list of TC dicts, skip_reason).

    Accepts either:
      - a single dict shaped like a TC
      - a list of dicts, each shaped like a TC (API-style, common even for single-TC files)

    Returns empty list + reason if data doesn't match either shape.
    """
    if data is None:
        return [], "empty file"
    if isinstance(data, dict):
        if _looks_like_tc_dict(data):
            return [data], None
        if "id" not in data:
            return [], f"no 'id' field (keys: {list(data.keys())[:6]})"
        rid = data.get("id")
        if not isinstance(rid, str):
            return [], f"id is {type(rid).__name__}: {rid!r}"
        return [], f"id {rid!r} doesn't match TC-<DOMAIN>-<digits>(.digits)+"
    if isinstance(data, list):
        if not data:
            return [], "empty list"
        if all(_looks_like_tc_dict(d) for d in data):
            return data, None
        # Partial match: list of dicts but some without TC-shaped id
        bad = next((d for d in data if not _looks_like_tc_dict(d)), None)
        if isinstance(bad, dict):
            if "id" not in bad:
                return [], f"list item missing 'id' (keys: {list(bad.keys())[:6]})"
            return [], f"list item id {bad.get('id')!r} doesn't match TC-<DOMAIN>-<digits>(.digits)+"
        return [], f"list contains non-dict item: {type(bad).__name__}"
    return [], f"top-level is {type(data).__name__}"


def _tc_skip_reason(data: Any) -> str | None:
    """Back-compat shim used by load_dir."""
    _, reason = _extract_tc_dicts(data)
    return reason


def _looks_like_tc(data: Any) -> bool:
    return _tc_skip_reason(data) is None


def load_yaml_tc(path: Path) -> TestCase:
    """Load exactly one TC from a YAML file. Errors if file holds multiple."""
    data = yaml.safe_load(path.read_text())
    dicts, reason = _extract_tc_dicts(data)
    if reason:
        raise typer.BadParameter(f"{path}: {reason}")
    if len(dicts) > 1:
        raise typer.BadParameter(
            f"{path}: file holds {len(dicts)} TCs; use load_dir or split into separate files"
        )
    try:
        return TestCase(**dicts[0])
    except (ValidationError, TypeError) as e:
        raise typer.BadParameter(f"{path}: {e}") from e


def _build_tc(path: Path, data: dict) -> TestCase:
    try:
        return TestCase(**data)
    except (ValidationError, TypeError) as e:
        raise typer.BadParameter(f"{path}: {e}") from e


def load_dir(path: Path) -> list[tuple[Path, TestCase]]:
    """Walk a folder for TC YAMLs. CSVs inside folders are treated as indexes and
    ignored — they are only loaded when an explicit CSV file path is passed."""
    if path.is_file():
        if path.suffix.lower() == ".csv":
            return [(path, tc) for tc in load_csv(path)]
        return [(path, load_yaml_tc(path))]
    out: list[tuple[Path, TestCase]] = []
    skipped: list[tuple[Path, str]] = []
    for ext in ("*.yml", "*.yaml"):
        for p in sorted(path.rglob(ext)):
            try:
                data = yaml.safe_load(p.read_text())
            except yaml.YAMLError as e:
                raise typer.BadParameter(f"{p}: invalid YAML: {e}") from e
            dicts, reason = _extract_tc_dicts(data)
            if reason:
                skipped.append((p, reason))
                continue
            for d in dicts:
                try:
                    out.append((p, TestCase(**d)))
                except (ValidationError, TypeError) as e:
                    raise typer.BadParameter(f"{p}: {e}") from e
    if skipped:
        console.print(f"[yellow]skipped {len(skipped)} YAML file(s) — reasons:[/yellow]")
        # Group by reason to surface patterns without flooding output
        by_reason: dict[str, list[Path]] = {}
        for p, r in skipped:
            by_reason.setdefault(r, []).append(p)
        for r, ps in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            console.print(f"  [yellow]{len(ps)}x[/yellow] {r}")
            for p in ps[:2]:
                console.print(f"      [dim]- {p}[/dim]")
            if len(ps) > 2:
                console.print(f"      [dim]... and {len(ps) - 2} more[/dim]")
    return out


def load_csv(path: Path) -> list[TestCase]:
    """Parse a CSV shaped like test-plan.csv. Title column has ID baked in."""
    out: list[TestCase] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            title_raw = row["title"].strip()
            m = TC_ID_RE.match(title_raw)
            if not m:
                raise ValueError(f"CSV row title missing TC-xxx prefix: {title_raw!r}")
            tc_id, title = m.group(1), m.group(2)
            out.append(TestCase(
                id=tc_id,
                title=title,
                section=row.get("section") or None,
                priority=row["priority"].strip(),
                platform=row.get("platform") or None,
                type=row["type"].strip(),
                preconditions=[s.strip() for s in row.get("preconditions", "").split("|") if s.strip()],
                steps=[s.strip() for s in row.get("steps", "").split("|") if s.strip()],
                expected_result=row.get("expected_outcome", "").strip(),
                jira_key=row.get("ref_jira_keys", "").strip(),
                automation_status=row.get("automation_status", "manual").strip(),
                automation_id=row.get("automation_id", "").strip(),
            ))
    return out


# ---------------------------------------------------------------------------
# Mapping (TC-ID prefix -> TestRail case_id)
# ---------------------------------------------------------------------------


@dataclass
class Mapping:
    by_tc_id: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Mapping":
        if MAPPING_FILE.exists():
            return cls(by_tc_id=json.loads(MAPPING_FILE.read_text()))
        return cls()

    def save(self) -> None:
        MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
        MAPPING_FILE.write_text(json.dumps(self.by_tc_id, indent=2, sort_keys=True))

    def refresh(self, tr: TR) -> tuple[int, list[str]]:
        cases = tr.paged(
            f"get_cases/{tr.cfg.project_id}{tr.suite_q()}",
            "cases",
        )
        unmapped: list[str] = []
        self.by_tc_id.clear()
        for c in cases:
            m = TC_ID_RE.match(c.get("title", ""))
            if not m:
                unmapped.append(f"{c['id']}: {c['title']}")
                continue
            tc_id = m.group(1)
            if tc_id in self.by_tc_id:
                unmapped.append(f"duplicate prefix {tc_id}: cases {self.by_tc_id[tc_id]['case_id']} and {c['id']}")
            self.by_tc_id[tc_id] = {
                "case_id": c["id"],
                "section_id": c.get("section_id"),
                "updated_on": c.get("updated_on"),
            }
        self.save()
        return len(cases), unmapped


# ---------------------------------------------------------------------------
# Push / diff
# ---------------------------------------------------------------------------


def build_payload(tc: TestCase, resolver: Resolver, section_id: int | None) -> dict:
    """YAML TestCase -> TestRail JSON body. Omits refs when empty to preserve existing."""
    body: dict[str, Any] = {
        "title": tc.full_title(),
        "type_id": resolver.type_id(tc.type),
        "custom_preconds": "\n- " + "\n- ".join(tc.preconditions) if tc.preconditions else "",
        "custom_expected": tc.expected_result,
        "custom_steps_separated": [
            {"content": s, "expected": ""} for s in tc.steps
        ],
    }
    if section_id is not None:
        body["section_id"] = section_id
    if tc.jira_key:
        body["refs"] = tc.jira_key
    if tc.automation_id:
        body["custom_automation_id"] = tc.automation_id
    auto = resolver.automation_id(tc.automation_status)
    if auto is not None:
        body["custom_automation_status"] = auto
    return body


def compare(local: dict, remote: dict) -> list[tuple[str, Any, Any]]:
    """Return [(field, local_val, remote_val)] for differing fields."""
    diffs = []
    for key, lval in local.items():
        rval = remote.get(key)
        if key == "custom_steps_separated":
            rlist = rval or []
            if len(lval) != len(rlist) or any(
                (a.get("content") or "").strip() != (b.get("content") or "").strip()
                for a, b in zip(lval, rlist)
            ):
                diffs.append((key, lval, rlist))
        elif (lval or "") != (rval or ""):
            diffs.append((key, lval, rval))
    return diffs


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def validate(path: Path = typer.Argument(..., help="YAML file, folder of YAML, or CSV")):
    """Schema-check local TCs. No API calls."""
    items: list[tuple[Path, TestCase]] = []
    if path.is_file() and path.suffix.lower() == ".csv":
        items = [(path, tc) for tc in load_csv(path)]
    else:
        items = load_dir(path)

    # Track every path an id appears at
    by_id: dict[str, list[Path]] = {}
    for src, tc in items:
        by_id.setdefault(tc.id, []).append(src)

    dupes = {tc_id: paths for tc_id, paths in by_id.items() if len(paths) > 1}
    for tc_id, paths in sorted(dupes.items()):
        console.print(f"[red]duplicate TC id {tc_id} ({len(paths)}x)[/red]")
        for p in paths:
            console.print(f"  [dim]- {p}[/dim]")

    if dupes:
        console.print(f"\n[red]{len(dupes)} duplicate ids across {sum(len(p) for p in dupes.values())} files[/red]")
        raise typer.Exit(1)
    console.print(f"[green]validated {len(items)} test cases[/green]")


@app.command("refresh-map")
def refresh_map():
    """Pull all cases from TestRail; rebuild .trsync/mapping.json.

    Takes no arguments: the project/suite to sync is fixed by TR_PROJECT_ID
    and TR_SUITE_ID in your .env.
    """
    cfg = Config.load()
    tr = TR(cfg)
    try:
        mapping = Mapping()
        total, unmapped = mapping.refresh(tr)
        console.print(f"[green]indexed {len(mapping.by_tc_id)}/{total} cases[/green]")
        if unmapped:
            console.print(f"[yellow]{len(unmapped)} cases without TC-xxx prefix (skipped):[/yellow]")
            for u in unmapped[:20]:
                console.print(f"  - {u}")
            if len(unmapped) > 20:
                console.print(f"  ... and {len(unmapped) - 20} more")
    finally:
        tr.close()


COVERAGE_LINE_RE = re.compile(
    r"^\s*-\s*\[[ xX]\]\s+(TC-(?:[A-Z]+-)?\d+(?:\.\d+)+)\s+(.*?)\s*$"
)


def _load_coverage(path: Path) -> dict[str, str]:
    """Parse TEST-COVERAGE.md into {tc_id: title}."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        m = COVERAGE_LINE_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


@app.command()
def renumber(
    old_prefix: str = typer.Argument(..., help="Legacy id prefix, e.g. TC-2."),
    new_prefix: str = typer.Argument(..., help="Replacement prefix, e.g. TC-MOB-2."),
    apply: bool = typer.Option(False, "--apply", help="Actually write. Default dry-run."),
):
    """Rewrite case titles by swapping id prefix in-place.

    Example: `renumber TC-2. TC-MOB-2.` turns every `TC-2.x.x ...` title into
    `TC-MOB-2.x.x ...`. Matches whole-id boundary so `TC-2.` will not touch
    `TC-MOB-2.` or `TC-NF-2.`.
    """
    cfg = Config.load()
    tr = TR(cfg)
    try:
        cases = tr.paged(
            f"get_cases/{tr.cfg.project_id}{tr.suite_q()}",
            "cases",
        )
        pattern = re.compile(rf"^\[?({re.escape(old_prefix)}\d+(?:\.\d+)*)\]?\s+(.*)$")
        changed = 0
        for c in cases:
            m = pattern.match(c.get("title", ""))
            if not m:
                continue
            new_id = new_prefix + m.group(1)[len(old_prefix):]
            new_title = f"{new_id} {m.group(2)}"
            action = "would rename" if not apply else "renaming"
            console.print(f"[cyan]{c['id']}[/cyan] {action}: {m.group(1)} -> {new_id}")
            if apply:
                tr.post(f"update_case/{c['id']}", {"title": new_title})
            changed += 1
        console.print(f"[green]{changed} renamed[/green]")
        if not apply and changed:
            console.print("[dim]dry-run — pass --apply to write[/dim]")
    finally:
        tr.close()


@app.command()
def adopt(
    coverage: Path = typer.Option(
        Path("../cases/TEST-COVERAGE.md"),
        "--coverage",
        help="Path to TEST-COVERAGE.md with canonical TC list.",
    ),
    threshold: float = typer.Option(0.85, "--threshold", help="Fuzzy match ratio cutoff [0..1]."),
    apply: bool = typer.Option(False, "--apply", help="Actually write to TestRail. Default dry-run."),
    map_file: Path | None = typer.Option(
        None, "--map", help="CSV with `case_id,tc_id` for forced mappings. Skips fuzzy."
    ),
):
    """Assign TC-xxx prefix to orphan TestRail cases via fuzzy title match.

    Reads canonical (tc_id, title) pairs from TEST-COVERAGE.md, finds best
    match for each orphan (no TC prefix), and rewrites title to
    `{tc_id} {matched_title}`. TC ids already mapped in .trsync/mapping.json
    are skipped so one id is never assigned to two cases.
    """
    from difflib import SequenceMatcher

    cfg = Config.load()
    tr = TR(cfg)
    try:
        # Load canonical titles
        if not coverage.exists():
            console.print(f"[red]coverage file not found: {coverage}[/red]")
            raise typer.Exit(1)
        canonical = _load_coverage(coverage)
        if not canonical:
            console.print(f"[red]no TC entries parsed from {coverage}[/red]")
            raise typer.Exit(1)
        console.print(f"[dim]loaded {len(canonical)} canonical TCs from {coverage}[/dim]")

        # TC ids already used by non-orphan cases
        taken: set[str] = set()
        if MAPPING_FILE.exists():
            taken = set(json.loads(MAPPING_FILE.read_text()).keys())

        # Explicit overrides
        overrides: dict[int, str] = {}
        if map_file:
            with map_file.open() as fh:
                for row in csv.reader(fh):
                    if not row or row[0].startswith("#") or row[0].strip() == "case_id":
                        continue
                    overrides[int(row[0])] = row[1].strip()

        # Fetch all cases, keep orphans
        cases = tr.paged(
            f"get_cases/{tr.cfg.project_id}{tr.suite_q()}",
            "cases",
        )
        orphans = [c for c in cases if not TC_ID_RE.match(c.get("title", ""))]
        console.print(f"[dim]{len(orphans)} orphans to process[/dim]")

        available = {tc_id: title for tc_id, title in canonical.items() if tc_id not in taken}

        matched = skipped = collisions = 0
        unmatched: list[str] = []

        for c in orphans:
            orphan_title = c["title"]
            forced = overrides.get(c["id"])

            if forced:
                tc_id = forced
                canonical_title = canonical.get(tc_id, orphan_title)
                score = 1.0
            else:
                best_id, best_score = None, 0.0
                for tc_id, title in available.items():
                    score = SequenceMatcher(None, orphan_title.lower(), title.lower()).ratio()
                    if score > best_score:
                        best_id, best_score = tc_id, score
                if not best_id or best_score < threshold:
                    unmatched.append(f"{c['id']} ({best_score:.2f}): {orphan_title}")
                    continue
                tc_id = best_id
                canonical_title = available[tc_id]
                score = best_score

            if tc_id in taken:
                collisions += 1
                unmatched.append(f"{c['id']} COLLISION {tc_id} already used: {orphan_title}")
                continue

            new_title = f"{tc_id} {canonical_title}"
            action = "would adopt" if not apply else "adopting"
            console.print(
                f"[cyan]{c['id']}[/cyan] {action} [green]{tc_id}[/green] "
                f"({score:.2f}): {orphan_title!r} -> {new_title!r}"
            )
            if apply:
                tr.post(f"update_case/{c['id']}", {"title": new_title})
            taken.add(tc_id)
            available.pop(tc_id, None)
            matched += 1

        console.print(
            f"[green]{matched} matched, {len(unmatched)} unmatched, "
            f"{collisions} collisions[/green]"
        )
        if unmatched:
            console.print(f"[yellow]unmatched (below threshold {threshold}):[/yellow]")
            for u in unmatched:
                console.print(f"  - {u}")
        if not apply and matched:
            console.print("[dim]dry-run — pass --apply to write[/dim]")
    finally:
        tr.close()


@app.command()
def normalize(
    apply: bool = typer.Option(False, "--apply", help="Actually write to TestRail. Default is dry-run."),
    report_orphans: bool = typer.Option(False, "--report-orphans", help="List cases with no TC-xxx prefix."),
):
    """Rewrite TestRail titles to canonical `TC-XXX-N.N.N Title` form.

    Strips brackets from `[TC-XXX-N.N.N] Title` and collapses whitespace.
    Cases without any TC prefix are left untouched (use --report-orphans to
    list them for manual mapping).
    """
    cfg = Config.load()
    tr = TR(cfg)
    try:
        cases = tr.paged(
            f"get_cases/{tr.cfg.project_id}{tr.suite_q()}",
            "cases",
        )
        changed = skipped = orphaned = 0
        orphans: list[str] = []
        for c in cases:
            title = c.get("title", "")
            m = TC_ID_RE.match(title)
            if not m:
                orphaned += 1
                orphans.append(f"{c['id']}: {title}")
                continue
            canonical = f"{m.group(1)} {m.group(2).strip()}"
            if canonical == title:
                skipped += 1
                continue
            action = "would rewrite" if not apply else "rewriting"
            console.print(f"[cyan]{c['id']}[/cyan] {action}: {title!r} -> {canonical!r}")
            if apply:
                tr.post(f"update_case/{c['id']}", {"title": canonical})
            changed += 1
        console.print(
            f"[green]{changed} changed, {skipped} already canonical, {orphaned} orphans[/green]"
        )
        if report_orphans and orphans:
            console.print(f"[yellow]orphans (no TC prefix):[/yellow]")
            for o in orphans:
                console.print(f"  - {o}")
        if not apply and changed:
            console.print("[dim]dry-run — pass --apply to write[/dim]")
    finally:
        tr.close()


@app.command()
def diff(
    path: Path = typer.Argument(...),
    out: Path | None = typer.Option(None, "--out", help="Write plain-text diff to FILE instead of terminal."),
):
    """Show per-field diffs between local YAML and TestRail."""
    cfg = Config.load()
    tr = TR(cfg)
    if out:
        fh = open(out, "w")
        sink = Console(file=fh, force_terminal=False, width=200, no_color=True)
    else:
        fh = None
        sink = console
    try:
        resolver = Resolver(tr)
        resolver.load()
        mapping = Mapping.load()
        if not mapping.by_tc_id:
            console.print("[yellow]mapping cache empty — run `trsync refresh-map` first[/yellow]")
            raise typer.Exit(1)

        items = load_dir(path) if path.suffix.lower() != ".csv" else [
            (path, tc) for tc in load_csv(path)
        ]
        for src, tc in items:
            meta = mapping.by_tc_id.get(tc.id)
            if not meta:
                sink.print(f"[cyan]{tc.id}[/cyan] NEW  ({src})")
                continue
            remote = tr.get(f"get_case/{meta['case_id']}")
            section_id = remote.get("section_id")
            local = build_payload(tc, resolver, section_id)
            diffs = compare(local, remote)
            if not diffs:
                sink.print(f"[green]{tc.id}[/green] up to date")
                continue
            table = Table(title=f"{tc.id}  (case {meta['case_id']})")
            table.add_column("field"); table.add_column("local"); table.add_column("remote")
            for f, lv, rv in diffs:
                table.add_row(f, _fmt(lv), _fmt(rv))
            sink.print(table)
        if out:
            console.print(f"[green]diff written to {out}[/green]")
    finally:
        tr.close()
        if fh:
            fh.close()


@app.command()
def push(
    path: Path = typer.Argument(...),
    apply: bool = typer.Option(False, "--apply", help="Actually write to TestRail. Default is dry-run."),
    force_clear_refs: bool = typer.Option(
        False,
        "--force-clear-refs",
        help="Allow pushing empty refs to wipe Jira links. Default: refs is only set when non-empty.",
    ),
):
    """Create missing cases and update changed ones."""
    cfg = Config.load()
    tr = TR(cfg)
    try:
        resolver = Resolver(tr)
        resolver.load()
        mapping = Mapping.load()
        if not mapping.by_tc_id:
            console.print("[yellow]mapping cache empty — run `trsync refresh-map` first[/yellow]")
            raise typer.Exit(1)

        items = load_dir(path) if path.suffix.lower() != ".csv" else [
            (path, tc) for tc in load_csv(path)
        ]

        created = updated = skipped = 0
        for src, tc in items:
            meta = mapping.by_tc_id.get(tc.id)

            if not meta:
                # CREATE
                if not tc.section:
                    console.print(f"[red]{tc.id}: no section set, cannot create[/red]")
                    continue
                try:
                    section_id = resolver.section_id(tc.section, create=apply)
                except KeyError:
                    console.print(f"[yellow]{tc.id}[/yellow] would create (section missing: {tc.section!r})")
                    continue
                body = build_payload(tc, resolver, section_id=None)
                action = "would create" if not apply else "creating"
                console.print(f"[cyan]{tc.id}[/cyan] {action} in section {section_id}")
                if apply:
                    r = tr.post(f"add_case/{section_id}", body)
                    mapping.by_tc_id[tc.id] = {
                        "case_id": r["id"],
                        "section_id": section_id,
                        "updated_on": r.get("updated_on"),
                    }
                    created += 1
                continue

            # UPDATE
            remote = tr.get(f"get_case/{meta['case_id']}")
            section_id = remote.get("section_id")
            body = build_payload(tc, resolver, section_id)
            if not tc.jira_key and not force_clear_refs:
                body.pop("refs", None)  # preserve existing
            diffs = compare(body, remote)
            if not diffs:
                skipped += 1
                continue
            action = "would update" if not apply else "updating"
            console.print(f"[yellow]{tc.id}[/yellow] {action} ({len(diffs)} fields)")
            for f, lv, rv in diffs:
                console.print(f"    {f}: {_fmt(rv)}  ->  {_fmt(lv)}")
            if apply:
                tr.post(f"update_case/{meta['case_id']}", body)
                updated += 1

        if apply:
            mapping.save()
        console.print(f"\n[bold]created={created} updated={updated} up-to-date={skipped}[/bold]")
        if not apply:
            console.print("[dim]dry-run only — rerun with --apply to commit[/dim]")
    finally:
        tr.close()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fmt(v: Any, limit: int = 80) -> str:
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    s = s.replace("\n", " | ")
    return s if len(s) <= limit else s[:limit] + "…"


if __name__ == "__main__":
    app()
