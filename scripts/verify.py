"""Validate the public clone and retained artifacts without private inputs."""
from pathlib import Path
import ast
import hashlib
import json
import nbformat

ROOT = Path(__file__).resolve().parents[1]

def check_notebooks():
    count = 0
    for path in sorted(ROOT.rglob("*.ipynb")):
        if any(part in {".venv", ".git", ".reproduction", ".ipynb_checkpoints"} for part in path.parts):
            continue
        notebook = nbformat.read(path, as_version=4)
        nbformat.validate(notebook)
        for index, cell in enumerate(notebook.cells):
            if cell.cell_type != "code":
                continue
            lines = cell.source.splitlines(keepends=True)
            if next((line.lstrip() for line in lines if line.strip()), "").startswith("%%"):
                continue
            code = "".join(line for line in lines if not line.lstrip().startswith(("%", "!")))
            ast.parse(code, filename=f"{path.relative_to(ROOT)}:{index}")
        count += 1
    print(f"Validated {count} notebook(s). This does not execute their training cells.")

def check_manifest():
    path = ROOT / "data_manifest.json"
    if not path.exists():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest.get("inputs", []):
        relative = entry.get("file")
        expected = entry.get("stored_sha256") or entry.get("sha256")
        if relative and expected:
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            if actual != expected:
                raise SystemExit(f"Input hash mismatch: {relative}")
    print("Input manifest hashes checked where recorded.")

def main():
    check_notebooks()
    check_manifest()
    specific_checks()
    print("Public verification passed. See REPRODUCIBILITY.md for its scope.")

def specific_checks():
    summary = json.loads((ROOT / "results/run_summary.json").read_text(encoding="utf-8"))
    assert summary, "Saved run summary is missing."
    print("Saved run summary is present; run the documented regression checks next.")

if __name__ == "__main__":
    main()
