# Reproducibility record

Reviewed on **2026-10-14** in a separate Windows x86-64 working copy with **CPython 3.12.14 / uv 0.12.17**. This is a fresh environment check on the review machine, not a claim that every OS and hardware combination has been exercised.

## Environment

The repository has a committed `pyproject.toml`, `.python-version` and `uv.lock`. Direct and transitive dependencies are locked. The public quick start uses `uv sync --locked`; caches, environments and generated `.reproduction/` outputs are ignored by Git. First sync requires package-index access.



## Checks actually performed

Notebook and all four input hashes validated; 8 allocation regression tests passed. The full allocation/policy-comparison pipeline reran in an ignored directory. The regenerated run summary exactly matched the retained summary.

| Command | Local result |
| --- | --- |
| `uv run --locked python scripts/verify.py` | Passed |
| `uv run --locked python -m unittest -v test_transfer.py` | Passed |
| `uv run --locked python transfer.py --output-dir .reproduction` | Passed |

## Scope and prerequisites

The policy is greedy and the 7-day transit assumption is fixed. Outputs represent a historical scenario, not realized logistics impact.

The current CI workflow runs the documented locked checks on its configured platform(s). The workflow file itself is not evidence that a remote run passed; use the linked GitHub Actions run for that result. Numerical floating-point differences and external Java/model/data prerequisites are not solved by a Python lock alone.

Notebook changes preserve prior saved outputs. Schema checks compile code without executing all analysis cells. Archived metrics are labeled as historical in the README unless checked directly here.
