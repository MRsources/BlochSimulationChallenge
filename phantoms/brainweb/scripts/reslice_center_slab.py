"""Copy the four centre slices of a phantom and centre that slab on z = 0.

This is a crop, not the density-weighted resample in bifti's ``resample.py``.
Each output voxel is one source voxel. The in-plane grid is kept. The z
origin is then set so the four voxel centres are symmetric about the world
origin: for a 1 mm step they lie at -1.5, -0.5, +0.5, +1.5 mm, and the slab
runs from -2 mm to +2 mm.

On a 1 mm grid the samples sit on integer millimetres, so the four slices
nearest z = 0 are a tie. The lower window is kept (centres -2, -1, 0, +1 mm
on the BrainWeb head) and the header absorbs the half-millimetre shift.

The slab in ``phantoms/brainweb`` was written by this script from a full-head folder.

Run::

    python phantoms/brainweb/scripts/reslice_center_slab.py /path/to/full-head -o phantoms/brainweb
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import nibabel as nib
import numpy as np

N_SLICES = 4


def _z_centers(affine: np.ndarray, n: int, axis: int) -> np.ndarray:
    index = np.zeros((n, 4))
    index[:, axis] = np.arange(n)
    index[:, 3] = 1.0
    return (affine @ index.T)[2]


def _slice_axis(affine: np.ndarray) -> int:
    """Voxel axis that maps onto world z. These phantoms are axis-aligned."""
    row = np.abs(np.asarray(affine[2, :3], dtype=np.float64))
    axis = int(np.argmax(row))
    off_axis = float(row.sum() - row[axis])
    if row[axis] <= 1e6 * off_axis:
        raise SystemExit('affine is oblique; this script only crops an axis-aligned grid')
    return axis


def center_window(affine: np.ndarray, n_src: int, axis: int, n_out: int = N_SLICES) -> int:
    """Start index of the contiguous window whose centres sit nearest z = 0.

    A tie keeps the lower index.
    """
    if n_src < n_out:
        raise SystemExit(f'volume has {n_src} slices along z, need at least {n_out}')
    z = _z_centers(affine, n_src, axis)
    best_k = 0
    best_score = None
    for k in range(n_src - n_out + 1):
        score = abs(float(np.mean(z[k : k + n_out])))
        if best_score is None or score < best_score - 1e-9:
            best_score = score
            best_k = k
    return best_k


def centered_affine(cropped_affine: np.ndarray, n_out: int, axis: int) -> np.ndarray:
    """Shift the translation so the mean world-z of the voxel centres is 0."""
    affine = np.array(cropped_affine, dtype=np.float64)
    mean_z = float(np.mean(_z_centers(affine, n_out, axis)))
    affine[2, 3] -= mean_z
    return affine


def crop_volume(src: Path, dest: Path) -> None:
    img = nib.load(str(src))
    affine = np.asarray(img.affine, dtype=np.float64)
    axis = _slice_axis(affine)
    if axis != 2:
        raise SystemExit(f'{src.name}: slice axis is {axis}, expected 2')
    k0 = center_window(affine, img.shape[2], axis)
    slicer = [slice(None), slice(None), slice(None)]
    slicer[axis] = slice(k0, k0 + N_SLICES)
    if img.ndim == 4:
        slicer.append(slice(None))
    cropped = img.slicer[tuple(slicer)]
    out_affine = centered_affine(cropped.affine, N_SLICES, axis)
    header = cropped.header.copy()
    header.set_sform(out_affine, code=int(img.header['sform_code']) or 2)
    header.set_qform(out_affine, code=int(img.header['qform_code']) or 2)
    out = nib.Nifti1Image(np.asanyarray(cropped.dataobj), out_affine, header)
    dest.parent.mkdir(parents=True, exist_ok=True)
    nib.save(out, str(dest))

    src_z = _z_centers(affine, img.shape[2], axis)
    out_z = _z_centers(out_affine, N_SLICES, axis)
    data_src = np.asanyarray(img.dataobj)
    data_out = np.asanyarray(out.dataobj)
    src_window = data_src[:, :, k0 : k0 + N_SLICES]
    copied = np.array_equal(data_out, src_window)
    print(f'{src.name} -> {dest}')
    print(f'  shape {img.shape} -> {out.shape}')
    print(f'  source slices {k0}..{k0 + N_SLICES - 1} at z {[round(float(z), 4) for z in src_z[k0:k0 + N_SLICES]]} mm')
    print(f'  written centres {[round(float(z), 4) for z in out_z]} mm  copied unchanged: {copied}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('phantom_dir', type=Path, help='folder containing the source NIfTIs and JSON')
    parser.add_argument(
        '-o',
        '--output',
        type=Path,
        help='destination folder (default: <phantom_dir>_center4 next to the source)',
    )
    args = parser.parse_args()
    source = args.phantom_dir.resolve()
    output = args.output.resolve() if args.output else source.parent / f'{source.name}_center4'
    volumes = sorted(source.glob('*.nii.gz'))
    if not volumes:
        raise SystemExit(f'no NIfTI files in {source}')
    output.mkdir(parents=True, exist_ok=True)
    for src in volumes:
        crop_volume(src, output / src.name)
    for spec in sorted(source.glob('*.json')):
        data = json.loads(spec.read_text())
        if 'reslice_to' in data:
            print(f'{spec.name} left in place (it still describes a reslice of the full head)')
            continue
        dest = output / spec.name
        dest.write_text(json.dumps(data, indent=2) + '\n')
        print(f'{spec.name} -> {dest}')


if __name__ == '__main__':
    main()
