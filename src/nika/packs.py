from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from nextloop import HarnessError, LoopConfig, SkillRegistry

from .contracts import (
    EXPECTED_EVENT_SCHEMA,
    EXPECTED_NEXTLOOP_API,
    SpecialistId,
)

PACK_SCHEMA = "nika.specialist/v1"


@dataclass(frozen=True)
class SpecialistPack:
    specialist: SpecialistId
    tools: frozenset[str]
    skills: tuple[str, ...]
    loop_config: LoopConfig
    skill_registry: SkillRegistry | None = None


def _load_shared_texts(root: Path) -> tuple[str, str]:
    shared_dir = root / "_shared"
    red_lines_path = shared_dir / "RED_LINES.md"
    if not red_lines_path.is_file():
        raise HarnessError(f"Missing shared red lines: {red_lines_path}")
    compaction_path = shared_dir / "COMPACTION.md"
    compaction = (
        compaction_path.read_text(encoding="utf-8").strip()
        if compaction_path.is_file()
        else ""
    )
    return red_lines_path.read_text(encoding="utf-8").strip(), compaction


def _build_loop_config(
    raw: Mapping[str, Any], full_prompt: str, compaction_prompt: str
) -> LoopConfig:
    loop_raw = dict(raw.get("loop") or {})
    return LoopConfig(
        system_prompt=full_prompt,
        compaction_prompt=compaction_prompt,
        context_window=int(loop_raw.get("context_window", 128_000)),
        output_reserve=int(loop_raw.get("output_reserve", 4_096)),
        max_steps=loop_raw.get("max_steps"),
    )


def _parse_single_pack(
    pack_dir: Path,
    red_lines: str,
    compaction_prompt: str,
    available: frozenset[str],
) -> SpecialistPack:
    toml_path = pack_dir / "pack.toml"
    prompt_path = pack_dir / "prompt.md"
    if not toml_path.is_file() or not prompt_path.is_file():
        raise HarnessError(f"Incomplete specialist pack in {pack_dir}")
    with toml_path.open("rb") as fp:
        raw: dict[str, Any] = tomllib.load(fp)
    if raw.get("schema") != PACK_SCHEMA:
        raise HarnessError(f"{toml_path}: expected schema '{PACK_SCHEMA}'")
    if raw.get("min_nextloop") != EXPECTED_NEXTLOOP_API:
        raise HarnessError(f"{toml_path}: min_nextloop mismatch")
    if raw.get("event_schema") != EXPECTED_EVENT_SCHEMA:
        raise HarnessError(f"{toml_path}: event_schema mismatch")
    specialist = SpecialistId(str(raw["name"]))
    if specialist.value != pack_dir.name:
        raise HarnessError(f"{toml_path}: name does not match directory")
    tools = frozenset(str(t) for t in raw.get("tools", []))
    missing = sorted(tools - available - {"skill_view", "read_tool_result"})
    if missing:
        raise HarnessError(
            f"{toml_path}: unknown tools in allowlist: {', '.join(missing)}"
        )
    role_prompt = prompt_path.read_text(encoding="utf-8").strip()
    return SpecialistPack(
        specialist=specialist,
        tools=tools,
        skills=tuple(str(s) for s in raw.get("skills", [])),
        loop_config=_build_loop_config(
            raw, f"{red_lines}\n\n{role_prompt}", compaction_prompt
        ),
    )


def _build_pack_skills(
    shared_skills_dir: Path | None, pack: SpecialistPack
) -> SkillRegistry | None:
    if shared_skills_dir is None or not pack.skills:
        return None
    base = shared_skills_dir.expanduser().resolve()
    skill_dirs = [base / name for name in pack.skills]
    allowed = tuple(pack.tools | {"skill_view", "read_tool_result"})
    return SkillRegistry(skill_dirs, available_tools=allowed)


def load_specialist_packs(
    specialists_root: Path,
    *,
    available_tools: Sequence[str],
    shared_skills_dir: Path | None = None,
) -> dict[SpecialistId, SpecialistPack]:
    root = specialists_root.expanduser().resolve()
    red_lines, compaction = _load_shared_texts(root)
    available = frozenset(available_tools)
    subdirs = [
        p
        for p in sorted(root.iterdir())
        if p.is_dir() and not p.name.startswith("_")
    ]
    packs: dict[SpecialistId, SpecialistPack] = {}
    for subdir in subdirs:
        parsed = _parse_single_pack(subdir, red_lines, compaction, available)
        reg = _build_pack_skills(shared_skills_dir, parsed)
        packs[parsed.specialist] = replace(parsed, skill_registry=reg)
    if not packs:
        raise HarnessError(f"No specialist packs found in {root}")
    return packs
