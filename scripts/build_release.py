from __future__ import annotations

import argparse
import fnmatch
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NAME = "fa-kara-studio-source.zip"
INCLUDE = (
    "*.py",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "requirements-core.txt",
    "requirements-gui.txt",
    "environment.yml",
    "ruby_timeline_component/index.html",
    "scripts/*.sh",
    "scripts/*.ps1",
    "scripts/build_release.py",
    "songs/*/README.md",
    "songs/playlist_order.txt",
)
EXCLUDE_PARTS = {".git", ".venv", ".kara_gui_runs", "__pycache__", "dist"}


def included(relative_path: str) -> bool:
    path = Path(relative_path)
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return False
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in INCLUDE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a source-only FA-Kara Studio release archive.")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / DEFAULT_NAME)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(
        path for path in ROOT.rglob("*")
        if path.is_file() and included(path.relative_to(ROOT).as_posix())
    )
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path("FA-Kara-Studio") / path.relative_to(ROOT))

    print(f"Created {output} ({len(files)} files)")


if __name__ == "__main__":
    main()
