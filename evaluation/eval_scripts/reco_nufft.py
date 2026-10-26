"""Reconstruct a raw ADC with the MRI-NUFFT finufft adjoint.

The reconstruction uses ``mri-nufft[finufft]==1.5.1``. A different installed
version stops the script.

Pulseq ``calculate_kspace()`` is in cycles/m. MRI-NUFFT wants those
locations in [-0.5, 0.5); they are divided by the matrix size over FOV.
The sign is flipped so ``adj_op`` matches ``fft2`` on a Cartesian grid.

A ``.npy`` may be any real or complex floating dtype. An HDF5 file carries
float ``signal_real`` and ``signal_imag`` of any floating dtype. Both are
cast to complex128 for the NUFFT.

Run::

    python evaluation/eval_scripts/reco_nufft.py sequences/case1_gre.seq signal.h5 -o image.npy
"""

from __future__ import annotations

import argparse
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
import pypulseq as pp

MRI_NUFFT_VERSION = '1.5.1'


def _complex128(values: np.ndarray, what: str) -> np.ndarray:
    """Cast a real or complex floating vector to complex128."""
    values = np.asarray(values).reshape(-1)
    if not (
        np.issubdtype(values.dtype, np.floating)
        or np.issubdtype(values.dtype, np.complexfloating)
    ):
        raise SystemExit(f'{what} dtype {values.dtype} is not floating')
    return np.ascontiguousarray(values, dtype=np.complex128)


def load_signal(path: Path) -> np.ndarray:
    """Load a flat complex ADC and cast it to complex128."""
    suffix = path.suffix.lower()
    if suffix == '.npy':
        return _complex128(np.load(path), path.name)
    if suffix in {'.h5', '.hdf5'}:
        import h5py
        with h5py.File(path, 'r') as handle:
            if 'signal_real' not in handle or 'signal_imag' not in handle:
                raise SystemExit(
                    f'{path.name} needs datasets signal_real and signal_imag'
                )
            real = np.asarray(handle['signal_real'][()])
            imag = np.asarray(handle['signal_imag'][()])
        if real.shape != imag.shape:
            raise SystemExit(f'{path.name}: signal_real and signal_imag shapes differ')
        if not (
            np.issubdtype(real.dtype, np.floating)
            and np.issubdtype(imag.dtype, np.floating)
        ):
            raise SystemExit(
                f'{path.name} dtypes are {real.dtype} and {imag.dtype}; both must be floating'
            )
        return np.ascontiguousarray(real.reshape(-1) + 1j * imag.reshape(-1), dtype=np.complex128)
    raise SystemExit(
        f'{path.name}: {suffix or "no suffix"} is not accepted. '
        'Use a floating .npy or signal_real/signal_imag HDF5.'
    )


def _locations(seq: pp.Sequence) -> tuple[np.ndarray, tuple[int, int]]:
    k = seq.calculate_kspace()[0]
    fov = np.asarray(seq.definitions['FOV'][:2], dtype=np.float64)
    i0 = int(np.argmin(k[0] * k[0] + k[1] * k[1]))
    step = 1.0 / fov
    ix = np.rint((k[0] - k[0, i0]) / step[0])
    iy = np.rint((k[1] - k[1, i0]) / step[1])
    nx = int(ix.max() - ix.min()) + 1
    ny = int(iy.max() - iy.min()) + 1
    locations = np.stack(
        (
            -(k[1] - k[1, i0]) * fov[1] / ny,
            -(k[0] - k[0, i0]) * fov[0] / nx,
        ),
        axis=1,
    )
    return np.ascontiguousarray(locations, dtype=np.float64), (ny, nx)


def _require_mri_nufft() -> None:
    """Stop unless the reconstruction package is the pinned release."""
    try:
        installed = version('mri-nufft')
    except PackageNotFoundError as exc:
        raise SystemExit(
            f'mri-nufft {MRI_NUFFT_VERSION} is required. Install mri-nufft[finufft]=={MRI_NUFFT_VERSION}'
        ) from exc
    if installed != MRI_NUFFT_VERSION:
        raise SystemExit(
            f'mri-nufft {installed} is installed; reconstruction uses {MRI_NUFFT_VERSION}'
        )


def reconstruct(seq_path: Path, signal: np.ndarray) -> np.ndarray:
    """Return the 2D complex image (complex128)."""
    _require_mri_nufft()
    from mrinufft import get_operator

    signal = _complex128(signal, 'signal')
    seq = pp.Sequence()
    seq.read(str(seq_path))
    locations, shape = _locations(seq)
    if locations.shape[0] != signal.size:
        raise ValueError(
            f'signal has {signal.size} samples, .seq ADC trajectory has {locations.shape[0]}'
        )
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', module=r'mrinufft\._utils')
        operator = get_operator('finufft')(samples=locations, shape=shape, n_coils=1)
        image = np.asarray(operator.adj_op(signal))
    return np.asarray(image, dtype=np.complex128)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('seq', type=Path, help='Pulseq .seq that produced the signal')
    parser.add_argument('signal', type=Path, help='floating .npy or HDF5 ADC')
    parser.add_argument('-o', '--out', type=Path, required=True, help='complex image .npy')
    args = parser.parse_args()

    image = reconstruct(args.seq, load_signal(args.signal))
    np.save(args.out, image)
    print(f'{args.out}: {image.shape[0]} x {image.shape[1]}  {image.dtype}')


if __name__ == '__main__':
    main()
