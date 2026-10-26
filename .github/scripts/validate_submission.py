"""Check a challenge submission directory or a list of case files.

Accepted signal layouts, one of:

- ``signal``: a complex floating dataset, shape ``(n,)``
- ``signal_real`` and ``signal_imag``: real floating datasets, same shape ``(n,)``

``n`` is 1024 for ``case0`` and 4096 for ``case1`` … ``case4``.
Every value must be finite. ``submission.json`` is the sheet. ``README.md`` in
a submission folder is generated later and is not part of the entry. Any other
file is an optional run script: the name and the file type are not fixed, and
the file is not run.

    python .github/scripts/validate_submission.py submissions/issue-1
    python .github/scripts/validate_submission.py case0.h5 case1.h5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import h5py
import numpy as np

EXPECTED_SAMPLES = {0: 1024, 1: 4096, 2: 4096, 3: 4096, 4: 4096}
CASE_NAME = re.compile(r'case([0-4])\.(h5|hdf5)$', re.IGNORECASE)


def kept_name(name: str) -> bool:
    """A file the issue unpacker may keep.

    Case files, ``submission.json``, and any other run script. The script name
    and suffix are free. Hidden names are left out.
    """
    base = Path(name).name
    if not base or base in {'.', '..'} or base.startswith('.'):
        return False
    if '\x00' in base or '/' in base or '\\' in base:
        return False
    return True


class Reject(Exception):
    """One file failed the format check."""


def _dataset(handle: h5py.File, name: str) -> h5py.Dataset:
    link = handle.get(name, getlink=True)
    if link is None:
        raise Reject(f'missing dataset {name}')
    if isinstance(link, h5py.ExternalLink):
        raise Reject(f'{name} is an external link')
    dataset = handle[name]
    if not isinstance(dataset, h5py.Dataset):
        raise Reject(f'{name} is not a dataset')
    if dataset.is_virtual:
        raise Reject(f'{name} is a virtual dataset')
    return dataset


def _as_1d(array: np.ndarray, label: str) -> np.ndarray:
    array = np.asarray(array)
    if array.ndim != 1:
        raise Reject(f'{label} shape {array.shape} is not 1-D')
    return array


def load_signal(path: Path) -> tuple[np.ndarray, str]:
    """Return ``(samples, dtype description)`` or raise ``Reject``."""
    try:
        handle = h5py.File(path, 'r')
    except OSError as exc:
        raise Reject(f'not an HDF5 file ({exc})') from exc
    with handle:
        names = set(handle.keys())
        if 'signal_real' in names or 'signal_imag' in names:
            if 'signal_real' not in names or 'signal_imag' not in names:
                raise Reject('signal_real and signal_imag must both be present')
            real = _as_1d(_dataset(handle, 'signal_real')[()], 'signal_real')
            imag = _as_1d(_dataset(handle, 'signal_imag')[()], 'signal_imag')
            if not np.issubdtype(real.dtype, np.floating):
                raise Reject(f'signal_real dtype {real.dtype} is not floating')
            if not np.issubdtype(imag.dtype, np.floating):
                raise Reject(f'signal_imag dtype {imag.dtype} is not floating')
            if real.dtype != imag.dtype:
                raise Reject(f'signal_real is {real.dtype}, signal_imag is {imag.dtype}')
            if real.shape != imag.shape:
                raise Reject(
                    f'signal_real length {real.shape[0]}, signal_imag length {imag.shape[0]}'
                )
            signal = real + 1j * imag
            kind = f'{real.dtype} real/imag'
        elif 'signal' in names:
            signal = _as_1d(_dataset(handle, 'signal')[()], 'signal')
            if not np.issubdtype(signal.dtype, np.complexfloating):
                raise Reject(
                    f'signal dtype {signal.dtype} is not complex; '
                    'use a complex dataset or signal_real and signal_imag'
                )
            kind = str(signal.dtype)
        else:
            raise Reject(
                'need a complex dataset "signal", or float datasets '
                '"signal_real" and "signal_imag"'
            )
    bad = int(np.size(signal) - np.count_nonzero(np.isfinite(signal)))
    if bad:
        raise Reject(f'{bad} non-finite sample(s)')
    return signal, kind


def check_case(path: Path) -> str:
    """Return a one-line success description or raise ``Reject``."""
    match = CASE_NAME.fullmatch(path.name)
    if match is None:
        raise Reject('name must be case0.h5 … case4.h5')
    case = int(match.group(1))
    expected = EXPECTED_SAMPLES[case]
    signal, kind = load_signal(path)
    if signal.shape[0] != expected:
        raise Reject(f'{signal.shape[0]} samples, expected {expected}')
    return f'{kind}, {signal.shape[0]} samples, finite'


SHEET_KEYS = {
    'group', 'tool_name', 'tool_version', 'tool_commit', 'tool_date',
    'solver', 'project_page', 'paper', 'hardware', 'cases', 'setup_notes',
}
CASE_KEYS = {'case', 'runtime_s', 'mrzero_runtime_s'}
PAPER_KEYS = {'title', 'authors', 'year', 'link'}


def _string(value, label: str) -> str:
    if value is None:
        return ''
    if not isinstance(value, str):
        raise Reject(f'{label} must be a string')
    return value.strip()


def _positive(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Reject(f'{label} must be a number')
    number = float(value)
    if not np.isfinite(number) or number <= 0:
        raise Reject(f'{label} must be a positive finite number')
    return number


def _paper(value) -> None:
    """A paper may be left out, be a link, or be an object with any fields filled."""
    if value is None or value == '':
        return
    if isinstance(value, str):
        return
    if not isinstance(value, dict):
        raise Reject('paper must be a string or an object')
    extra = set(value) - PAPER_KEYS
    if extra:
        raise Reject('paper has unknown fields: ' + ', '.join(sorted(extra)))
    for key in ('title', 'authors', 'link'):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            raise Reject(f'paper.{key} must be a string')
    year = value.get('year')
    if year is not None and (isinstance(year, bool) or not isinstance(year, int)):
        raise Reject('paper.year must be an integer or null')


def check_submission_json(path: Path) -> str:
    """Check ``submission.json``. Runtimes may be left null."""
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise Reject(f'not UTF-8 text ({exc})') from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Reject(f'not JSON ({exc})') from exc
    if not isinstance(data, dict):
        raise Reject('the sheet must be a JSON object')
    extra = set(data) - SHEET_KEYS
    if extra:
        raise Reject('unknown fields: ' + ', '.join(sorted(extra)))
    group = _string(data.get('group'), 'group')
    tool = _string(data.get('tool_name'), 'tool_name')
    if not group:
        raise Reject('group is empty')
    if not tool:
        raise Reject('tool_name is empty')
    for key in (
        'solver', 'project_page', 'hardware', 'setup_notes',
        'tool_version', 'tool_commit', 'tool_date',
    ):
        _string(data.get(key), key)
    version = _string(data.get('tool_version'), 'tool_version')
    commit = _string(data.get('tool_commit'), 'tool_commit')
    tool_date = _string(data.get('tool_date'), 'tool_date')
    if tool_date:
        try:
            date.fromisoformat(tool_date)
        except ValueError:
            raise Reject('tool_date must be YYYY-MM-DD') from None
    if not (version or commit or tool_date):
        raise Reject('give a tool_version, a tool_commit, or a tool_date')
    _paper(data.get('paper'))
    cases = data.get('cases')
    if not isinstance(cases, list):
        raise Reject('cases must be a list')
    seen_cases: set[int] = set()
    for item in cases:
        if not isinstance(item, dict):
            raise Reject('each case must be an object')
        extra_case = set(item) - CASE_KEYS
        if extra_case:
            raise Reject('case has unknown fields: ' + ', '.join(sorted(extra_case)))
        index = item.get('case')
        if isinstance(index, bool) or not isinstance(index, int) or index not in EXPECTED_SAMPLES:
            raise Reject('case must be an integer from 0 to 4')
        if index in seen_cases:
            raise Reject(f'case {index} is repeated')
        seen_cases.add(index)
        for key in ('runtime_s', 'mrzero_runtime_s'):
            value = item.get(key)
            if value is None:
                continue
            _positive(value, f'case {index} {key}')
    missing_rows = [str(n) for n in EXPECTED_SAMPLES if n not in seen_cases]
    if missing_rows:
        raise Reject('cases missing ' + ', '.join(missing_rows))
    return f'{tool}, {version or commit or tool_date}'


def check_run_script(path: Path) -> str:
    """Accept an optional run script of any name and type. It is not executed."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise Reject(f'unreadable ({exc})') from exc
    if size == 0:
        raise Reject('empty')
    return 'present'


