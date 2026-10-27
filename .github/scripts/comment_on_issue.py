"""Download a submission archive attached to an issue, unpack it, and comment.

GitHub issue uploads reject ``.h5``. Participants attach one ``.zip`` or
``.tgz`` of the case files and ``submission.json``, or each file as ``.gz``.
An optional run script is kept too, under any file name and type.
This script
reads the issue body from the API (never from the shell), downloads only
``user-attachments`` links, unpacks them, and posts the validator report.

    ISSUE_NUMBER=12 GITHUB_REPOSITORY=owner/name GITHUB_TOKEN=... \\
        python .github/scripts/comment_on_issue.py

Exits 0 without commenting when the issue has no case attachment.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_submission import kept_name, review  # noqa: E402

REPO_NAME = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
ATTACHMENT = re.compile(
    r'https://github\.com/user-attachments/\S+',
)
MAX_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED = 25 * 1024 * 1024
MAX_MEMBERS = 32
MAX_REDIRECTS = 5
# GitHub issues reject .h5, so the upload is a zip, a tgz, or a gzip of an allowed file.


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class StepFailed(RuntimeError):
    """A step stopped. ``target`` is the URL or file name in hand."""

    def __init__(self, step: str, target: str, detail: str):
        self.step = step
        self.target = target
        self.detail = detail
        super().__init__(f'{step} failed: {detail}; target={target}')


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


def _host_allowed(url: str) -> bool:
    parts = urllib.parse.urlparse(url)
    host = (parts.hostname or '').lower()
    return parts.scheme == 'https' and (
        host == 'github.com' or host.endswith('.githubusercontent.com')
    )


def _read_capped(response, limit: int) -> bytes:
    length = response.headers.get('Content-Length')
    if length is not None and int(length) > limit:
        raise RuntimeError(f'attachment declares {length} bytes')
    chunks: list[bytes] = []
    total = 0
    while True:
        block = response.read(65536)
        if not block:
            break
        total += len(block)
        if total > limit:
            raise RuntimeError(f'attachment exceeds {limit} bytes')
        chunks.append(block)
    return b''.join(chunks)


def _http_detail(exc: urllib.error.HTTPError, url: str, current: str) -> str:
    """HTTP status plus a short response body. ``current`` is the URL that failed."""
    snippet = exc.read(180).decode('utf-8', errors='replace').strip().replace('\n', ' ')
    detail = f'HTTP {exc.code}'
    if current != url:
        detail += f'; first URL was {url}'
    if snippet:
        detail += f'; response {snippet}'
    return detail


def download(url: str, dest: Path, token: str) -> None:
    """Download one user-attachments URL.

    The job token is ignored here. A private-repo attachment answers it
    as logged out and returns 404. ``ATTACHMENT_TOKEN`` is a classic
    personal access token with the ``repo`` scope. The auth header stays
    on github.com and is not forwarded to the redirect host.
    """
    del token  # the issue API token cannot download these files
    attachment = os.environ.get('ATTACHMENT_TOKEN', '')
    if not attachment:
        raise StepFailed(
            'download', url,
            'ATTACHMENT_TOKEN is not set. Add a classic personal access '
            'token with repo scope as that Actions secret.',
        )
    if not url.startswith('https://github.com/user-attachments/'):
        raise StepFailed('download', url, 'refusing a URL outside user-attachments')
    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not _host_allowed(current):
            raise StepFailed('download', current, f'refusing a redirect off GitHub from {url}')
        headers = {'User-Agent': 'bloch-sim-challenge'}
        if urllib.parse.urlparse(current).hostname == 'github.com':
            headers['Authorization'] = f'Bearer {attachment}'
            headers['Accept'] = 'application/octet-stream'
        request = urllib.request.Request(current, headers=headers)
        try:
            with opener.open(request, timeout=30) as response:
                try:
                    payload = _read_capped(response, MAX_BYTES)
                except RuntimeError as exc:
                    raise StepFailed('download', current, str(exc)) from exc
                dest.write_bytes(payload)
                return
        except urllib.error.HTTPError as exc:
            location = exc.headers.get('Location') if exc.code in {301, 302, 303, 307, 308} else None
            if not location:
                raise StepFailed('download', current, _http_detail(exc, url, current)) from exc
            current = urllib.parse.urljoin(current, location)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise StepFailed('download', current, str(exc)) from exc
    raise StepFailed('download', current, f'too many redirects from {url}')


def _allowed_file(name: str) -> bool:
    return kept_name(Path(name).name)


def _is_tarball(name: str) -> bool:
    lower = name.lower()
    return lower.endswith('.tgz') or lower.endswith('.tar.gz')


def _keep_attachment(name: str) -> bool:
    lower = name.lower()
    return (
        lower.endswith('.zip')
        or _is_tarball(name)
        or lower.endswith('.gz')
        or _allowed_file(name)
    )


def _write_limited(src, dest: Path, limit: int) -> None:
    written = 0
    with dest.open('wb') as out:
        while True:
            block = src.read(65536)
            if not block:
                break
            written += len(block)
            if written > limit:
                dest.unlink(missing_ok=True)
                raise RuntimeError(f'{dest.name} is larger than {limit} bytes after unpacking')
            out.write(block)


def _place(dest: Path, name: str) -> Path:
    """Return a new file path. Refuse a second copy of the same name."""
    base = Path(name).name
    if not _allowed_file(base):
        raise RuntimeError(f'{base} is not a usable file name')
    out = dest / base
    if out.exists():
        raise RuntimeError(f'{base} appears more than once')
    return out


def _gunzip_to(path: Path, dest: Path) -> None:
    try:
        with gzip.open(path, 'rb') as src:
            _write_limited(src, dest, MAX_UNCOMPRESSED)
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f'{path.name} is not gzip data ({exc})') from exc


def _unzip(path: Path, dest: Path) -> list[Path]:
    """Unpack allowed members only. Member paths are reduced to the file name."""
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f'{path.name} is not a zip file') from exc
    saved: list[Path] = []
    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > MAX_MEMBERS:
            raise RuntimeError(f'{path.name} has too many entries')
        for info in members:
            base = Path(info.filename).name
            if not base or not _allowed_file(base):
                continue
            if info.flag_bits & 0x1:
                raise RuntimeError(f'{path.name} is encrypted')
            if info.file_size > MAX_UNCOMPRESSED:
                raise RuntimeError(f'{base} declares an uncompressed size above the limit')
            out = _place(dest, base)
            with archive.open(info) as src:
                _write_limited(src, out, MAX_UNCOMPRESSED)
            saved.append(out)
    if not saved:
        raise RuntimeError(f'{path.name} contains no caseN.h5 or submission.json')
    return saved


def _untar(path: Path, dest: Path) -> list[Path]:
    """Unpack allowed regular files from a gzip-compressed tar."""
    try:
        archive = tarfile.open(path, 'r:gz')
    except tarfile.TarError as exc:
        raise RuntimeError(f'{path.name} is not a gzip tar') from exc
    saved: list[Path] = []
    with archive:
        members = [member for member in archive.getmembers() if member.isreg()]
        if len(members) > MAX_MEMBERS:
            raise RuntimeError(f'{path.name} has too many entries')
        for member in members:
            base = Path(member.name).name
            if not base or not _allowed_file(base):
                continue
            if member.size > MAX_UNCOMPRESSED:
                raise RuntimeError(f'{base} declares an uncompressed size above the limit')
            src = archive.extractfile(member)
            if src is None:
                continue
            out = _place(dest, base)
            with src:
                _write_limited(src, out, MAX_UNCOMPRESSED)
            saved.append(out)
    if not saved:
        raise RuntimeError(f'{path.name} contains no caseN.h5 or submission.json')
    return saved


def unpack(path: Path, dest: Path) -> list[Path]:
    """Return the case files and sheet inside one downloaded attachment."""
    lower = path.name.lower()
    if _is_tarball(path.name):
        return _untar(path, dest)
    if lower.endswith('.gz'):
        inner = path.name[:-3]
        if inner.lower().endswith('.zip'):
            zip_path = dest / Path(inner).name
            _gunzip_to(path, zip_path)
            try:
                return _unzip(zip_path, dest)
            finally:
                zip_path.unlink(missing_ok=True)
        out = _place(dest, inner)
        _gunzip_to(path, out)
        return [out]
    if lower.endswith('.zip'):
        return _unzip(path, dest)
    if _allowed_file(path.name):
        return [path]
    raise RuntimeError(
        f'{path.name} must be a .zip, a .tgz, or a gzip of a submission file'
    )


def attachment_names(body: str) -> list[tuple[str, str]]:
    """Return ``(url, filename)`` for zip/gz uploads, de-duplicated."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in ATTACHMENT.findall(body or ''):
        url = raw.rstrip(').,>]\'"')
        name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
        if not _keep_attachment(name):
            continue
        if not re.fullmatch(r'[A-Za-z0-9._-]+', name):
            continue
        if url in seen:
            continue
        seen.add(url)
        found.append((url, name))
    return found


