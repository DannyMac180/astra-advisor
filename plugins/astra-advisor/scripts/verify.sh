#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
plugin_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
repo_dir=$(CDPATH= cd -- "$plugin_dir/../.." && pwd)

exec python3 - "$repo_dir" <<'PY'
from __future__ import annotations

import json
import re
import sys
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


repo = Path(sys.argv[1]).resolve()
plugin = repo / "plugins" / "astra-advisor"
errors: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def load_json(path: Path, label: str):
    require(path.is_file(), f"missing {label}: {path}")
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid JSON in {label}: {exc}")
        return None


def require_mapping(value, label: str):
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value if isinstance(value, dict) else {}


def require_string(mapping: dict, key: str, label: str, expected: str | None = None) -> None:
    value = mapping.get(key)
    require(isinstance(value, str) and bool(value.strip()), f"{label}.{key} must be a non-empty string")
    if expected is not None:
        require(value == expected, f"{label}.{key} must equal {expected!r}")


def require_list_of_strings(value, label: str) -> None:
    require(isinstance(value, list), f"{label} must be an array")
    if isinstance(value, list):
        require(
            all(isinstance(item, str) and bool(item.strip()) for item in value),
            f"{label} must contain only non-empty strings",
        )


def markdown_links(text: str) -> list[str]:
    # This intentionally parses link destinations only; it does not assert prose wording.
    return re.findall(r"\[[^\]]+\]\(([^)\s]+)(?:\s+[^)]*)?\)", text)


def check_relative_link(raw_target: str, base: Path, label: str) -> None:
    parsed = urlsplit(raw_target)
    if parsed.scheme or parsed.netloc or raw_target.startswith("#"):
        return
    target = (base / parsed.path).resolve()
    require(target.is_relative_to(repo), f"{label} escapes the repository: {raw_target}")
    require(target.is_file(), f"{label} points to a missing file: {raw_target}")


require(plugin.is_dir(), f"missing plugin directory: {plugin}")
manifest_path = plugin / ".codex-plugin" / "plugin.json"
manifest = require_mapping(load_json(manifest_path, "plugin manifest"), "plugin manifest")

require_string(manifest, "name", "plugin manifest", "astra-advisor")
require_string(manifest, "version", "plugin manifest", "0.2.0")
require_string(manifest, "description", "plugin manifest")
require_string(manifest, "homepage", "plugin manifest", "https://github.com/DannyMac180/astra-advisor#readme")
require_string(manifest, "repository", "plugin manifest", "https://github.com/DannyMac180/astra-advisor")
require_string(manifest, "license", "plugin manifest", "MIT")
require(manifest.get("skills") == "./skills/", "plugin manifest.skills must be ./skills/")
keywords = manifest.get("keywords")
require_list_of_strings(keywords, "plugin manifest.keywords")
if isinstance(keywords, list):
    require("orchestration" in keywords, "plugin manifest.keywords must include orchestration")

author = require_mapping(manifest.get("author"), "plugin manifest.author")
require_string(author, "name", "plugin manifest.author", "Daniel McAteer")
require_string(author, "url", "plugin manifest.author", "https://github.com/DannyMac180")

interface = require_mapping(manifest.get("interface"), "plugin manifest.interface")
for key, expected in (
    ("displayName", "Astra Advisor"),
    ("developerName", "Daniel McAteer"),
    ("category", "Productivity"),
):
    require_string(interface, key, "plugin manifest.interface", expected)
for key in ("shortDescription", "longDescription"):
    require_string(interface, key, "plugin manifest.interface")
capabilities = interface.get("capabilities")
require_list_of_strings(capabilities, "plugin manifest.interface.capabilities")
if isinstance(capabilities, list):
    require({"Interactive", "Write"}.issubset(capabilities), "plugin manifest.interface.capabilities must include Interactive and Write")
require_string(interface, "websiteURL", "plugin manifest.interface", "https://github.com/DannyMac180/astra-advisor")
default_prompt = interface.get("defaultPrompt")
require_list_of_strings(default_prompt, "plugin manifest.interface.defaultPrompt")
if isinstance(default_prompt, list):
    require(any("$astra-advisor:orchestration" in item for item in default_prompt), "defaultPrompt must invoke $astra-advisor:orchestration")

skill_root = plugin / "skills" / "orchestration"
skill_path = skill_root / "SKILL.md"
operations_path = skill_root / "references" / "operations.md"
ui_path = skill_root / "agents" / "openai.yaml"
require(skill_path.is_file(), f"missing orchestration skill: {skill_path}")
require(operations_path.is_file(), f"missing operations reference: {operations_path}")
require(ui_path.is_file(), f"missing orchestration UI metadata: {ui_path}")
if operations_path.is_file():
    for target in markdown_links(operations_path.read_text(encoding="utf-8")):
        check_relative_link(target, operations_path.parent, "operations reference link")
require((plugin / "scripts" / "cost_receipt.py").is_file(), "missing cost receipt calculator")
require((plugin / "tests" / "test_cost_receipt.py").is_file(), "missing cost receipt tests")
for date in ("2026-09-04", "2026-09-05"):
    require((plugin / "pricing" / f"{date}.json").is_file(), f"missing pricing snapshot: {date}")

