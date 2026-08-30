"""Carga contexto desde el repo de Fyodos y rutas extra."""

from __future__ import annotations

import os
from pathlib import Path

CONTEXT_EXTENSIONS = {".md", ".txt", ".json"}

PRIORITY_FILES = (
    "README.md",
    "README.md",
    "README.md",
    "README.md",
    "README.md",
)

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".claude",
    "node_modules",
    "mobile",
    "scripts/.venv",
    ".expo",
    ".next",
    "dist",
    "build",
    "coverage",
    "tarballs",
    "ios",
    "android",
}
SKIP_PREFIXES = ()
SKIP_FILE_NAMES = {".env", "local-secret", "modelWeights.json"}


def _default_context_roots(primary: Path) -> list[Path]:
    """Solo el repo configurado en JARVIS_CONTEXT_DIR.

    Cualquier otra carpeta debe declararse en JARVIS_CONTEXT_PATHS.
    """
    return [primary.resolve()]


def _extra_roots_from_env() -> list[Path]:
    raw = os.getenv("JARVIS_CONTEXT_PATHS", "").strip()
    if not raw:
        return []
    return [Path(p.strip()).expanduser() for p in raw.split(":") if p.strip()]


def _should_skip(path: Path, repo_root: Path) -> bool:
    if path.name in SKIP_FILE_NAMES:
        return True
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        rel = path
    if any(part in SKIP_DIRS for part in rel.parts):
        return True
    rel_str = str(rel)
    return any(rel_str.startswith(p) for p in SKIP_PREFIXES)


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _collect_from_root(
    repo_root: Path,
    parts: list[str],
    seen: set[Path],
    max_chars: int,
) -> int:
    total = 0

    def append_chunk(path: Path, text: str) -> bool:
        nonlocal total
        if not text:
            return True
        key = path.resolve()
        if key in seen:
            return True
        try:
            label = path.relative_to(repo_root)
        except ValueError:
            label = path
        chunk = f"### {label}\n{text}\n"
        if total + len(chunk) > max_chars:
            remaining = max_chars - total
            if remaining <= 500:
                return False
            chunk = chunk[:remaining] + "\n[...truncado...]\n"
        parts.append(chunk)
        total += len(chunk)
        seen.add(key)
        return total < max_chars

    for name in PRIORITY_FILES:
        path = repo_root / name
        if path.is_file() and not append_chunk(path, _read_file(path)):
            return total

    docs = repo_root / "docs"
    if docs.is_dir():
        for path in sorted(docs.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in CONTEXT_EXTENSIONS:
                continue
            if path.resolve() in seen or _should_skip(path, repo_root):
                continue
            if not append_chunk(path, _read_file(path)):
                return total

    for path in sorted(repo_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in CONTEXT_EXTENSIONS:
            continue
        if path.resolve() in seen or _should_skip(path, repo_root):
            continue
        if not append_chunk(path, _read_file(path)):
            break

    return total


def load_context(
    context_dir: Path,
    max_chars: int | None = None,
    extra_roots: list[Path] | None = None,
) -> str:
    if max_chars is None:
        max_chars = int(os.getenv("JARVIS_CONTEXT_MAX_CHARS", "96000"))

    primary = context_dir.resolve()
    roots = _default_context_roots(primary)
    roots.extend(_extra_roots_from_env())
    if extra_roots:
        roots.extend(extra_roots)

    parts: list[str] = []
    seen: set[Path] = set()
    total = 0

    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            text = _read_file(root)
            if text:
                chunk = f"### {root.name}\n{text}\n"
                if total + len(chunk) <= max_chars:
                    parts.append(chunk)
                    total += len(chunk)
                    seen.add(root.resolve())
            continue
        total = _collect_from_root(root, parts, seen, max_chars)
        if total >= max_chars:
            break

    return "\n".join(parts)