def fetch_issue(repo: str, number: int, token: str) -> dict:
    return github_json('GET', f'https://api.github.com/repos/{repo}/issues/{number}', token)


def post_comment(repo: str, number: int, token: str, body: str) -> None:
    github_json(
        'POST',
        f'https://api.github.com/repos/{repo}/issues/{number}/comments',
        token,
        {'body': body},
    )


def environment() -> tuple[str, int, str]:
    """Read the three values the workflow passes in, and nothing else.

    ``GITHUB_TOKEN`` is the job token. ``GITHUB_REPOSITORY`` is
    ``owner/name``. The issue number is ``ISSUE_NUMBER`` for an issue
    event, or ``DISPATCH_ISSUE_NUMBER`` when the PR workflow was started
    by hand. The issue title and body are not taken from the environment;
    the body is fetched from the API later, so it cannot be expanded by
    the shell.
    """
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    if not REPO_NAME.fullmatch(repo):
        raise SystemExit('GITHUB_REPOSITORY must be owner/name')
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        raise SystemExit('GITHUB_TOKEN is not set')
    raw = os.environ.get('DISPATCH_ISSUE_NUMBER') or os.environ.get('ISSUE_NUMBER') or ''
    try:
        number = int(raw)
    except ValueError:
        raise SystemExit('ISSUE_NUMBER must be an integer') from None
    if number < 1:
        raise SystemExit('ISSUE_NUMBER must be positive')
    return repo, number, token


