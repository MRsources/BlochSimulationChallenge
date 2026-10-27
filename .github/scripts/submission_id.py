"""Submission folder ids: ``001_<tool>``, ``002_<tool>``, and so on.

Numbers already present under ``submissions/`` are kept. The next submission
takes one more than the highest number, so a removed id is not reused.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

FOLDER = re.compile(r'^(\d{3})_(.+)\Z')
TOOL = re.compile(r'^[A-Za-z0-9._-]+\Z')


def parse_id(name: str) -> tuple[int, str] | None:
    """Return ``(number, tool)`` for ``001_tool``. ``000_tool`` is not an id."""
    match = FOLDER.fullmatch(name)
    if match is None:
        return None
    number = int(match.group(1))
    tool = match.group(2)
    if number < 1 or not TOOL.fullmatch(tool):
        return None
    return number, tool


def next_number(names: list[str]) -> int:
    """One past the highest id in ``names``, or 1 when there is none."""
    numbers = [parsed[0] for name in names if (parsed := parse_id(name))]
    nxt = max(numbers) + 1 if numbers else 1
    if nxt > 999:
        raise ValueError('no submission id left after 999')
    return nxt


def assign_folder(tool: str, existing: list[str], previous: list[str]) -> str:
    """Folder for an issue accept.

    ``previous`` is the folders this same issue already wrote. The first
    accept takes the next id. A later accept keeps that number unless some
    other submission already published it.
    """
    if not TOOL.fullmatch(tool):
        raise ValueError(f'{tool} is not a usable tool name')
    owned = sorted(parsed[0] for name in previous if (parsed := parse_id(name)))
    foreign = {
        parsed[0]
        for name in existing
        if (parsed := parse_id(name)) and name not in previous
    }
    if owned and owned[0] not in foreign:
        return f'{owned[0]:03d}_{tool}'
    return f'{next_number(existing):03d}_{tool}'


def submission_dirs(root: Path) -> list[Path]:
    """Submission folders on disk: a sheet or a case file, hidden names aside."""
    submissions = root / 'submissions'
    if not submissions.is_dir():
        return []
    found = []
    for folder in sorted(path for path in submissions.iterdir() if path.is_dir()):
        if folder.name.startswith('.'):
            continue
        has_sheet = (folder / 'submission.json').is_file()
        has_case = any(folder.glob('case[0-4].h5'))
        if has_sheet or has_case:
            found.append(folder)
    return found


def plan_new_ids(folders: list[Path], reserved: list[str]) -> list[tuple[str, str]]:
    """Ids for folders that arrived without one.

    ``reserved`` counts numbers already published on ``main``, on
    ``eval``, or on the ``submissions`` branch, so those ids are not
    given out again. A folder
    that already has an id is left as it is. The open ``bot/issue-<number>``
    branch has no id yet, so it does not reserve a number.
    """
    names = [folder.name for folder in folders]
    pending = [
        name for name in names
        if parse_id(name) is None and TOOL.fullmatch(name)
    ]
    if not pending:
        return []
    return rename_plan(list(reserved) + names, pending)


def rename_plan(
    taken: list[str], ours: list[str], owned: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Renames that give these folders their ids.

    ``taken`` is every folder name already published on ``main`` or staged
    on ``submissions``. ``owned`` is a number this same submission already
    published and may keep. The result is ``(current name, numbered name)``
    and omits folders that already have a free id.
    """
    owned_number = {
        parsed[1]: parsed[0]
        for name in (owned or [])
        if (parsed := parse_id(name))
    }
    foreign = {
        parsed[0]
        for name in taken
        if (parsed := parse_id(name)) and parsed[0] not in owned_number.values()
    }
    used = set(foreign)
    plan: list[tuple[str, str]] = []
    for folder in sorted(ours):
        parsed = parse_id(folder)
        if parsed is not None and parsed[0] not in used:
            used.add(parsed[0])
            continue
        tool = parsed[1] if parsed is not None else folder
        if not TOOL.fullmatch(tool):
            raise ValueError(f'{folder} is not a usable folder name')
        number = owned_number.get(tool)
        if number is None or number in foreign:
            number = max(used) + 1 if used else 1
        if number > 999:
            raise ValueError('no submission id left after 999')
        used.add(number)
        renamed = f'{number:03d}_{tool}'
        if renamed != folder:
            plan.append((folder, renamed))
    return plan


def open_pull_folders(repo: str, token: str, skip: int | None = None) -> list[str]:
    """Folder names under ``submissions/`` on open pull requests, except ``skip``."""
    from comment_on_issue import github_json

    found: list[str] = []
    seen: set[str] = set()
    for page in range(1, 11):
        pulls = github_json(
            'GET',
            f'https://api.github.com/repos/{repo}/pulls?state=open&per_page=100&page={page}',
            token,
        )
        if not isinstance(pulls, list):
            raise RuntimeError('the open pull request list was not a list')
        if not pulls:
            break
        for pull in pulls:
            number = pull.get('number')
            if skip is not None and number == skip:
                continue
            if not isinstance(number, int):
                continue
            files = github_json(
                'GET',
                f'https://api.github.com/repos/{repo}/pulls/{number}/files?per_page=100',
                token,
            )
            if not isinstance(files, list):
                raise RuntimeError(f'pull request {number} file list was not a list')
            for item in files:
                parts = Path(str(item.get('filename') or '')).parts
                if len(parts) < 2 or parts[0] != 'submissions' or parts[1] in seen:
                    continue
                seen.add(parts[1])
                found.append(parts[1])
        if len(pulls) < 100:
            break
    return found


def folders_at(cwd: Path, rev: str) -> list[str]:
    """Directory names inside ``submissions/`` at a git revision. Empty when absent."""
    listed = subprocess.run(
        ['git', 'ls-tree', '--name-only', f'{rev}:submissions'],
        cwd=cwd, text=True, capture_output=True,
    )
    if listed.returncode != 0:
        return []
    return [line.strip() for line in listed.stdout.splitlines() if line.strip()]


def remote_folders(cwd: Path, branch: str = 'submissions') -> list[str]:
    """Folder names on ``origin/<branch>``. Empty when that branch does not exist."""
    fetched = subprocess.run(
        ['git', 'fetch', 'origin', branch],
        cwd=cwd, text=True, capture_output=True,
    )
    if fetched.returncode != 0:
        err = (fetched.stderr or fetched.stdout or '').strip()
        if "couldn't find remote ref" in err or 'not found' in err.lower():
            return []
        raise RuntimeError(err or f'could not fetch the {branch} branch')
    return folders_at(cwd, f'origin/{branch}')


def id_sources(cwd: Path) -> list[str]:
    """Folders already published on ``main``, ``eval``, or ``submissions``.

    Pull requests and issue submissions land on ``main``. Evaluation
    assigns the id on ``eval``. A leftover ``submissions`` branch still
    counts, so an id that was staged there is not given out again.
    """
    names: list[str] = []
    seen: set[str] = set()
    for branch in ('main', 'eval', 'submissions'):
        for name in remote_folders(cwd, branch):
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names
