## What to submit

One entry is one folder, the five ADC files, and a completed copy of [submission.json](../submission.json).

```
submissions/NNN_<tool>/
    case0.h5   case1.h5   case2.h5   case3.h5   case4.h5
    submission.json
    simulate.py     optional run script; any name and file type
```

The folder name starts with the id: three digits, then an underscore, then a short name for the simulator. Look at the folders already in `submissions/` and take the next number. Put the group in the name when two teams might use the same simulator (`NNN_KomaMRI-Freiburg`). When one team submits more than one configuration, put the simulation flavour in the name as well (`NNN_MR-zero-isochromat`).

Each `caseN.h5` is the raw complex ADC vector in acquisition order. Either layout is accepted:

- a complex dataset named `signal`, or
- two floating datasets of the same dtype, `signal_real` and `signal_imag`

```python
import h5py

with h5py.File('case0.h5', 'w') as handle:
    handle.create_dataset('signal_real', data=adc.real)
    handle.create_dataset('signal_imag', data=adc.imag)
    # or: handle.create_dataset('signal', data=adc)
```

`adc` is one complex vector in acquisition order. Case 0 has 1024 samples. Cases 1–4 have 4096.


**Complete `submission.json`.** Copy the sheet from the repository root and fill it in.

- Group and tool name.
- A reference for the code. Set `tool_version` or `tool_commit`. If you have neither, set `tool_date` to the day of the run. One of the three is enough. The format check accepts `tool_date` only as `YYYY-MM-DD`.
- `project_page` of your simulation is optional.
- `paper` is optional. A link on its own is enough, either as a string or as the `link` field of an object. `title`, `authors`, and `year` can be left empty.
- `hardware` is optional.
- `runtime_s` and `mrzero_runtime_s` are optional, in seconds. Leave them null when the run was not timed. If you record timings, run [simulation_mr0.py](001_MR-zero/simulation_mr0.py) on the same machine and put that wall-clock in `mrzero_runtime_s`. Evaluation divides the two.
- `solver` and `setup_notes` are optional.

After the entry is on `main`, evaluation writes `README.md` into the submission folder from this JSON.

A run script is optional. Any file name and type is accepted (`simulate.py`, `run.jl`, `fid.ipynb`, and so on). The format check keeps these files and does not require them. It does not run them.

# How to submit

A pull request that targets `main` is how to submit. After the files are on `main`, evaluation rebuilds the comparison and commits it on `main`.


## Pull request

Open a pull request against `main`. Put the folder from [What to submit](#what-to-submit) in the pull request as files, not as a zip. Change only `submissions/NNN_<tool>/`. Leave every other file in this repository untouched.

The format check runs when the pull request changes anything under `submissions/`. Merge it into `main`. A pull request from a fork is merged the same way. Evaluation rebuilds the comparison and commits it on `main`. 
