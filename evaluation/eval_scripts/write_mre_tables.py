"""Write the pairwise mean-relative-error table for each case.

Imaging cases use the magnitude of the reconstructed image. The FID uses
the magnitude of the ADC. Each magnitude is divided by its own mean before
the difference, which is the definition of this table and is separate from
the image plots.

Run::

    python evaluation/eval_scripts/write_mre_tables.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from submission_cases import (
    CASES,
    OUT,
    SEQUENCES,
    SUBMISSIONS,
    case_dir,
    collect_case,
    header,
    list_submissions,
)


def normalise(signal: np.ndarray) -> np.ndarray:
    """Divide by the mean magnitude so a global scale drops out of the table."""
    scale = float(np.mean(np.abs(signal)))
    if scale == 0.0 or not np.isfinite(scale):
        return signal
    return signal / scale


def mean_relative_error(left: np.ndarray, right: np.ndarray) -> float:
    """Mean absolute difference after each magnitude is divided by its mean."""
    return float(np.mean(np.abs(normalise(left) - normalise(right))))


def write_table(
    out: Path,
    stem: str,
    title: str,
    names: list[str],
    magnitudes: list[np.ndarray],
    *,
    image: bool,
) -> None:
    path = case_dir(out, stem) / f'{stem}_mre.md'
    # The formula lives in evaluation/README.md. A case file is only its table.
    if image:
        summary = 'Pairwise mean relative error of the magnitude images.'
    else:
        summary = 'Pairwise mean relative error of the FID magnitude. This case has no image.'
    lines = [f'# {title}', '', summary, '']
    if not names:
        lines.append('No submission contains this case yet.')
        lines.append('')
        path.write_text('\n'.join(lines))
        print(f'wrote {path}')
        return
    header_row = '| | ' + ' | '.join(names) + ' |'
    rule = '|---|' + '|'.join('---:' for _ in names) + '|'
    lines.extend([header_row, rule])
    for i, name in enumerate(names):
        cells = []
        for j in range(len(names)):
            value = 0.0 if i == j else mean_relative_error(magnitudes[i], magnitudes[j])
            cells.append(f'{value:.4f}')
        lines.append('| ' + name + ' | ' + ' | '.join(cells) + ' |')
    lines.append('')
    path.write_text('\n'.join(lines))
    print(f'wrote {path}')


def write_mre_tables(folders: list[Path], out: Path, sequences: Path) -> None:
    """One ``<stem>_mre.md`` per case."""
    out.mkdir(parents=True, exist_ok=True)
    for index, stem, seq_name, imaging in CASES:
        seq_path = sequences / seq_name
        names, signals, images = collect_case(folders, index, imaging, seq_path)
        if imaging:
            magnitudes = [np.abs(image) for image in images]
        else:
            magnitudes = [np.abs(signal) for signal in signals]
        write_table(out, stem, header(stem), names, magnitudes, image=imaging)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--submissions', type=Path, default=SUBMISSIONS,
                        help='folder of entry directories (default: submissions/)')
    parser.add_argument('--out', type=Path, default=OUT,
                        help='where to write the case folders (default: evaluation/)')
    args = parser.parse_args()
    folders = list_submissions(args.submissions)
    print(f'{len(folders)} submission(s)')
    write_mre_tables(folders, args.out, SEQUENCES)


if __name__ == '__main__':
    main()
