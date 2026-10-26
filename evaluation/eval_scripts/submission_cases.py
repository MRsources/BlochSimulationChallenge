"""Case list and signal loading shared by the evaluation scripts."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SUBMISSIONS = REPO / 'submissions'
OUT = REPO / 'evaluation'
SEQUENCES = REPO / 'sequences'

# case index, plot stem, sequence file, whether it is an image
CASES = (
    (0, 'case0_fid', 'case0_fid.seq', False),
    (1, 'case1_gre', 'case1_gre.seq', True),
    (2, 'case2_tse', 'case2_tse.seq', True),
    (3, 'case3_epi', 'case3_epi.seq', True),
    (4, 'case4_epi_t2star', 'case3_epi.seq', True),
)
_WORDS = {
    'fid': 'FID',
    'gre': 'GRE',
    'tse': 'TSE',
    'epi': 'EPI',
    't2star': 'T2*',
}
CASE_LABELS = {
    0: 'FID',
    1: 'RF-spoiled GRE',
    2: 'TSE, 4 shots × 16 echoes',
    3: "EPI, T2' = inf",
    4: "EPI, published T2'",
}


def header(stem: str) -> str:
    """'case4_epi_t2star' -> 'Case 4 EPI T2*'."""
    case, _, rest = stem.partition('_')
    words = [_WORDS.get(part, part.capitalize()) for part in rest.split('_')]
    return f'Case {case.removeprefix("case")} ' + ' '.join(words)


def list_submissions(root: Path) -> list[Path]:
    """Tool folders that hold at least one case file, in name order."""
    found = []
    if not root.is_dir():
        return found
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        if folder.name.startswith('.'):
            continue
        if any(folder.glob('case[0-4].h5')):
            found.append(folder)
    return found


def case_signal(folder: Path, index: int) -> np.ndarray | None:
    path = folder / f'case{index}.h5'
    if not path.is_file():
        return None
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from reco_nufft import load_signal  # noqa: E402

    return np.asarray(load_signal(path), dtype=np.complex128).reshape(-1)


def collect_case(
    folders: list[Path], index: int, imaging: bool, seq_path: Path,
) -> tuple[list[str], list[np.ndarray], list[np.ndarray]]:
    """Signals for one case. Images are reconstructed only for imaging cases."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from reco_nufft import reconstruct  # noqa: E402

    names: list[str] = []
    signals: list[np.ndarray] = []
    images: list[np.ndarray] = []
    for folder in folders:
        signal = case_signal(folder, index)
        if signal is None:
            print(f'  {folder.name}: no case{index}.h5')
            continue
        names.append(folder.name)
        signals.append(signal)
        if imaging:
            image = reconstruct(seq_path, signal)
            print(f'  {folder.name} case{index}: {image.shape[0]} x {image.shape[1]}')
            images.append(image)
    return names, signals, images


def case_dir(out: Path, stem: str) -> Path:
    path = out / stem
    path.mkdir(parents=True, exist_ok=True)
    return path
