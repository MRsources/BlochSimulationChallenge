"""Rebuild the evaluation from the submission folders.

Two steps, each also runnable on its own:

- ``write_submission_readmes.py`` renders ``README.md`` from ``submission.json``.
  The id is already part of the folder name.
- ``plot_submission_images.py`` writes one figure per case and refreshes the figure links in the repository README.

Install::

    python -m pip install numpy h5py matplotlib pypulseq==1.5.0.post1 'mri-nufft[finufft]==1.5.1'

Run::

    python evaluation/eval_scripts/update_submission_evaluation.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plot_submission_images import plot_submission_images  # noqa: E402
from submission_cases import OUT, SEQUENCES, SUBMISSIONS, list_submissions  # noqa: E402
from write_submission_readmes import write_submission_readmes  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--submissions', type=Path, default=SUBMISSIONS,
                        help='folder of entry directories (default: submissions/)')
    parser.add_argument('--out', type=Path, default=OUT,
                        help='where to write the case folders (default: evaluation/)')
    args = parser.parse_args()
    folders = list_submissions(args.submissions)
    print(f'{len(folders)} submission(s)')
    write_submission_readmes(folders)
    plot_submission_images(folders, args.out, SEQUENCES)


if __name__ == '__main__':
    main()
