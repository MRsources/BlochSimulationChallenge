## What to submit

One entry is one folder, the five ADC files, and a completed copy of [submission.json](../submission.json).

```
submissions/<tool>/
    case0.h5   case1.h5   case2.h5   case3.h5   case4.h5
    submission.json
    simulate.py     optional run script; any name and file type
```

`<tool>` is a short name for the simulator. Put the group in that name when two teams might use the same simulator (`submissions/KomaMRI-Freiburg/`). When one team submits more than one configuration, put the simulation flavour in the name as well (`submissions/MR-zero-isochromat/`).

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
- `runtime_s` and `mrzero_runtime_s` are optional, in seconds. Leave them null when the run was not timed. If you record timings, run [simulation_mr0.py](003_MR-zero/simulation_mr0.py) on the same machine and put that wall-clock in `mrzero_runtime_s`. Evaluation divides the two.
- `solver` and `setup_notes` are optional.

After the entry is on `main`, evaluation writes `README.md` into the submission folder from this JSON.

A run script is optional. Any file name and type is accepted (`simulate.py`, `run.jl`, `fid.ipynb`, and so on). The format check keeps these files and does not require them. It does not run them.

# How to submit

There is two ways to submit. A pull request that targets `main` is the straightforward approach. Alternatively one can submit through this gits issue space. After the files are on `main`, evaluation assigns an id to a folder that does not have one and rebuilds the comparison.


## Pull request

Open a pull request against `main`. Put the folder from [What to submit](#what-to-submit) in the pull request as files, not as a zip. Change only `submissions/<tool>/`. Leave every other file in this repository untouched.

The format check runs when the pull request changes anything under `submissions/`. Merge it into `main`. A pull request from a fork is merged the same way. Evaluation assigns the id.

## Issue

Open a GitHub issue on this repository. You need an account; you do not need to clone the repo or set up git.

**Issue title.** Include the word `submission` and the name of the tool. The form to use is:

```text
submission: <tool>
```

`<tool>` is the same folder name as in [What to submit](#what-to-submit). Put the group in the tool name when two teams might use the same simulator (`submission: KomaMRI-Freiburg`). When one team submits more than one configuration, put the simulation flavour in the name as well (`submission: MR-zero-isochromat`).

**Issue body.** GitHub issues do not accept `.h5` uploads. Pack the same files into one `.zip` or `.tgz`, or gzip each file (`case0.h5.gz` … `case4.h5.gz`, `submission.json.gz`, and the run script when you include one), and drag that archive into the issue. The link has to be a GitHub `user-attachments` link, not a link to another site.

```sh
zip submission.zip case0.h5 case1.h5 case2.h5 case3.h5 case4.h5 submission.json
# optional: add the run script, under any name and file type
# or: tar -czf submission.tgz case0.h5 case1.h5 case2.h5 case3.h5 case4.h5 submission.json
```

A comment on the issue reports whether the unpacked files pass the format check. When they pass, the files are put on `bot/issue-<number>` and a pull request targets `main`. The owner merges that pull request. Evaluation assigns the id and runs on that merge. 