def is_submission_title(title: str) -> bool:
    """True when the title contains the word ``submission``.

    That is the only title check. The recommended form is
    ``submission: <tool>``; anything after the keyword is the tool name.
    """
    return re.search(r'\bsubmission\b', title, re.IGNORECASE) is not None


def tool_folder(title: str) -> str:
    """Folder name from the issue title, after the word ``submission``.

    ``submission: KomaMRI`` becomes ``KomaMRI``. Other characters become
    hyphens. The result is a single path segment.
    """
    rest = re.sub(r'\bsubmission\b', ' ', title, count=1, flags=re.IGNORECASE)
    slug = re.sub(r'[^A-Za-z0-9._-]+', '-', rest).strip('.-')
    if not slug or slug in {'.', '..'}:
        raise ValueError('the title needs a tool name as well as the word "submission"')
    return slug[:80]


def _failure_note(reached: list[str], step: str, target: str, detail: str) -> str:
    """Issue comment: steps that finished, then the step and value that stopped."""
    def safe(text: str) -> str:
        return text.replace('`', "'")

    lines = ['Format check stopped before validation.', '', 'Reached:']
    if reached:
        lines.extend(f'- {safe(item)}' for item in reached)
    else:
        lines.append('- nothing completed')
    lines.extend([
        '',
        f'Failed at: `{safe(step)}`',
        f'Target: `{safe(target)}`',
        f'Error: {safe(detail)}',
    ])
    return '\n'.join(lines)


