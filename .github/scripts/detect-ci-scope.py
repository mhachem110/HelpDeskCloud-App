"""Run expensive CI groups only when their inputs changed.

The workflow itself is not path-filtered, so required PR checks still receive a
result for documentation-only changes. If the event diff cannot be read, the
safe choice is to run every validation group.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
from pathlib import Path


GROUPS = {
    "app-ci": {
        "dotnet": (
            "src/**",
            "tests/HelpDeskCloud.Tests/**",
            ".github/workflows/app-ci.yml",
            ".github/scripts/detect-ci-scope.py",
            ".github/scripts/verify-dotnet.sh",
        ),
        "container": (
            "src/**",
            "Dockerfile",
            ".dockerignore",
            ".github/workflows/app-ci.yml",
        ),
        "helm": (
            "helm/**",
            "k8s/**",
            "tests/test_*.py",
            ".github/scripts/*.py",
            ".github/scripts/*.sh",
            ".github/workflows/*.yml",
        ),
    },
    "supporting-images": {
        "supporting_images": (
            "database/migration-client/**",
            ".dockerignore",
            ".github/workflows/supporting-images-ci.yml",
            ".github/scripts/detect-ci-scope.py",
        ),
    },
}

ZERO_SHA = "0" * 40


def changed_paths(event_name: str, before: str, base_sha: str, head_sha: str) -> set[str] | None:
    """Return changed paths, or None when a complete diff is not available."""
    if event_name == "workflow_dispatch":
        return None
    if event_name == "push":
        if not before or before == ZERO_SHA or not head_sha:
            return None
        revisions = [before, head_sha]
    elif event_name == "pull_request":
        if not base_sha or not head_sha:
            return None
        revisions = [f"{base_sha}...{head_sha}"]
    else:
        return None

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", *revisions],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        return None
    return {path.replace("\\", "/") for path in result.stdout.splitlines() if path}


def group_is_relevant(workflow: str, group: str, paths: set[str] | None) -> bool:
    """Fail open for an unknown diff and match paths against one CI group."""
    if paths is None:
        return True
    patterns = GROUPS[workflow][group]
    return any(fnmatch.fnmatchcase(path, pattern) for path in paths for pattern in patterns)


def write_outputs(workflow: str, output_file: Path, paths: set[str] | None) -> None:
    if workflow not in GROUPS:
        raise ValueError(f"unknown CI workflow group: {workflow}")
    with output_file.open("a", encoding="utf-8", newline="\n") as output:
        for name in GROUPS[workflow]:
            value = "true" if group_is_relevant(workflow, name, paths) else "false"
            output.write(f"{name}={value}\n")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: detect-ci-scope.py WORKFLOW OUTPUT_FILE", file=sys.stderr)
        return 2

    workflow, output_path = sys.argv[1:]
    paths = changed_paths(
        event_name=os.environ.get("GITHUB_EVENT_NAME", ""),
        before=os.environ.get("GITHUB_EVENT_BEFORE", ""),
        base_sha=os.environ.get("GITHUB_BASE_SHA", ""),
        head_sha=os.environ.get("GITHUB_HEAD_SHA", ""),
    )
    if paths is None:
        print("::notice::No complete event diff is available; enabling all validation groups.")
    write_outputs(workflow, Path(output_path), paths)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"::error::Could not select CI scope: {error}", file=sys.stderr)
        raise SystemExit(1)
