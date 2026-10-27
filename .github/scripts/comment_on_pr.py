"""Validate submission folders changed by a pull request, and comment.

The workflow checks out this script from the tip of main and points it
at the pull request's files. A submission cannot replace the checker.
The file list comes from the pull request API. Each
``submissions/<tool>/`` directory is passed to ``validate_submission.review``.
The folder name already carries the id. Evaluation commits the
comparison on ``main``.
A fork is merged like any other pull request.

    PR_NUMBER=4 PR_DIR=/tmp/pr GITHUB_REPOSITORY=owner/name \\
        GITHUB_TOKEN=... python .github/scripts/comment_on_pr.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_submission import review  # noqa: E402

REPO_NAME = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
TOOL_NAME = re.compile(r'^[A-Za-z0-9._-]+$')
ALLOWED_ROOT_FILES = {'README.md'}
MAIN_BRANCH = 'main'
FAULTY_BRANCH = 'faulty-submissions'


def github_json(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'bloch-sim-challenge',
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def post_comment(repo: str, number: int, token: str, body: str) -> None:
    """Comment on the pull request. GitHub stores that comment on the issue."""
    github_json(
        'POST',
        f'https://api.github.com/repos/{repo}/issues/{number}/comments',
        token,
        {'body': body},
    )


def pull_filenames(repo: str, number: int, token: str) -> list[str]:
    """Every file the pull request changes, including deletions."""
    names: list[str] = []
    for page in range(1, 11):
        url = (
            f'https://api.github.com/repos/{repo}/pulls/{number}/files'
            f'?per_page=100&page={page}'
        )
        batch = github_json('GET', url, token)
        if not isinstance(batch, list):
            raise RuntimeError('the pull request file list was not a list')
        names.extend(str(item.get('filename') or '') for item in batch)
        if len(batch) < 100:
            return names
    raise RuntimeError('the pull request changes more than 1000 files')


def changed_tools(filenames: list[str]) -> tuple[list[str], list[str]]:
    """Return ``(tool folder names, problem lines)`` for ``submissions/`` paths."""
    tools: list[str] = []
    problems: list[str] = []
    seen: set[str] = set()
    for name in filenames:
        parts = Path(name).parts
        if not parts or parts[0] != 'submissions':
            continue
        if len(parts) == 2 and parts[1] in ALLOWED_ROOT_FILES:
            continue
        if len(parts) == 2:
            problems.append(
                f'`{name}` is directly in `submissions/`. '
                'Use `submissions/<tool>/`.'
            )
            continue
        if len(parts) != 3:
            problems.append(
                f'`{name}` is nested too deeply. Expected `submissions/<tool>/<file>`.'
            )
            continue
        tool = parts[1]
        if tool in seen:
            continue
        seen.add(tool)
        if not TOOL_NAME.fullmatch(tool) or tool in {'.', '..'}:
            problems.append(f'`submissions/{tool}/` is not a usable folder name.')
            continue
        tools.append(tool)
    return tools, problems


def report_changes(pr_dir: Path, filenames: list[str]) -> tuple[bool, str]:
    """Format-check each changed ``submissions/<tool>/`` directory."""
    tools, problems = changed_tools(filenames)
    blocks: list[str] = []
    ok = not problems
    blocks.extend(f'- {line}' for line in problems)
    if not tools and not problems:
        readme_only = [
            name for name in filenames
            if (parts := Path(name).parts)
            and parts[0] == 'submissions'
            and len(parts) == 2
            and parts[1] in ALLOWED_ROOT_FILES
        ]
        if readme_only:
            return True, '- `submissions/README.md` only; not a submission.'
        return False, '- no files under `submissions/`'
    for tool in tools:
        folder = pr_dir / 'submissions' / tool
        if not folder.is_dir():
            blocks.append(f'- `submissions/{tool}/`: removed, nothing left to check')
            continue
        folder_ok, report = review([folder])
        ok = ok and folder_ok
        indented = '\n'.join(f'  {line}' for line in report.splitlines())
        blocks.append(f'`submissions/{tool}/`\n\n{indented}')
    return ok, '\n\n'.join(blocks)


def environment() -> tuple[str, int, str, Path, str]:
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    if not REPO_NAME.fullmatch(repo):
        raise SystemExit('GITHUB_REPOSITORY must be owner/name')
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        raise SystemExit('GITHUB_TOKEN is not set')
    try:
        number = int(os.environ.get('PR_NUMBER') or '')
    except ValueError:
        raise SystemExit('PR_NUMBER must be an integer') from None
    if number < 1:
        raise SystemExit('PR_NUMBER must be positive')
    pr_dir = Path(os.environ.get('PR_DIR', ''))
    if not pr_dir.is_dir():
        raise SystemExit('PR_DIR must be the pull request checkout')
    base = os.environ.get('BASE_REF', '')
    return repo, number, token, pr_dir, base


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ['git', *args], cwd=cwd, text=True, capture_output=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or '').strip()
        raise RuntimeError(err or f'git {args[0]} failed')
    return result


def _gh(token: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env['GH_TOKEN'] = token
    result = subprocess.run(['gh', *args], text=True, capture_output=True, env=env)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or '').strip()
        if 'already' in err.lower():
            return result
        raise RuntimeError(err or f'gh {args[0]} failed')
    return result


def ensure_faulty_branch(cwd: Path) -> None:
    """Create ``faulty-submissions`` from ``main`` when it does not exist yet."""
    fetched = subprocess.run(
        ['git', 'fetch', 'origin', FAULTY_BRANCH],
        cwd=cwd, text=True, capture_output=True,
    )
    if fetched.returncode == 0:
        return
    _git(cwd, 'fetch', 'origin', MAIN_BRANCH)
    _git(cwd, 'push', 'origin', f'origin/{MAIN_BRANCH}:refs/heads/{FAULTY_BRANCH}')


def publish_faulty(base_dir: Path, pr_dir: Path, tools: list[str], number: int) -> list[str]:
    """Copy the failed folders onto ``faulty-submissions``.

    The branch is where an unevaluated submission lives. Evaluation runs
    on ``main`` after a folder has landed there, so a folder that failed
    the format check is written here under the same
    ``submissions/<tool>/`` name. A later failure of the same folder
    replaces the copy.
    """
    present = [
        name for name in tools
        if (pr_dir / 'submissions' / name).is_dir()
    ]
    if not present:
        return []
    ensure_faulty_branch(base_dir)
    _git(base_dir, 'fetch', 'origin', FAULTY_BRANCH)
    _git(base_dir, 'checkout', '-B', FAULTY_BRANCH, f'origin/{FAULTY_BRANCH}')
    written: list[str] = []
    for name in present:
        src = pr_dir / 'submissions' / name
        if not src.is_dir():
            continue
        dest = base_dir / 'submissions' / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        _git(base_dir, 'add', '-A', '--', f'submissions/{name}')
        written.append(name)
    if not written:
        return []
    status = _git(base_dir, 'status', '--porcelain')
    if not status.stdout.strip():
        return written
    subprocess.run(
        [
            'git',
            '-c', 'user.name=github-actions[bot]',
            '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
            'commit', '-m', f'Keep unevaluated submission from pull request {number}',
        ],
        cwd=base_dir, check=True,
    )
    _git(base_dir, 'push', 'origin', f'HEAD:refs/heads/{FAULTY_BRANCH}')
    return written


def retarget(repo: str, number: int, token: str, base: str) -> None:
    """Point the pull request at ``base``. No effect when it is already there."""
    _gh(token, 'pr', 'edit', str(number), '--repo', repo, '--base', base)


def close_pr(repo: str, number: int, token: str) -> None:
    """Close the pull request. A corrected submission is a new pull request."""
    _gh(token, 'pr', 'close', str(number), '--repo', repo)


def comment_on_pr() -> None:
    repo, number, token, pr_dir, base = environment()
    try:
        filenames = pull_filenames(repo, number, token)
    except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
        post_comment(
            repo, number, token,
            'Format check stopped before validation.\n\n'
            f'Failed at: `list pull request files`\nTarget: `pulls/{number}/files`\n'
            f'Error: {exc}',
        )
        raise SystemExit(1) from exc
    ok, report = report_changes(pr_dir, filenames)
    status = 'Format check passed.' if ok else 'Format check failed.'
    tools, _problems = changed_tools(filenames)
    tools = [
        name for name in tools
        if (pr_dir / 'submissions' / name).is_dir()
    ]
    id_note = ''
    move_note = ''
    if ok and tools:
        id_note = (
            '\n\nMerge this pull request into `main`. '
            'Evaluation rebuilds the comparison and commits it on `main`.'
        )
        if base and base != MAIN_BRANCH:
            try:
                retarget(repo, number, token, MAIN_BRANCH)
                move_note = f'\n\nThis pull request now targets `{MAIN_BRANCH}`.'
            except (RuntimeError, OSError) as exc:
                move_note = (
                    f'\n\nThe pull request still targets `{base}` because moving '
                    f'it to `{MAIN_BRANCH}` failed.\n\nError: {exc}'
                )
    elif not ok:
        try:
            base_dir = Path(os.environ.get('BASE_DIR', ''))
            cwd = base_dir if base_dir.is_dir() else pr_dir
            kept = publish_faulty(cwd, pr_dir, tools, number)
            close_pr(repo, number, token)
            names = ', '.join(f'`submissions/{name}/`' for name in kept)
            placed = f' {names} is on `{FAULTY_BRANCH}`.' if names else ''
            move_note = (
                '\n\nThis pull request is closed.'
                f'{placed} Open a new pull request with the corrected files.'
            )
        except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
            move_note = (
                '\n\nThe pull request is still open because closing it '
                f'failed.\n\nError: {exc}'
            )
    post_comment(repo, number, token, f'{status}\n\n{report}{id_note}{move_note}')
    print(report, flush=True)
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    comment_on_pr()
