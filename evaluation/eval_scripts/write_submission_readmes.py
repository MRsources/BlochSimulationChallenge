"""Write each submission README from its submission.json.

Folder ids are part of the folder name. This step only renders
the sheet into ``README.md`` beside that JSON file.

Run::

    python evaluation/eval_scripts/write_submission_readmes.py
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from submission_cases import CASE_LABELS, SUBMISSIONS, list_submissions


def _blank(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _given(value) -> bool:
    """A JSON value the sheet actually filled in. Null and blanks are left out."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _ratio(runtime, mrzero) -> str:
    """``runtime_s / mrzero_runtime_s``. Missing values stay blank."""
    if runtime is None or mrzero is None or runtime == '' or mrzero == '':
        return '—'
    try:
        left = float(runtime)
        right = float(mrzero)
    except (TypeError, ValueError):
        return '—'
    if not math.isfinite(left) or not math.isfinite(right) or right == 0.0:
        return '—'
    return f'{left / right:.6g}'


def _num(value) -> str:
    if value is None or value == '':
        return '—'
    return f'{float(value):.6g}'


def _paper_lines(paper) -> list[str]:
    if paper is None or paper == '':
        return []
    if isinstance(paper, str):
        text = paper.strip()
        return [text] if text else []
    if not isinstance(paper, dict):
        return [str(paper)]
    lines = []
    for label, key in (
        ('Title', 'title'),
        ('Authors', 'authors'),
        ('Year', 'year'),
        ('Link', 'link'),
    ):
        text = _blank(paper.get(key))
        if text:
            lines.append(f'- {label}: {text}')
    return lines


def _timed_cases(data: dict) -> list[dict]:
    """Case rows that carry a runtime. Untimed cases are left out of the page."""
    items = []
    for item in data.get('cases') or []:
        if not isinstance(item, dict) or isinstance(item.get('case'), bool):
            continue
        if not isinstance(item.get('case'), int):
            continue
        if _given(item.get('runtime_s')) or _given(item.get('mrzero_runtime_s')):
            items.append(item)
    return sorted(items, key=lambda item: item['case'])


def _runtime_lines(items: list[dict]) -> list[str]:
    """The runtime table, with a column only when some case filled that value."""
    if not items:
        return []
    show_runtime = any(_given(item.get('runtime_s')) for item in items)
    show_mrzero = any(_given(item.get('mrzero_runtime_s')) for item in items)
    show_ratio = any(
        _given(item.get('runtime_s')) and _given(item.get('mrzero_runtime_s'))
        for item in items
    )
    headers = ['Case', 'Sequence']
    if show_runtime:
        headers.append('Runtime (s)')
    if show_mrzero:
        headers.append('MR-zero (s)')
    if show_ratio:
        headers.append('Relative to MR-zero')
    lines = ['## Runtime', '']
    if show_ratio:
        lines.extend(['Relative to MR-zero is `runtime_s / mrzero_runtime_s`.', ''])
    lines.append('| ' + ' | '.join(headers) + ' |')
    aligns = ['---', '---', *(['---:'] * (len(headers) - 2))]
    lines.append('|' + '|'.join(aligns) + '|')
    for item in items:
        index = item['case']
        cells = [str(index), CASE_LABELS.get(index, str(index))]
        if show_runtime:
            cells.append(_num(item['runtime_s']) if _given(item.get('runtime_s')) else '')
        if show_mrzero:
            cells.append(_num(item['mrzero_runtime_s']) if _given(item.get('mrzero_runtime_s')) else '')
        if show_ratio:
            both = _given(item.get('runtime_s')) and _given(item.get('mrzero_runtime_s'))
            cells.append(_ratio(item.get('runtime_s'), item.get('mrzero_runtime_s')) if both else '')
        lines.append('| ' + ' | '.join(cells) + ' |')
    return lines


def render_submission_readme(folder_name: str, data: dict) -> str:
    """Markdown page for one submission folder, filled from ``submission.json``.

    A heading, a field, or the runtime table is written only when the sheet
    has something for it. Nulls and empty strings are left out.
    """
    tool = _blank(data.get('tool_name')) or folder_name
    lines = [f'# {tool}', '', f'`{folder_name}`']
    details = []
    for label, key in (
        ('Group', 'group'),
        ('Version', 'tool_version'),
        ('Commit', 'tool_commit'),
        ('Date', 'tool_date'),
        ('Solver', 'solver'),
        ('Project page', 'project_page'),
        ('Hardware', 'hardware'),
    ):
        text = _blank(data.get(key))
        if text:
            details.append(f'- {label}: {text}')
    if details:
        lines.extend(['', *details])
    paper = _paper_lines(data.get('paper'))
    if paper:
        lines.extend(['', '## Paper', '', *paper])
    runtime = _runtime_lines(_timed_cases(data))
    if runtime:
        lines.extend(['', *runtime])
    notes = _blank(data.get('setup_notes'))
    if notes:
        lines.extend(['', '## Setup notes', '', notes])
    lines.append('')
    return '\n'.join(lines)


def write_submission_readmes(folders: list[Path]) -> None:
    """Write ``README.md`` next to each ``submission.json``."""
    for folder in folders:
        path = folder / 'submission.json'
        if not path.is_file():
            print(f'  {folder.name}: no submission.json')
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f'{path}: {exc}') from exc
        if not isinstance(data, dict):
            raise SystemExit(f'{path}: the sheet must be a JSON object')
        out = folder / 'README.md'
        out.write_text(render_submission_readme(folder.name, data))
        print(f'wrote {out}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--submissions', type=Path, default=SUBMISSIONS,
                        help='folder of entry directories (default: submissions/)')
    args = parser.parse_args()
    folders = list_submissions(args.submissions)
    print(f'{len(folders)} submission(s)')
    write_submission_readmes(folders)


if __name__ == '__main__':
    main()