def _stop(repo: str, number: int, token: str, reached: list[str], step: str, target: str, detail: str) -> None:
    print(f'failed_step={step}', flush=True)
    print(f'failed_target={target}', flush=True)
    print(f'failed_detail={detail}', flush=True)
    try:
        post_comment(repo, number, token, _failure_note(reached, step, target, detail))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f'could not post the failure comment: {exc}', flush=True)


def download_cases(
    repo: str, number: int, token: str, dest: Path, issue: dict | None = None,
    reached: list[str] | None = None,
) -> list[Path]:
    def mark(text: str) -> None:
        print(text, flush=True)
        if reached is not None:
            reached.append(text)

    if issue is None:
        issue = fetch_issue(repo, number, token)
    links = attachment_names(issue.get('body') or '')
    mark(f'parsed {len(links)} attachment URL(s) from the issue body')
    saved: list[Path] = []
    for url, name in links:
        mark(f'next attachment `{name}` at `{url}`')
        path = dest / name
        download(url, path, token)
        mark(f'downloaded `{name}` ({path.stat().st_size} bytes)')
        try:
            unpacked = unpack(path, dest)
        except (RuntimeError, OSError) as exc:
            raise StepFailed('unpack', name, str(exc)) from exc
        names = ', '.join(f'`{item.name}`' for item in unpacked)
        mark(f'unpacked `{name}` into {names}')
        saved.extend(unpacked)
    return saved


def comment_on_review() -> None:
    reached: list[str] = []

    def mark(text: str) -> None:
        print(text, flush=True)
        reached.append(text)

    repo, number, token = environment()
    mark(f'read workflow environment for `{repo}` issue {number}')
    issue_url = f'https://api.github.com/repos/{repo}/issues/{number}'
    try:
        issue = fetch_issue(repo, number, token)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        _stop(repo, number, token, reached, 'fetch issue', issue_url, str(exc))
        raise SystemExit(1) from exc
    title = issue.get('title') or ''
    mark(f'fetched issue {number}, title `{title}`')
    if not is_submission_title(title):
        print('issue title has no "submission"; not commenting', flush=True)
        return
    mark('title contains the word submission')
    with tempfile.TemporaryDirectory(prefix='submission-') as tmp:
        dest = Path(tmp)
        try:
            saved = download_cases(repo, number, token, dest, issue, reached)
        except StepFailed as exc:
            _stop(repo, number, token, reached, exc.step, exc.target, exc.detail)
            raise SystemExit(1) from exc
        except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
            _stop(repo, number, token, reached, 'download or unpack', '(no target recorded)', str(exc))
            raise SystemExit(1) from exc
        if not saved:
            print('no case attachments; not commenting', flush=True)
            return
        mark(f'handed {len(saved)} file(s) to the format check')
        try:
            ok, report = review(saved)
        except Exception as exc:
            names = ', '.join(path.name for path in saved)
            _stop(repo, number, token, reached, 'format check', names, str(exc))
            raise SystemExit(1) from exc
        if not ok:
            post_comment(
                repo, number, token,
                'Format check failed.\n\n'
                f'{report}\n\n'
                'Fix the files and edit the issue; this check runs again on the new attachments.',
            )
            print(report, flush=True)
            raise SystemExit(1)
        try:
            slug = tool_folder(title)
        except ValueError as exc:
            post_comment(
                repo, number, token,
                f'Format check passed, but no pull request was opened. {exc}. '
                'Example title: `submission: KomaMRI`.',
            )
            raise SystemExit(str(exc)) from exc
        try:
            from open_submission_pr import publish_validated
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
        'Format check passed.\n\n'
        f'{report}\n\n'
        f'Pull request: {url}\n\n'
        'Merge it into `main`. Evaluation assigns the id on the `eval` branch. '
        'Merge `eval` back into `main` by hand.',
    )
    print(report, flush=True)
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    comment_on_review()
