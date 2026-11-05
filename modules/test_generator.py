"""Test case generator (Groq-based)."""
import ast

from modules import groq_client

TEST_SYSTEM = """You are BugLens AI, a software testing tutor.
Generate test cases for the submitted code.
Rules:
- Produce normal, edge and boundary cases (2-4 of each).
- Give expected_output ONLY when it can be determined by reasoning about the code. Otherwise use "Cannot be determined".
- Never guess outputs for code that is buggy or ambiguous; say what is unclear in "note".
Return ONLY a JSON object with exactly these keys:
{"normal": [{"input": str, "expected_output": str, "note": str}],
 "edge": [{"input": str, "expected_output": str, "note": str}],
 "boundary": [{"input": str, "expected_output": str, "note": str}]}"""


def _python_signatures(code):
    try:
        return [f"{n.name}({', '.join(a.arg for a in n.args.args)})"
                for n in ast.walk(ast.parse(code)) if isinstance(n, ast.FunctionDef)]
    except SyntaxError:
        return []


def generate_tests(code, language, static_findings=None):
    """Return {"normal": [...], "edge": [...], "boundary": [...]}."""
    hints = []
    if language == "Python":
        sigs = _python_signatures(code)
        if sigs:
            hints.append("Functions found: " + ", ".join(sigs))
    if static_findings:
        hints.append("Known static findings: " + "; ".join(f["message"] for f in static_findings))
    user = (f"Language: {language}\n\nCode:\n{groq_client._truncate(code)}\n\n"
            f"{' '.join(hints)}\n\nReturn the JSON object.")
    data = groq_client.chat_json(TEST_SYSTEM, user)
    return {k: data.get(k) or [] for k in ("normal", "edge", "boundary")}


def tests_to_rows(tests):
    """Flatten the test dict into a list of rows (for a pandas DataFrame / PDF table)."""
    rows = []
    for kind in ("normal", "edge", "boundary"):
        for t in tests.get(kind, []):
            rows.append({"Type": kind.capitalize(), "Input": str(t.get("input", "")),
                         "Expected Output": str(t.get("expected_output", "")),
                         "Note": str(t.get("note", ""))})
    return rows
