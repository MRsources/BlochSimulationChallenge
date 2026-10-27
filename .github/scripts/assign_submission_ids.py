"""Give submission folders on the eval branch the next free id.

The workflow has already updated ``eval`` from ``main``. This script
renames a folder that arrived without an id, then the plots run. A
folder that already has an id is left alone. The number is one past the
highest id on ``main``, on ``eval``, or on the leftover ``submissions``
branch. Merge ``eval`` back into ``main`` by hand.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from submission_id import id_sources, plan_new_ids, submission_dirs  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['git', *args], cwd=ROOT, text=True, capture_output=True,
    )


def assign() -> None:
    try:
        reserved = id_sources(ROOT)
    except RuntimeError as exc:
        print(f'could not read a branch used for ids: {exc}', flush=True)
        reserved = []
    plan = plan_new_ids(submission_dirs(ROOT), reserved)
    if not plan:
        print('no new submission id')
        return
    for old, new in plan:
        dest = ROOT / 'submissions' / new
        if dest.exists():
            raise SystemExit(f'{new} is already in the tree')
        moved = _git('mv', f'submissions/{old}', f'submissions/{new}')
        if moved.returncode != 0:
            err = (moved.stderr or moved.stdout or '').strip()
            raise SystemExit(err or f'could not rename {old}')
        print(f'{old} -> {new}', flush=True)


if __name__ == '__main__':
    assign()
