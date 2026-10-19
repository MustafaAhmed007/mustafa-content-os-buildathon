"""Local POSIX journal for finalizer transactions, independent of creative copy."""

from contextlib import contextmanager
from datetime import date
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


def canonical_path(root, content_path):
    directory = Path(root).resolve() / "content/carousels"
    raw = Path(content_path)
    if raw.is_symlink():
        raise ValueError("Artifact aliases are forbidden")
    path = raw.absolute()
    if directory.resolve() != directory or path.parent.resolve() != directory:
        raise ValueError("Use a regular artifact directly in content/carousels; aliases and nested output paths are forbidden")
    path = directory / path.name
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*", path.stem)
    if path.suffix != ".yaml" or not match:
        raise ValueError("Use content/carousels/YYYY-MM-DD-<slug>.yaml")
    date.fromisoformat(match.group(1))
    for target in (path, path.with_suffix(".md"), path.with_suffix(".validation-failure.json")):
        if target.is_symlink() or (target.exists() and (not target.is_file() or target.stat().st_nlink != 1)):
            raise ValueError("Artifact files must be regular, single-link files")
    return path


def state_path(path):
    directory = path.parent / ".workflow-state"
    if directory.is_symlink():
        raise ValueError("Workflow state directory must not be a symlink")
    target = directory / (path.stem + ".json")
    if target.is_symlink():
        raise ValueError("Workflow state must not be a symlink")
    return target


@contextmanager
def locked(path):
    """Serialize one artifact; an interrupted process never removes its journal."""
    target = state_path(path)
    target.parent.mkdir(exist_ok=True)
    lock_path = target.with_suffix(".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(descriptor).st_nlink != 1:
            raise ValueError("Workflow lock must not be a hard link")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield target
    finally:
        os.close(descriptor)


def atomic_json(path, document):
    """Commit one durable journal record; interrupted writes retain the old state."""
    descriptor, name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def output_hashes(path):
    return {target.name: hashlib.sha256(target.read_bytes()).hexdigest()
            for target in (path, path.with_suffix(".md"))}


def binding(path, root):
    return {"artifact_id": path.stem, "artifact_path": str(path.relative_to(root)), "version": 1}


def check_record(record, path, root):
    if not isinstance(record, dict) or any(record.get(key) != value for key, value in binding(path, root).items()):
        raise ValueError("Journal identity/version does not match this artifact")
    if record.get("state") not in {"RUNNING", "FAIL", "COMPLETE"}:
        raise ValueError("Invalid journal state")
    if record["state"] != "RUNNING":
        result = record.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("errors"), list):
            raise ValueError("Journal has no authoritative result")
        passed = record["state"] == "COMPLETE"
        if (result.get("valid") is not passed or result.get("continue") is not passed
                or result.get("result") != ("PASS" if passed else "FAIL")
                or bool(result["errors"]) is passed
                or result.get("artifact_id") != path.stem
                or result.get("artifact_path") != str(path.relative_to(root))):
            raise ValueError("Journal result is inconsistent with its state/identity")
        if passed and (not isinstance(record.get("outputs"), dict)
                       or set(record["outputs"]) != {path.name, path.with_suffix('.md').name}):
            raise ValueError("Completed journal must bind both output hashes")
    return record
