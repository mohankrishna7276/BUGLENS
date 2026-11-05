"""Code optimisation: simple static metrics + Groq-based suggestions.

Complexity is only *estimated* when it can be reasonably inferred. The static
hint below (loop nesting depth, recursion) is passed to the LLM as evidence and
shown to the user so they can see where the estimate comes from.
"""
import ast
import re

from modules import groq_client


def static_metrics(code, language):
    """Return a dict of cheap, verifiable facts about the code."""
    lines = code.splitlines()
    metrics = {
        "lines_of_code": sum(1 for l in lines if l.strip()),
        "max_loop_depth": None,
        "recursion_detected": False,
        "notes": [],
    }
    if language == "Python":
        try:
            tree = ast.parse(code)
        except SyntaxError:
            metrics["notes"].append("Code has a syntax error, so loop/recursion analysis was skipped.")
            return metrics
        metrics["max_loop_depth"] = _py_loop_depth(tree)
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == fn.name
                   for c in ast.walk(fn)):
                metrics["recursion_detected"] = True
        long_fns = [fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                    and (fn.end_lineno - fn.lineno + 1) > 30]
        if long_fns:
            metrics["notes"].append(f"Long function(s) (>30 lines): {', '.join(long_fns)}")
    else:
        metrics["max_loop_depth"] = _brace_loop_depth(code)
    return metrics


def _py_loop_depth(node, depth=0):
    best = depth
    for child in ast.iter_child_nodes(node):
        d = depth + 1 if isinstance(child, (ast.For, ast.While, ast.AsyncFor)) else depth
        best = max(best, _py_loop_depth(child, d))
    return best


def _brace_loop_depth(code):
    """Approximate loop nesting for brace languages by tracking braces after for/while."""
    depth, best, stack = 0, 0, []
    for line in code.splitlines():
        is_loop = re.search(r"\b(for|while)\s*\(", line) is not None
        for ch in line:
            if ch == "{":
                stack.append(is_loop); is_loop = False
                depth = sum(stack); best = max(best, depth)
            elif ch == "}" and stack:
                stack.pop(); depth = sum(stack)
    return best


OPT_SYSTEM = """You are BugLens AI, a code-quality reviewer for students.
Rules:
- Only give a complexity estimate if it can be reasonably inferred from the code; otherwise set the estimate to "Cannot be determined from the given code" and explain why.
- Never invent measurements or benchmark numbers.
- Keep suggestions concrete and beginner-friendly.
Return ONLY a JSON object with exactly these keys:
{"time_complexity": {"estimate": str, "reasoning": str},
 "space_complexity": {"estimate": str, "reasoning": str},
 "readability": [str],
 "best_practices": [str],
 "optimized_code": str,
 "optimization_notes": str}"""


def optimize_code(code, language):
    """Return (ai_result_dict, static_metrics_dict). Raises GroqUnavailableError on API problems."""
    metrics = static_metrics(code, language)
    user = (f"Language: {language}\n\nCode:\n{groq_client._truncate(code)}\n\n"
            f"Static hints (verified): {metrics}\n\nReturn the JSON object.")
    data = groq_client.chat_json(OPT_SYSTEM, user)
    result = {
        "time_complexity": data.get("time_complexity") or {"estimate": "Not provided", "reasoning": ""},
        "space_complexity": data.get("space_complexity") or {"estimate": "Not provided", "reasoning": ""},
        "readability": data.get("readability") or [],
        "best_practices": data.get("best_practices") or [],
        "optimized_code": data.get("optimized_code", ""),
        "optimization_notes": data.get("optimization_notes", ""),
        "static_metrics": metrics,
    }
    return result
