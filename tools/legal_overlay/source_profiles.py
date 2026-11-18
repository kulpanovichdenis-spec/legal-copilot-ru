"""Load provider-neutral legal source profiles from Markdown frontmatter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tools.profile.profile_lib import repo_root


SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "source-profile.schema.json"
DEFAULT_PROFILES_DIR = repo_root() / "references" / "source-profiles"


class SourceProfileError(ValueError):
    """A controlled source-profile validation error."""


@dataclass(frozen=True)
class SourceProfile:
    source_id: str
    metadata: Mapping[str, Any]
    body: str
    path: Path

    def to_dict(self, *, include_body: bool = False) -> dict[str, Any]:
        result = dict(self.metadata)
        try:
            result["profile_path"] = self.path.resolve().relative_to(repo_root().resolve()).as_posix()
        except ValueError:
            result["profile_path"] = str(self.path.resolve())
        if include_body:
            result["guidance"] = self.body.strip()
        return result


def _split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        raise SourceProfileError(f"source profile has no YAML frontmatter: {path}")
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise SourceProfileError(f"source profile frontmatter is not closed: {path}") from exc
    loaded = yaml.safe_load("\n".join(lines[1:closing]))
    if not isinstance(loaded, dict):
        raise SourceProfileError(f"source profile frontmatter must be a mapping: {path}")
    return loaded, "\n".join(lines[closing + 1 :]).strip()


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_norm_verification(metadata: Mapping[str, Any], path: Path) -> None:
    roles = set(metadata["verification_roles"])
    coverage = metadata["coverage"]
    contract = metadata["norm_verification"]
    eligible = bool(contract["eligible"])

    if eligible and "norm_verification" not in roles:
        raise SourceProfileError(
            f"eligible norm verification profile must declare norm_verification role: {path}"
        )
    if not eligible and "norm_verification" in roles:
        raise SourceProfileError(
            f"ineligible profile cannot declare norm_verification role: {path}"
        )
    if contract["mode"] == "pending_capability_smoke" and "candidate_norm_verification" not in roles:
        raise SourceProfileError(
            f"pending norm verification profile must declare candidate_norm_verification role: {path}"
        )
    if eligible:
        if contract["mode"] not in {"live_official", "live_professional", "manual_professional"}:
            raise SourceProfileError(f"eligible norm verification profile has an invalid mode: {path}")
        if metadata["status"] != "active":
            raise SourceProfileError(f"eligible norm verification profile must have active status: {path}")
        missing_coverage = [
            field
            for field in ("full_text", "historical_versions", "current_status", "pinpoint", "provenance")
            if coverage[field] is False or coverage[field] == "unknown"
        ]
        if missing_coverage:
            raise SourceProfileError(
                f"eligible norm verification profile lacks required coverage {missing_coverage}: {path}"
            )
        if not contract["verified_tools"] or not contract["last_smoke_at"]:
            raise SourceProfileError(
                f"eligible norm verification profile requires verified_tools and last_smoke_at: {path}"
            )


def _validate_protocol_refs(metadata: Mapping[str, Any], path: Path, repository: Path) -> None:
    root = repository.resolve()
    for reference in metadata.get("protocol_refs", []):
        target = (root / str(reference)).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise SourceProfileError(f"protocol reference leaves repository in {path}: {reference}") from exc
        if not target.is_file():
            raise SourceProfileError(f"protocol reference does not exist in {path}: {reference}")


def load_source_profiles(
    directory: Path | None = None,
    *,
    repository: Path | None = None,
) -> tuple[SourceProfile, ...]:
    repository_path = (repository or repo_root()).resolve()
    profiles_dir = (directory or repository_path / "references" / "source-profiles").resolve()
    if not profiles_dir.exists():
        return ()

    validator = _validator()
    profiles: list[SourceProfile] = []
    seen: set[str] = set()
    for path in sorted(profiles_dir.glob("*.md")):
        if path.name.upper() == "INDEX.MD":
            continue
        metadata, body = _split_frontmatter(path.read_text(encoding="utf-8"), path)
        errors = sorted(validator.iter_errors(metadata), key=lambda error: list(error.absolute_path))
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.absolute_path) or "root"
            raise SourceProfileError(f"invalid source profile {path.name} at {location}: {first.message}")
        source_id = str(metadata["id"])
        if source_id in seen:
            raise SourceProfileError(f"duplicate source profile id: {source_id}")
        seen.add(source_id)
        _validate_norm_verification(metadata, path)
        _validate_protocol_refs(metadata, path, repository_path)
        profiles.append(SourceProfile(source_id=source_id, metadata=metadata, body=body, path=path))
    return tuple(profiles)


def source_profile_map(profiles: Iterable[SourceProfile]) -> dict[str, SourceProfile]:
    return {profile.source_id: profile for profile in profiles}
