"""Run the FULL pipeline (static + RAG + Groq) on every sample case.

Requires GROQ_API_KEY in .env and the installed requirements. Results are written to
docs/ai_test_results.json and are NOT invented: if the API is unavailable the case is
recorded as 'not run'.

Usage (project root):  python tests/run_ai_tests.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from modules import groq_client                 # noqa: E402
from modules.pipeline import run_pipeline       # noqa: E402
from modules.rag_engine import RAGEngine        # noqa: E402
from sample_cases import CASES                  # noqa: E402

if not groq_client.is_configured():
    sys.exit("GROQ_API_KEY is not set in .env - AI tests cannot run (nothing was fabricated).")

rag, results = RAGEngine(), {}
for c in CASES:
    res = run_pipeline(c["code"], c["language"], rag)
    if res["ai_error"]:
        results[c["id"]] = {"status": "NOT RUN", "detail": res["ai_error"]}
        print(c["id"], "NOT RUN:", res["ai_error"])
    else:
        ai = res["ai"]
        results[c["id"]] = {
            "status": "REVIEW",  # a human must judge correctness against the 'expected' column
            "retrieval_available": res["retrieval"]["available"],
            "retrieved_titles": [x["title"] for x in res["retrieval"]["chunks"]],
            "summary": ai["summary"], "root_cause": ai["root_cause"],
            "ai_error_count": len(ai["errors"]),
        }
        print(c["id"], "->", ai["summary"][:90])
    time.sleep(2.5)  # stay under free-tier requests/minute

(ROOT / "docs" / "ai_test_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print("\nSaved docs/ai_test_results.json. Open it, compare each summary with the expected behaviour in "
      "docs/test_cases.md, then set PASS/FAIL by hand (python tests/build_test_doc.py rebuilds the table).")
