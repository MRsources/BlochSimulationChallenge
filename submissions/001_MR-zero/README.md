# MR-zero

`001_MR-zero`

- Group: zMRI Lab (Prof. Zaiss)
- Version: 1.0.8
- Project page: https://github.com/MRsources/MRzero-Core
- Hardware: Intel Core i7-12700K

## Runtime

Relative to MR-zero is `runtime_s / mrzero_runtime_s`.

| Case | Sequence | Runtime (s) | MR-zero (s) | Relative to MR-zero |
|---|---|---:|---:|---:|
| 0 | FID | 3.5 | 3.5 | 1 |
| 1 | RF-spoiled GRE | 25 | 25 | 1 |
| 2 | TSE, 4 shots × 16 echoes | 10.8 | 10.8 | 1 |
| 3 | EPI, T2' = inf | 13.1 | 13.1 | 1 |
| 4 | EPI, published T2' | 13.5 | 13.5 | 1 |

## Setup notes

Maximum RAM usage minus baseline usage in GB: case0: 9, case1: 2, case2: 2, case3: 37, case4: 37
