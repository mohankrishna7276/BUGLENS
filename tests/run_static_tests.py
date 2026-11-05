"""Run the static analyzer on every sample case and print/save honest results.

Usage (from project root):  python tests/run_static_tests.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from modules.analyzer import analyze          # noqa: E402
from sample_cases import CASES                # noqa: E402


def run():
    rows = []
    for c in CASES:
        findings = analyze(c["code"], c["language"])
        rules = [f["rule"] for f in findings if f["severity"] != "info"]
        expected = c["expect_rules"]
        passed = (set(expected) <= set(rules)) if expected else (len(rules) == 0)
        rows.append({
            "id": c["id"], "language": c["language"], "title": c["title"],
            "expected_rules": expected, "actual_rules": rules,
            "actual": "; ".join(f"L{f['line']} {f['rule']}: {f['message']}" for f in findings) or "No findings",
            "status": "PASS" if passed else "FAIL",
        })
    return rows


if __name__ == "__main__":
    rows = run()
    for r in rows:
        print(f"{r['id']} [{r['language']:<10}] {r['status']}  {r['title']}\n      -> {r['actual']}")
    n_pass = sum(r["status"] == "PASS" for r in rows)
    print(f"\nStatic analyzer: {n_pass}/{len(rows)} cases passed")
    (ROOT / "tests" / "static_results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    sys.exit(0 if n_pass == len(rows) else 1)
