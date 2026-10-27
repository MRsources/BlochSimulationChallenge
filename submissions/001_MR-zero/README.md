# MR-zero

`001_MR-zero`

- Group: zMRI Lab (Prof. Zaiss)
- Version: 1.2.0
- Project page: https://github.com/MRsources/MRzero-Core
- Hardware: Intel Core i7-12700K

## Paper

https://doi.org/10.48550/arXiv.2002.04265

## Runtime

Relative to MR-zero is `runtime_s / mrzero_runtime_s`.

| Case | Sequence | Runtime (s) | MR-zero (s) | Relative to MR-zero |
|---|---|---:|---:|---:|
| 0 | FID | 2.8 | 2.8 | 1 |
| 1 | RF-spoiled GRE | 24.3 | 24.3 | 1 |
| 2 | TSE, 4 shots × 16 echoes | 9.7 | 9.7 | 1 |
| 3 | EPI, T2' = inf | 12.1 | 12.1 | 1 |
| 4 | EPI, published T2' | 12.3 | 12.3 | 1 |

## Setup notes

Maximum RAM usage minus baseline usage in GB: case0: 9, case1: 2, case2: 2, case3: 37, case4: 37
