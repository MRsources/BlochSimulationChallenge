"""Case 0: slice-selective FID.

This case carries no spatial encoding at all: one slice-selective 90 degree
excitation, its rephaser, a delay, then a gradient-free readout of the free
induction decay. The whole slab contributes to every sample.

What this case probes:
  * a globally conjugated signal,
  * a global amplitude scale (proton density normalisation, spins per voxel),
  * a global phase offset.

The phantom contains a fat pool shifted by -440 Hz plus a dB0 map, so water
and fat beat against each other and the magnitude oscillates. What is compared
between tools is the direction of phase evolution, the overall scale, and that
beat pattern.

Run::

    python sequences/sequence_generators/write_case0_fid.py
    python sequences/sequence_generators/write_case0_fid.py --plot
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pypulseq as pp

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import SLICE_THICKNESS, system, write_seq  # noqa: E402

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
N_SAMPLES = 1024
DWELL = 20e-6  # [s] -> 20.48 ms readout, long enough to see several periods
TE = 4e-3  # [s] from the RF centre to the start of the ADC


def main(plot: bool = False, write: bool = True, seq_filename: str = 'case0_fid.seq'):
    seq = pp.Sequence(system)

    # 90 degree slice-selective excitation, on resonance.
    rf, gz, gz_reph = pp.make_sinc_pulse(
        flip_angle=np.pi / 2,
        duration=3e-3,
        slice_thickness=SLICE_THICKNESS,
        apodization=0.5,
        time_bw_product=4,
        system=system,
        return_gz=True,
        delay=system.rf_dead_time,
        use='excitation',
    )

    # The ADC dead time is stated explicitly rather than being silently applied,
    # so that TE below counts to the first sample and not to the ADC block start.
    adc = pp.make_adc(num_samples=N_SAMPLES, dwell=DWELL, delay=system.adc_dead_time, system=system)

    # TE is measured from the centre of the RF pulse to the first ADC sample.
    # What has already elapsed is the pulse's own second half, the rephaser and
    # the ADC's dead time, so only the remainder becomes an explicit delay.
    elapsed = (
        pp.calc_duration(gz, rf) - pp.calc_rf_center(rf)[0] - rf.delay
        + pp.calc_duration(gz_reph)
        + adc.delay
    )
    delay_TE = round((TE - elapsed) / seq.grad_raster_time) * seq.grad_raster_time
    assert delay_TE >= 0, f'TE too short by {-delay_TE * 1e3:.3f} ms'

    seq.add_block(rf, gz)
    seq.add_block(gz_reph)
    if delay_TE > 0:
        seq.add_block(pp.make_delay(delay_TE))
    seq.add_block(adc)  # no gradient: a pure FID

    print(f'FID: {N_SAMPLES} samples x {DWELL * 1e6:.0f} us = {N_SAMPLES * DWELL * 1e3:.2f} ms')

    if plot:
        seq.plot()

    if write:
        write_seq(seq, Path(__file__).parent / seq_filename, 'case0_fid')

    return seq


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--plot', action='store_true', help='show the sequence diagram')
    p.add_argument('--no-write', action='store_true', help='do not write the .seq file')
    args = p.parse_args()
    main(plot=args.plot, write=not args.no_write)
