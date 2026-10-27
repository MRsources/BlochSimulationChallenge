"""Copy one validated issue onto ``bot/issue-<number>`` and open a PR into ``main``.

Called by the issue comment workflow once the format check has passed.
The token in ``GITHUB_TOKEN`` is the automatic one GitHub injected into
that run; this file does not create or store a token.

The branch starts at the tip of ``main``. The folder is
``submissions/<tool>/``, with no id yet. ``<tool>`` is the issue title
with the word ``submission`` removed. Push ``bot/issue-<number>`` and
open a pull request into ``main``. That pull request is not checked
again. An organiser merges it by hand. Evaluation assigns the id on
the ``eval`` branch. Merge ``eval`` back into ``main`` by hand. Editing the
issue after a pass updates the same branch and the same pull request.

    ISSUE_NUMBER=12 GITHUB_REPOSITORY=owner/name GITHUB_TOKEN=... \\
        python .github/scripts/open_submission_pr.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comment_on_issue import (  # noqa: E402
    download_cases,
    environment,
    fetch_issue,
    is_submission_title,
    post_comment,
    tool_folder,
)
from validate_submission import review  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git in the repo and keep stdout/stderr in the Actions log.

    Authentication comes from ``actions/checkout``: it rewrote the
    ``origin`` URL to use the job's GITHUB_TOKEN. This function does not
    put the token on the command line.
    """
    command = ['git', *args]
    print('+', ' '.join(command), flush=True)
    result = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end='' if result.stdout.endswith('\n') else '\n')
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(f'git failed ({result.returncode}): {args[0]}')
    return result


def remote_branch(name: str) -> bool:
    """True when ``origin`` already has a branch of this name.

    ``git ls-remote --exit-code`` returns 2 when the name is absent and
    0 when it is present. Any other code is a real failure (auth, network).
    """
    result = subprocess.run(
        ['git', 'ls-remote', '--exit-code', '--heads', 'origin', name],
        cwd=REPO_ROOT, text=True, capture_output=True,
    )
    if result.returncode in {0, 2}:
        return result.returncode == 0
    print(result.stderr, file=sys.stderr)
    raise SystemExit(f'git ls-remote failed ({result.returncode})')


def commit_all(message: str) -> bool:
    """Commit ``submissions/`` only. Return False when the tree is unchanged.

    The author is the GitHub Actions bot, set with ``git -c`` for this
    one command so the runner's global git config is left alone. An
    unchanged folder (same bytes as the last accept) is not an error.
    """
    git('add', '--', 'submissions')
    status = git('status', '--porcelain')
    if not status.stdout.strip():
        print('no file changes', flush=True)
        return False
    subprocess.run(
        [
            'git',
            '-c', 'user.name=github-actions[bot]',
            '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
            'commit', '-m', message,
        ],
        cwd=REPO_ROOT, check=True,
    )
    return True


def ensure_pr(repo: str, number: int, head: str, folder: str, token: str) -> str:
    """Return the URL of the PR from ``head`` into ``main``.

    ``gh`` does not read GITHUB_TOKEN. It reads GH_TOKEN, so the workflow
    passes the same secret under both names and this function sets
    GH_TOKEN again for the subprocess. If a PR for this head branch is
    already open, a later pass only needs the push above.
    """
    env = os.environ.copy()
    env['GH_TOKEN'] = token
    listed = subprocess.run(
        [
            'gh', 'pr', 'list', '--repo', repo, '--head', head, '--base', 'main',
            '--json', 'url', '--jq', '.[0].url',
        ],
        cwd=REPO_ROOT, text=True, capture_output=True, env=env,
    )
    if listed.returncode != 0:
        print(listed.stderr, file=sys.stderr)
        raise SystemExit('could not list pull requests')
    existing = listed.stdout.strip()
    if existing and existing != 'null':
        return existing
    created = subprocess.run(
        [
            'gh', 'pr', 'create', '--repo', repo, '--base', 'main',
            '--head', head,
            '--title', f'Submission from issue {number}',
            '--body', (
                f'Files from https://github.com/{repo}/issues/{number}, '
                f'copied to `submissions/{folder}/` on `bot/issue-{number}`. '
                'Merge this pull request into `main`. Evaluation assigns the id '
                'on the `eval` branch. Merge `eval` back into `main` by hand.\n'
            ),
        ],
        cwd=REPO_ROOT, text=True, capture_output=True, env=env,
    )
    if created.returncode != 0:
        print(created.stderr, file=sys.stderr)
        raise SystemExit('could not open the pull request')
    return created.stdout.strip()


