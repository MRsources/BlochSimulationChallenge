"""Kept for reference. The evaluation workflow does not run this.

The id is part of the folder name when the submission is written.
``NNN_<tool>`` is the next number after the highest folder already in
``submissions/``. Plotting uses that name as it stands.
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
