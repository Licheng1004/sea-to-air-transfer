# Sea-to-Air Transfer Decision Support

A single maintained, deterministic allocation pipeline for open sales orders, inventory, purchase orders, and monthly air-freight weight quotas. It consolidates the historical greedy notebooks into `transfer.py` and one executed companion notebook.

## Selected policy and rerun results

The selected greedy policy orders candidate purchase lines by proximity to the remaining demand quantity, then by quantity and purchase-line key. Selection maximizes the number of fully allocated sales orders lexicographically by priority 6, 5, 4, 3, and 2; ties favor lower transferred weight.

With the **historical scenario date 2024-11-04** and an **assumed 7-day air transit**:

- 10,264 sales orders and 1,110 separate material-level forecast buffers were evaluated.
- 181 unique purchase lines were selected for air transfer, using **10,185.873 kg** of quota.
- **7,160 sales orders** were fully allocated, versus 7,008 without air transfer.
- **5,834 sales orders** were fully on time, versus 5,766 without air transfer.
- Eight regression tests and the run's conservation checks passed.

Three greedy candidate orders and a no-air baseline were compared on the same inputs. This is the best audited candidate under the stated assumptions, not a proof of global optimization or a forecast of real transport performance.

## Run

Tested with Python 3.12.14. From this repository directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe transfer.py
.\.venv\Scripts\python.exe -m unittest -v test_transfer.py
```

Inspect the executed `analysis.ipynb` in VS Code. To re-execute from a terminal:

```powershell
.\.venv\Scripts\python.exe -m ipykernel install --prefix .venv --name sea-to-air-transfer --display-name "Sea-to-Air Transfer"
.\.venv\Scripts\python.exe -m jupyter nbconvert --execute --to notebook --inplace --ExecutePreprocessor.kernel_name=sea-to-air-transfer analysis.ipynb
```

`transfer.py --as-of YYYY-MM-DD --data-dir PATH --output-dir PATH` accepts overrides. The default scenario is frozen in `config.json`; it deliberately does not use the computer's current date. Existing output names are overwritten on rerun.

## Necessary original data

The following four original Excel files are retained unchanged in `data/`, with hashes in `data_manifest.json`: `Open PO.xlsx`, `Open SO.xlsx`, `Material List.xlsx`, and `Quota.xlsx`. Public release was explicitly authorized by the owner. All input worksheets are `Sheet1`.

Old `After_*` spreadsheets are omitted; they are regenerated as auditable CSV tables. No duplicate historical code versions are maintained.

## Allocation rules and corrections

1. Remove 732 exact duplicate purchase rows. Keep unshipped, positive open quantities. Two conflicting rows share purchase key `4512723718/1` with different due dates and no schedule identifier; both are quarantined instead of inventing additional supply.
2. Join material attributes by material identifier. Inventory is a shared balance per material, not repeated for every joined order. Physical purchase lines are allocated through one shared remaining-quantity ledger.
3. Preserve linked make-to-order demand: a linked sales order can consume only its referenced purchase line. Unlinked demand can use MTS/FMTS supplies of the same material.
4. Apply original priority conventions: original priority 1 becomes 6; other overdue demand becomes 5; priority 4 is retained; eligible VIP demand becomes 3; other demand is 2. Real sales orders precede forecast buffers.
5. Build one forecast buffer per unlinked material from `ceil(planned_delivery_days * monthly_forecast / 30)`, due after that planned lead time. The buffer is not added once per sales-order row.
6. Allocate available stock and receipts by priority and deadline. Consider only each candidate purchase line's own `O02` method and non-SG origin for transfer. A transferred line must arrive earlier under the configured transit assumption.
7. Charge a whole purchase line's weight once, in grams, against that material entity's scenario-month quota. Partial demand allocations may use the remaining quantity of an already-transferred line; they do not consume its quota again.
8. Separate on-time allocation, late allocation, and unallocated demand. An overdue order cannot be made historically on time by an action taken after its deadline.

The original 1022 notebook selected 380 joined rows but only 183 unique purchase keys, including 18 rows with an ineligible method. Its counts are not directly comparable to the corrected model's physical-line decisions. See `results/legacy_audit.json` for rerun details.

## Outputs and checks

- `demand_outcomes.csv`: requested quantity, on-time quantity, late allocated quantity, and unallocated quantity per demand.
- `allocations.csv`: every stock or purchase-line allocation, with deadline and availability date.
- `transfers.csv`: one record per selected physical purchase line.
- `quota_remaining.csv`: initial, spent, and remaining quota by entity.
- `quarantined_po_rows.csv`, `rejected_po_rows.csv`, `invalid_so_rows.csv`: source-data exceptions.
- `candidate_comparison.json` / `.csv`: policy comparison evidence.
- `run_summary.json`: fixed assumptions, row counts, and invariant results.

Tests independently reconcile quota weight, stock consumption, purchase quantities, order links, uniqueness, origin/method eligibility, and overdue timing. Charts and executed outputs are in `analysis.ipynb` and `results/`.

## Assumptions and limitations

The scenario date follows the date on existing historical exports; it is not a verified extraction timestamp. Air transit is an assumption, not a measured carrier service level. Purchase due dates are treated as arrival dates; dates before the scenario date are clipped to the scenario date. There is no cost model, partial-line transfer optimization, customs delay model, or transport-capacity model beyond weight quota. Forecast buffers use the supplied forecast and lead-time fields; their business suitability requires review. Published results support this snapshot and these assumptions only. No new reuse license has been granted.
