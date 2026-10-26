"""Plot each imaging case as one figure.

Rows are submissions. Columns are k-space, magnitude, and phase, in that
order. K-space is log10 of the acquired magnitude. Magnitude is the
absolute value of the reconstruction. Phase is the angle in radians.

The FID has no readout gradient. It stays a magnitude-versus-time plot of
the raw ADC.

Run::

    python evaluation/eval_scripts/plot_submission_images.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pypulseq as pp

# Latin Modern is the OpenType Computer Modern used as LaTeX's text face.
# matplotlib's cmr10 has no underscore or bar, so submission names would break.
_FONTS = Path(__file__).resolve().parent / 'fonts'
_LM = _FONTS / 'lmroman10-regular.otf'
_LMB = _FONTS / 'lmroman10-bold.otf'
font_manager.fontManager.addfont(str(_LM))
font_manager.fontManager.addfont(str(_LMB))
plt.rcParams.update({
    'font.family': 'Latin Modern Roman',
    'mathtext.fontset': 'cm',
})

sys.path.insert(0, str(Path(__file__).resolve().parent))

from submission_cases import (  # noqa: E402
    CASES,
    OUT,
    SEQUENCES,
    SUBMISSIONS,
    case_dir,
    collect_case,
    header,
    list_submissions,
)

CMAP = 'gray'
KSPACE_CMAP = 'magma'
_SPLIT_PLOTS = ('_kspace.png', '_image.png', '_phase.png')


def bold_font(size: float) -> font_manager.FontProperties:
    return font_manager.FontProperties(fname=str(_LMB), size=size)


def adc_time_s(seq_path: Path, n: int) -> np.ndarray:
    seq = pp.Sequence()
    seq.read(str(seq_path))
    times = np.asarray(seq.adc_times()[0], dtype=float).reshape(-1)
    if times.size != n:
        raise SystemExit(f'{seq_path.name}: {times.size} ADC times, signal length {n}')
    return times


def _square(signal: np.ndarray, stem: str) -> np.ndarray:
    """Reshape a Cartesian ADC into a square, one readout line per row."""
    side = int(np.sqrt(signal.size))
    if side * side != signal.size:
        raise SystemExit(f'{stem}: {signal.size} samples is not a square k-space')
    return np.abs(signal).reshape(side, side)


def reorder_tse(signal: np.ndarray) -> np.ndarray:
    """Place 4 shots of 16 echoes on the 64 ky lines.

    Rows cycle through the shots in order. Shot 0 starts at ky = -30, two
    lines above ky = -32, and each later echo is four rows on, wrapping
    around the grid.
    """
    lines = signal.reshape(4, 16, -1)
    grid = np.empty((64, lines.shape[-1]), dtype=signal.dtype)
    for shot in range(4):
        row = 2 + shot
        for echo in range(16):
            grid[row] = lines[shot, echo]
            row = (row + 4) % 64
    return grid.reshape(-1)


def reorder_epi(signal: np.ndarray) -> np.ndarray:
    """Flip every odd EPI line. Those readouts run backwards in kx."""
    lines = np.array(signal, copy=True).reshape(-1, int(np.sqrt(signal.size)))
    lines[1::2] = lines[1::2, ::-1]
    return lines.reshape(-1)


def _kspace_adc(signal: np.ndarray, stem: str) -> np.ndarray:
    """ADC in ky-line order. GRE is already stored that way."""
    if stem == 'case2_tse':
        return reorder_tse(signal)
    if stem in {'case3_epi', 'case4_epi_t2star'}:
        return reorder_epi(signal)
    return signal


def _log10_magnitude(magnitude: np.ndarray) -> np.ndarray:
    """log10(|k|). Zeros stay NaN so they are not drawn as minus infinity."""
    shown = np.full(magnitude.shape, np.nan)
    positive = magnitude > 0
    shown[positive] = np.log10(magnitude[positive])
    return shown


def _panel_limits(panel: np.ndarray, fallback: tuple[float, float], *, floor: float | None) -> tuple[float, float]:
    """Color limits of one panel. ``floor`` pins the bottom, as magnitude does at 0."""
    finite = panel[np.isfinite(panel)]
    if finite.size == 0:
        return fallback
    lo = float(np.min(finite)) if floor is None else floor
    hi = float(np.max(finite))
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def _drop_split_plots(folder: Path, stem: str) -> None:
    """The three old panels are now columns of ``<stem>.png``."""
    for suffix in _SPLIT_PLOTS:
        path = folder / f'{stem}{suffix}'
        if path.is_file():
            path.unlink()
            print(f'removed {path}')


def _plot_signal_trace(
    stem: str, names: list[str], signals: list[np.ndarray], seq_path: Path, out: Path,
) -> None:
    """Magnitude versus ADC time, for a trajectory that never leaves the centre."""
    fig, ax = plt.subplots(figsize=(8, 4.2))
    for name, signal in zip(names, signals):
        times_ms = adc_time_s(seq_path, signal.size) * 1e3
        ax.plot(times_ms, np.abs(signal), label=name, linewidth=1.0)
    ax.set_xlabel('time (ms)')
    ax.set_ylabel('|signal|')
    ax.set_title(header(stem), fontproperties=bold_font(14))
    ax.legend(fontsize=8, loc='best')
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f'wrote {out}')


def plot_case_grid(
    stem: str, names: list[str], signals: list[np.ndarray], images: list[np.ndarray], out: Path,
) -> None:
    """One row per submission: k-space, magnitude, phase."""
    if not names:
        return
    kspaces = [
        _log10_magnitude(_square(_kspace_adc(signal, stem), stem))
        for signal in signals
    ]
    magnitudes = [np.abs(image) for image in images]
    phases = [np.angle(image) for image in images]
    columns = (
        (kspaces, KSPACE_CMAP, 'lower', 'k-space', 'log10(|k|)', None, (-1.0, 0.0)),
        (magnitudes, CMAP, 'upper', 'magnitude', '|image|', 0.0, (0.0, 1.0)),
        (phases, 'twilight', 'upper', 'phase', 'phase (rad)', -np.pi, (-np.pi, np.pi)),
    )
    # Phase is an angle, so every phase bar still runs from −π to π.
    # K-space and magnitude take the range of that panel.
    n = len(names)
    side = 3.6
    fig, axes = plt.subplots(
        n, 3, figsize=(side * 3 + 3.1, n * (side + 0.35) + 0.55), squeeze=False,
    )
    fig.suptitle(header(stem), fontproperties=bold_font(20), y=0.995)
    # Small inset on the left. The right margin leaves room for the last color bar.
    fig.subplots_adjust(left=0.04, right=0.88, top=0.92, bottom=0.02, wspace=0.55, hspace=0.14)
    shown = [[None, None, None] for _ in names]
    for row, name in enumerate(names):
        for col, (panels, cmap, origin, title, label, floor, fallback) in enumerate(columns):
            panel = panels[row]
            if floor == -np.pi:
                vmin, vmax = -np.pi, np.pi
            else:
                vmin, vmax = _panel_limits(panel, fallback, floor=floor)
            ax = axes[row, col]
            shown[row][col] = ax.imshow(panel, origin=origin, cmap=cmap, vmin=vmin, vmax=vmax)
            ax.set_box_aspect(1)
            ax.set_anchor('S')
            ax.set_title(title, fontsize=11)
            ax.set_xticks([])
            ax.set_yticks([])
    # Color bars use the square image box, so the bar is exactly as tall as the image.
    fig.canvas.draw()
    for row, name in enumerate(names):
        positions = [axes[row, col].get_position() for col in range(3)]
        top = max(pos.y1 for pos in positions)
        fig.text(
            positions[0].x0, top + 0.03, name,
            ha='left', va='bottom', fontproperties=bold_font(20),
        )
        for col, (*_rest, label, _floor, _fallback) in enumerate(columns):
            pos = positions[col]
            cax = fig.add_axes([pos.x1 + 0.008, pos.y0, 0.011, pos.height])
            fig.colorbar(shown[row][col], cax=cax, label=label)
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f'wrote {out}')


def plot_submission_images(folders: list[Path], out: Path, sequences: Path) -> None:
    """Write ``<stem>.png`` for every case and drop the old split panels."""
    out.mkdir(parents=True, exist_ok=True)
    for index, stem, seq_name, imaging in CASES:
        seq_path = sequences / seq_name
        folder = case_dir(out, stem)
        names, signals, images = collect_case(folders, index, imaging, seq_path)
        if imaging:
            _drop_split_plots(folder, stem)
            plot_case_grid(stem, names, signals, images, folder / f'{stem}.png')
        elif names:
            _plot_signal_trace(stem, names, signals, seq_path, folder / f'{stem}.png')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--submissions', type=Path, default=SUBMISSIONS,
                        help='folder of entry directories (default: submissions/)')
    parser.add_argument('--out', type=Path, default=OUT,
                        help='where to write the case folders (default: evaluation/)')
    args = parser.parse_args()
    folders = list_submissions(args.submissions)
    print(f'{len(folders)} submission(s)')
    plot_submission_images(folders, args.out, SEQUENCES)


if __name__ == '__main__':
    main()