def publish_validated(
    repo: str, number: int, token: str, saved: list[Path], slug: str,
) -> str:
    """Put ``saved`` on ``bot/issue-<number>`` and open the pull request into ``main``."""
    head = f'bot/issue-{number}'
    git('fetch', 'origin', 'main')
    if remote_branch(head):
        git('fetch', 'origin', head)
    git('checkout', '-B', head, 'origin/main')
    target = REPO_ROOT / 'submissions' / slug
    if target.exists():
        raise SystemExit(f'submissions/{slug} is already on main')
    target.mkdir(parents=True)
    for path in saved:
        shutil.copy2(path, target / path.name)
    commit_all(f'Add submission from issue {number}')
    if remote_branch(head):
        git('push', '--force-with-lease', 'origin', f'HEAD:refs/heads/{head}')
    else:
        git('push', 'origin', f'HEAD:refs/heads/{head}')
    return ensure_pr(repo, number, head, slug, token)


def open_pr() -> None:
    # environment() checks GITHUB_REPOSITORY and GITHUB_TOKEN and reads
    # the issue number from DISPATCH_ISSUE_NUMBER or ISSUE_NUMBER.
    repo, number, token = environment()
    issue = fetch_issue(repo, number, token)
    title = issue.get('title') or ''
    # The only title gate: the word "submission". The rest of the title
    # is the tool name. The folder is submissions/<tool>/, with no id yet.
    if not is_submission_title(title):
        post_comment(
            repo, number, token,
            'No pull request was opened. The issue title must contain the '
            'word `submission`, for example `submission: KomaMRI`.',
        )
        raise SystemExit('issue title has no "submission"')
    try:
        slug = tool_folder(title)
    except ValueError as exc:
        post_comment(
            repo, number, token,
            f'No pull request was opened. {exc}. '
            'Example title: `submission: KomaMRI`.',
        )
        raise SystemExit(str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix='submission-') as tmp:
        dest = Path(tmp)
        try:
            saved = download_cases(repo, number, token, dest, issue)
        except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
            post_comment(repo, number, token, 'Could not download or unpack the attachments, so no pull request was opened.')
            raise SystemExit(str(exc)) from exc
        if not saved:
            post_comment(repo, number, token, 'No `.zip`, `.tgz`, or `.gz` attachment on this issue, so no pull request was opened.')
            raise SystemExit(1)
        ok, report = review(saved)
        if not ok:
            post_comment(
                repo, number, token,
                f'Format check failed, so no pull request was opened.\n\n{report}',
            )
            print(report, flush=True)
            raise SystemExit(1)
        try:
            url = publish_validated(repo, number, token, saved, slug)
        except SystemExit as exc:
            post_comment(
                repo, number, token,
                'Format check passed, but the pull request was not opened. '
                'The Actions log has the git error.',
            )
            raise SystemExit(str(exc)) from exc
    post_comment(
        repo, number, token,
        f'Format check passed. Pull request: {url}\n\n'
        'Merge it into `main`. Evaluation assigns the id on the `eval` branch. '
        f'Merge `eval` back into `main` by hand.\n\n{report}',
    )
    print(url, flush=True)


if __name__ == '__main__':
    open_pr()