if skill_path.is_file():
    skill_text = skill_path.read_text(encoding="utf-8")
    require(skill_text.startswith("---\n"), "orchestration SKILL.md must start with frontmatter")
    frontmatter_end = skill_text.find("\n---", 4)
    require(frontmatter_end != -1, "orchestration SKILL.md frontmatter must close")
    if frontmatter_end != -1:
        frontmatter = skill_text[4:frontmatter_end]
        frontmatter_lines = {}
        for line in frontmatter.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                frontmatter_lines[key.strip()] = value.strip().strip('"').strip("'")
        require(frontmatter_lines.get("name") == "orchestration", "orchestration skill frontmatter.name must be orchestration")
        require(bool(frontmatter_lines.get("description")), "orchestration skill frontmatter.description must be non-empty")
    for target in markdown_links(skill_text):
        check_relative_link(target, skill_root, "orchestration skill link")

readme_path = repo / "README.md"
require(readme_path.is_file(), f"missing README: {readme_path}")
if readme_path.is_file():
    readme = readme_path.read_text(encoding="utf-8")
    require("$astra-advisor:orchestration" in readme, "README must include the Astra Advisor invocation")
    links = markdown_links(readme)
    require("https://attentionheads.substack.com/" in links, "README must link to Attention Heads")
    subscribe_links = [urlsplit(link) for link in links if urlsplit(link).path == "/subscribe"]
    require(bool(subscribe_links), "README must link to the Attention Heads subscribe page")
    require(
        any(
            parsed.netloc == "attentionheads.substack.com"
            and parse_qs(parsed.query).get("utm_campaign") == ["astra-advisor"]
            for parsed in subscribe_links
        ),
        "README subscribe link must track astra-advisor",
    )
    for target in links:
        check_relative_link(target, repo, "README link")

marketplace_path = repo / ".agents" / "plugins" / "marketplace.json"
marketplace = require_mapping(load_json(marketplace_path, "marketplace"), "marketplace")
require_string(marketplace, "name", "marketplace", "astra-advisor")
marketplace_interface = require_mapping(marketplace.get("interface"), "marketplace.interface")
require_string(marketplace_interface, "displayName", "marketplace.interface", "Astra Advisor")
entries = marketplace.get("plugins")
require(isinstance(entries, list), "marketplace.plugins must be an array")
astra_entries = [entry for entry in entries if isinstance(entry, dict) and entry.get("name") == "astra-advisor"] if isinstance(entries, list) else []
require(len(astra_entries) == 1, "marketplace must contain exactly one astra-advisor entry")
if len(astra_entries) == 1:
    entry = astra_entries[0]
    source = require_mapping(entry.get("source"), "marketplace entry.source")
    require_string(source, "source", "marketplace entry.source", "local")
    require_string(source, "path", "marketplace entry.source", "./plugins/astra-advisor")
    policy = require_mapping(entry.get("policy"), "marketplace entry.policy")
    require_string(policy, "installation", "marketplace entry.policy", "AVAILABLE")
    require_string(policy, "authentication", "marketplace entry.policy", "ON_INSTALL")
    require_string(entry, "category", "marketplace entry", "Productivity")
    source_target = (repo / source["path"][2:]) if isinstance(source.get("path"), str) and source["path"].startswith("./") else None
    require(source_target is not None and (source_target / ".codex-plugin" / "plugin.json").is_file(), "marketplace source path must resolve to the plugin manifest")

license_path = repo / "LICENSE"
require(license_path.is_file(), f"missing LICENSE: {license_path}")
if license_path.is_file():
    license_text = license_path.read_text(encoding="utf-8")
    require(license_text.startswith("MIT License\n"), "LICENSE must use the MIT license")
    require("Copyright (c) 2026 Daniel McAteer" in license_text, "LICENSE must retain the existing MIT attribution")

gitignore_path = repo / ".gitignore"
require(gitignore_path.is_file(), f"missing .gitignore: {gitignore_path}")
if gitignore_path.is_file():
    ignored = {line.strip() for line in gitignore_path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")}
    require("*.log" in ignored and "logs/" in ignored, ".gitignore must exclude log files and the logs directory")

workflow_path = repo / ".github" / "workflows" / "verify.yml"
require(workflow_path.is_file(), f"missing CI workflow: {workflow_path}")
if workflow_path.is_file():
    workflow = workflow_path.read_text(encoding="utf-8")
    require("actions/checkout@v4" in workflow, "CI workflow must check out the repository")
    require("plugins/astra-advisor/scripts/verify.sh" in workflow, "CI workflow must run the repository verifier")

# This plugin intentionally has no static role files or installation companion.
for path in plugin.rglob("*"):
    if path.is_file() and path.suffix == ".toml":
        errors.append(f"static role TOML is not allowed: {path.relative_to(plugin)}")
require(not (plugin / "scripts" / "install-agents.sh").exists(), "companion installer is not allowed")

# Exercise accounting behavior as part of the same local and CI verifier.
result = subprocess.run(
    [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(plugin / "tests"), "-p", "test_*.py"],
    cwd=repo,
)
require(result.returncode == 0, "cost receipt tests failed")

if errors:
    print("VERIFY FAILED")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)

print("VERIFY PASSED")
print("manifest, marketplace, skill references, README links, license, CI, and static-role boundaries are valid")
PY
