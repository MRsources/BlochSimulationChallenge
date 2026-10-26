"""Give submission folders on main the next free id.

Evaluation runs this before the plots. A folder that already has an id is
left alone. The number is one past the highest id on main or on the
submissions branch, not on an open bot/issue branch. A queued run merges ids that an earlier run already
pushed, so two merges do not take the same number.
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


def take_ids_already_on_main() -> None:
    """Merge ``origin/main`` so a queued run sees ids already pushed."""
    fetched = _git('fetch', 'origin', 'main')
    if fetched.returncode != 0:
        err = (fetched.stderr or fetched.stdout or '').strip()
        raise SystemExit(err or 'could not fetch main')
    merged = subprocess.run(
        [
            'git',
            '-c', 'user.name=github-actions[bot]',
            '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
            'merge', '--no-edit', 'origin/main',
        ],
        cwd=ROOT, text=True, capture_output=True,
    )
    if merged.returncode != 0:
        err = (merged.stderr or merged.stdout or '').strip()
        raise SystemExit(err or 'could not include ids already committed on main')
    if merged.stdout.strip():
        print(merged.stdout, end='' if merged.stdout.endswith('\n') else '\n')


def assign() -> None:
    take_ids_already_on_main()
    try:
        reserved = id_sources(ROOT)
    except RuntimeError as exc:
        print(f'could not read the submissions branch: {exc}', flush=True)
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