def files_from(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(sorted(child for child in path.iterdir() if child.is_file()))
        elif path.is_file():
            found.append(path)
        else:
            raise Reject(f'not found: {path}')
    return found


def review(paths: list[Path]) -> tuple[bool, str]:
    """Validate case files. Missing cases are reported and do not fail."""
    lines: list[str] = []
    ok = True
    seen: dict[int, Path] = {}
    sheet: Path | None = None
    scripts: list[Path] = []
    for path in files_from(paths):
        name = path.name
        if not kept_name(name):
            continue
        if name.lower() in {'readme.md', 'submission.md'}:
            continue
        if name.lower() == 'submission.json':
            if sheet is not None:
                ok = False
                lines.append(f'- `{name}`: failed, duplicate of `{sheet.name}`')
                continue
            sheet = path
            continue
        if path.suffix.lower() not in {'.h5', '.hdf5'}:
            scripts.append(path)
            continue
        match = CASE_NAME.fullmatch(name)
        if match is None:
            ok = False
            lines.append(f'- `{name}`: failed, name must be case0.h5 … case4.h5')
            continue
        case = int(match.group(1))
        if case in seen:
            ok = False
            lines.append(f'- `{name}`: failed, duplicate of `{seen[case].name}`')
            continue
        seen[case] = path
        try:
            detail = check_case(path)
        except Reject as exc:
            ok = False
            lines.append(f'- `{name}`: failed, {exc}')
        else:
            lines.append(f'- `{name}`: ok, {detail}')

    if not seen and ok:
        ok = False
        lines.append('- no case0.h5 … case4.h5 files')

    missing = [f'case{n}.h5' for n in EXPECTED_SAMPLES if n not in seen]
    if missing:
        lines.append('Missing (not a failure): ' + ', '.join(f'`{name}`' for name in missing))

    if sheet is None:
        ok = False
        lines.append('- `submission.json`: failed, not attached')
    else:
        try:
            detail = check_submission_json(sheet)
        except Reject as exc:
            ok = False
            lines.append(f'- `submission.json`: failed, {exc}')
        else:
            lines.append(f'- `submission.json`: ok, {detail}')

    for script in scripts:
        try:
            detail = check_run_script(script)
        except Reject as exc:
            ok = False
            lines.append(f'- `{script.name}`: failed, {exc}')
        else:
            lines.append(f'- `{script.name}`: optional, {detail}')
    return ok, '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        'path', nargs='+', type=Path,
        help='case HDF5 files, submission.json, or a directory containing them',
    )
    args = parser.parse_args()
    try:
        ok, report = review(args.path)
    except Reject as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
    print(report)
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
