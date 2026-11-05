"""Static code analysis.

Findings produced here are *detected* by deterministic rules, in contrast to
the *possible bugs* suggested by the AI model.

method = "ast/compile"  -> Python's own parser/compiler or AST rules (reliable)
method = "pattern"      -> lightweight regex/heuristic checks (may have false positives)
"""
import ast
import builtins
import re

PY_ALLOWED_NAMES = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__",
                                         "__package__", "__builtins__", "__path__"}


def _f(line, severity, rule, message, method):
    return {"line": line, "severity": severity, "rule": rule, "message": message, "method": method}


# =============================================================================
# Python (AST + compile)
# =============================================================================
def _literal_type(node, var_types):
    """Best-effort static type name of an expression, or None if unknown."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "bool"
        return type(node.value).__name__ if node.value is not None else None
    if isinstance(node, ast.JoinedStr):
        return "str"
    if isinstance(node, ast.Name):
        return var_types.get(node.id)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return {"input": "str", "str": "str", "int": "int", "float": "float", "len": "int"}.get(node.func.id)
    return None


def _call_arity_issue(func, call):
    """Return a message if `call` has a wrong number of args for local def `func`."""
    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return None
    a = func.args
    positional = a.posonlyargs + a.args
    n_given = len(call.args)
    kw_names = {k.arg for k in call.keywords}
    required = len(positional) - len(a.defaults)
    given_by_kw = sum(1 for p in positional[n_given:] if p.arg in kw_names)
    if n_given > len(positional) and a.vararg is None:
        return f"Function '{func.name}' takes {len(positional)} argument(s) but {n_given} were given."
    missing = [p.arg for p in positional[n_given:required] if p.arg not in kw_names]
    if n_given < required and missing:
        return f"Function '{func.name}' is missing required argument(s): {', '.join(missing)}."
    return None


def analyze_python(code):
    findings = []
    try:
        tree = ast.parse(code)
        compile(tree, "<submitted>", "exec")
    except SyntaxError as e:  # includes IndentationError and TabError
        findings.append(_f(e.lineno, "error", "syntax-error",
                           f"{type(e).__name__}: {e.msg}", "ast/compile"))
        return findings
    except (ValueError, MemoryError) as e:
        findings.append(_f(None, "error", "compile-error", str(e), "ast/compile"))
        return findings

    # ---- collect facts -------------------------------------------------------
    defined, loads, store_counts = set(), [], {}
    star_import = False
    method_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            defined.add(node.name)
            method_ids |= {id(n) for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
            allargs = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            defined |= {a.arg for a in allargs}
            if node.args.vararg: defined.add(node.args.vararg.arg)
            if node.args.kwarg: defined.add(node.args.kwarg.arg)
        elif isinstance(node, ast.Lambda):
            defined |= {a.arg for a in node.args.args + node.args.kwonlyargs}
            if node.args.vararg: defined.add(node.args.vararg.arg)
            if node.args.kwarg: defined.add(node.args.kwarg.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    star_import = True
                defined.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            defined |= set(node.names)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                defined.add(node.id)
                store_counts[node.id] = store_counts.get(node.id, 0) + 1
            else:
                loads.append(node)
        elif hasattr(ast, "MatchAs") and isinstance(node, ast.MatchAs) and node.name:
            defined.add(node.name)

    # ---- undefined names -------------------------------------------------------
    if not star_import:
        seen = set()
        for n in loads:
            if n.id not in defined and n.id not in PY_ALLOWED_NAMES and n.id not in seen:
                seen.add(n.id)
                findings.append(_f(n.lineno, "error", "undefined-name",
                                   f"Name '{n.id}' is used but never defined (NameError at runtime).",
                                   "ast/compile"))

    # ---- single-assignment literal tracking (types and lengths) ------------------
    var_types, var_lens = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if store_counts.get(name) != 1:
                continue
            t = _literal_type(node.value, var_types)
            if t:
                var_types[name] = t
            v = node.value
            if isinstance(v, (ast.List, ast.Tuple)) and not any(isinstance(e, ast.Starred) for e in v.elts):
                var_lens[name] = len(v.elts)
            elif isinstance(v, ast.Constant) and isinstance(v.value, str):
                var_lens[name] = len(v.value)

    # ---- function definitions for arity check ------------------------------------
    funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and id(node) not in method_ids:
            funcs.setdefault(node.name, []).append(node)

    for node in ast.walk(tree):
        # type mismatch: str + number
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            lt, rt = _literal_type(node.left, var_types), _literal_type(node.right, var_types)
            if {lt, rt} & {"str"} and {lt, rt} & {"int", "float"}:
                findings.append(_f(node.lineno, "error", "type-mismatch",
                                   f"TypeError: cannot add '{lt}' and '{rt}'. Convert with str()/int()/float() "
                                   "or use an f-string.", "ast/compile"))
        # division by literal zero
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) \
                and isinstance(node.right, ast.Constant) and node.right.value == 0 \
                and not isinstance(node.right.value, bool):
            findings.append(_f(node.lineno, "error", "zero-division",
                               "ZeroDivisionError: division or modulo by zero.", "ast/compile"))
        # constant index out of range
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in var_lens:
            idx = node.slice
            val = None
            if isinstance(idx, ast.Constant) and isinstance(idx.value, int):
                val = idx.value
            elif isinstance(idx, ast.UnaryOp) and isinstance(idx.op, ast.USub) \
                    and isinstance(idx.operand, ast.Constant) and isinstance(idx.operand.value, int):
                val = -idx.operand.value
            n = var_lens[node.value.id]
            if val is not None and not isinstance(idx, ast.Slice) and (val >= n or val < -n):
                findings.append(_f(node.lineno, "error", "index-out-of-range",
                                   f"IndexError: index {val} is out of range for '{node.value.id}' "
                                   f"(length {n}, valid indexes 0..{n - 1}).", "ast/compile"))
        # function call arity
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in funcs \
                and len(funcs[node.func.id]) == 1 and store_counts.get(node.func.id, 0) == 0:
            msg = _call_arity_issue(funcs[node.func.id][0], node)
            if msg:
                findings.append(_f(node.lineno, "error", "argument-mismatch", "TypeError: " + msg, "ast/compile"))
        # infinite loops
        if isinstance(node, ast.While):
            f = _check_while(node)
            if f:
                findings.append(f)
        # bare except
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append(_f(node.lineno, "warning", "bare-except",
                               "Bare 'except:' hides real errors; catch specific exceptions.", "ast/compile"))
        # mutable default argument
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    findings.append(_f(node.lineno, "warning", "mutable-default",
                                       f"Function '{node.name}' uses a mutable default argument "
                                       "(shared between calls). Use None instead.", "ast/compile"))
        # 'is' with literal
        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(comp, ast.Constant) \
                        and isinstance(comp.value, (int, str, float)) and not isinstance(comp.value, bool):
                    findings.append(_f(node.lineno, "warning", "is-literal",
                                       "Use '==' to compare with a literal, not 'is'.", "ast/compile"))
    findings.sort(key=lambda x: (x["line"] or 0))
    return findings


def _check_while(node):
    body_nodes = [n for s in node.body for n in ast.walk(s)]
    exits = any(isinstance(n, (ast.Break, ast.Return, ast.Raise)) for n in body_nodes) or any(
        isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name))
        and getattr(n.func, "attr", getattr(n.func, "id", "")) in ("exit", "_exit", "quit")
        for n in body_nodes)
    test = node.test
    if isinstance(test, ast.Constant) and test.value and not exits:
        return _f(node.lineno, "warning", "infinite-loop",
                  "Possible infinite loop: 'while True' has no break/return/exit in its body.", "ast/compile")
    test_nodes = list(ast.walk(test))
    if any(isinstance(n, ast.Call) for n in test_nodes):
        return None
    names = {n.id for n in test_nodes if isinstance(n, ast.Name)}
    if not names or exits:
        return None
    modified = {n.id for n in body_nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    for n in body_nodes:  # method calls such as q.pop() may change the condition
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
            modified.add(n.func.value.id)
    if not (names & modified):
        return _f(node.lineno, "warning", "infinite-loop",
                  f"Possible infinite loop: condition variable(s) {sorted(names)} are never "
                  "changed inside the loop body.", "ast/compile")
    return None


# =============================================================================
# Java / C / JavaScript (lightweight pattern checks)
# =============================================================================
def _mask(code, language, keep_strings=False):
    """Blank out comments (and string contents) while preserving length and newlines."""
    out, i, n = [], 0, len(code)
    while i < n:
        c, nxt = code[i], code[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            while i < n and code[i] != "\n":
                out.append(" "); i += 1
        elif c == "/" and nxt == "*":
            out.append("  "); i += 2
            while i < n and not (code[i] == "*" and i + 1 < n and code[i + 1] == "/"):
                out.append("\n" if code[i] == "\n" else " "); i += 1
            out.append("  "); i += 2
        elif c in "\"'" or (c == "`" and language == "JavaScript"):
            q = c
            out.append(q); i += 1
            while i < n and code[i] != q and (code[i] != "\n" or q == "`"):
                if code[i] == "\\" and i + 1 < n:
                    out.append(code[i] if keep_strings else " "); i += 1
                out.append(code[i] if keep_strings or code[i] == "\n" else " "); i += 1
            if i < n and code[i] == q:
                out.append(q); i += 1
        else:
            out.append(c); i += 1
    return "".join(out)


def _line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def _match_paren(text, open_pos):
    depth = 0
    for j in range(open_pos, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _check_brackets(masked):
    findings, stack = [], []
    pairs = {")": "(", "]": "[", "}": "{"}
    line = 1
    for ch in masked:
        if ch == "\n":
            line += 1
        elif ch in "([{":
            stack.append((ch, line))
        elif ch in ")]}":
            if not stack:
                findings.append(_f(line, "error", "unbalanced-bracket", f"Unmatched closing '{ch}'.", "pattern"))
            elif stack[-1][0] != pairs[ch]:
                findings.append(_f(line, "error", "unbalanced-bracket",
                                   f"Mismatched bracket: '{ch}' closes '{stack[-1][0]}' from line {stack[-1][1]}.",
                                   "pattern"))
                stack.pop()
            else:
                stack.pop()
    for ch, ln in stack:
        findings.append(_f(ln, "error", "unbalanced-bracket", f"Opening '{ch}' is never closed.", "pattern"))
    return findings


_CONTROL = re.compile(r"^(if|for|while|switch|else\s+if|catch|synchronized)\b")
_BARE = re.compile(r"^(else|do|try|finally|default)$")
_DECL_START = re.compile(r"^(public|private|protected|static|final|abstract|class|interface|enum|struct|"
                         r"union|typedef|extends|implements)\b")
_SIGNATURE = re.compile(r"^[\w<>\[\],.\s*&]+\s+\**\w+\s*\(")  # e.g. 'static int add(int a, int b)'


def _check_semicolons(masked):
    """Heuristic 'missing semicolon' check for C and Java.

    A line is *skipped* when it legitimately ends without ';' (block openers, control
    headers, function signatures, continuation lines). Everything else is flagged.
    """
    findings, lines = [], masked.split("\n")
    depth_at_start, depth = [], 0          # () and [] depth, to skip multi-line expressions
    for ln in lines:
        depth_at_start.append(depth)
        depth += ln.count("(") + ln.count("[") - ln.count(")") - ln.count("]")
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or s.startswith(("#", "@", ".")) or depth_at_start[i] != 0:
            continue
        if s[-1] in ";{},(:" or s[-1] in "+-*/=&|<>?^%!~" or _BARE.match(s):
            continue                                   # already terminated / continues on next line
        nxt = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
        if nxt.startswith(("{", ".", "?", ":", "&&", "||", "+", "-", "*", "/", "=")):
            continue                                   # next line continues or opens this statement
        if _DECL_START.match(s) and not s.endswith(")"):
            continue                                   # 'public class Main' etc.
        if s.endswith(")") and (_CONTROL.match(s) or _SIGNATURE.match(s) and not s.startswith("return")
                                and not re.match(r"^(System|printf|scanf|puts)\b", s)):
            continue                                   # 'if (...)' / 'int f(int a)' before body
        findings.append(_f(i + 1, "error", "missing-semicolon",
                           "Likely missing ';' at the end of this statement.", "pattern"))
    return findings


def _top_level_assignment(cond):
    """True if `cond` contains a single '=' outside nested parentheses (e.g. 'x = 5')."""
    depth = 0
    for k, ch in enumerate(cond):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "=" and depth == 0:
            prev = cond[k - 1] if k else ""
            nxt = cond[k + 1] if k + 1 < len(cond) else ""
            if prev not in "=!<>+-*/%&|^" and nxt not in "=>":
                return True
    return False


def _check_assign_in_condition(masked, language):
    findings = []
    for m in re.finditer(r"\b(if|while)\s*\(", masked):
        open_pos = m.end() - 1
        close = _match_paren(masked, open_pos)
        if close != -1 and _top_level_assignment(masked[open_pos + 1:close]):
            findings.append(_f(_line_of(masked, m.start()), "warning", "assignment-in-condition",
                               "Assignment '=' used inside a condition. Did you mean '==' (comparison)?",
                               "pattern"))
    return findings


def _check_c(code):
    nc = _mask(code, "C", keep_strings=True)
    masked = _mask(code, "C")
    findings = []
    # scanf missing &
    for m in re.finditer(r"\bscanf\s*\(", nc):
        close = _match_paren(nc, m.end() - 1)
        if close == -1:
            continue
        args = _split_args(nc[m.end():close])
        if not args or not args[0].strip().startswith('"'):
            continue
        specs = re.findall(r"%(?!%)\*?\d*(?:hh|h|ll|l|L|z|j|t)?([diouxXfFeEgGaAcsp]|\[[^\]]*\])", args[0])
        for spec, arg in zip(specs, args[1:]):
            if re.fullmatch(r"[A-Za-z_]\w*", arg.strip()) and not spec.startswith(("s", "[")):
                findings.append(_f(_line_of(nc, m.start()), "error", "scanf-missing-address",
                                   f"scanf: '{arg.strip()}' needs '&' (use &{arg.strip()}); without it the "
                                   "program writes to an invalid address.", "pattern"))
    for m in re.finditer(r"\bgets\s*\(", masked):
        findings.append(_f(_line_of(masked, m.start()), "warning", "unsafe-gets",
                           "gets() is unsafe (buffer overflow) and removed in C11; use fgets().", "pattern"))
    if re.search(r"\b(printf|scanf|puts|fgets|fopen)\s*\(", masked) and not re.search(r"#\s*include\s*<stdio\.h>", code):
        m = re.search(r"\b(printf|scanf|puts|fgets|fopen)\s*\(", masked)
        findings.append(_f(_line_of(masked, m.start()), "warning", "missing-include",
                           "Uses stdio functions but '#include <stdio.h>' is missing.", "pattern"))
    # array off-by-one: int arr[5]; for (i = 0; i <= 5; i++) arr[i]
    for dm in re.finditer(r"\b(?:int|char|float|double|long|short)\s+(\w+)\s*\[\s*(\d+)\s*\]", masked):
        name, size = dm.group(1), dm.group(2)
        for lm in re.finditer(r"for\s*\([^;]*;\s*(\w+)\s*<=\s*" + size + r"\s*;", masked):
            if re.search(name + r"\s*\[\s*" + lm.group(1) + r"\s*\]", masked[lm.end():lm.end() + 300]):
                findings.append(_f(_line_of(masked, lm.start()), "error", "off-by-one",
                                   f"Loop uses '{lm.group(1)} <= {size}' but '{name}' has {size} elements "
                                   f"(valid indexes 0..{int(size) - 1}). Use '<'.", "pattern"))
    return masked, findings


def _split_args(s):
    args, depth, cur, in_str = [], 0, [], False
    for ch in s:
        if ch == '"':
            in_str = not in_str
        if not in_str:
            if ch in "([{": depth += 1
            elif ch in ")]}": depth -= 1
            elif ch == "," and depth == 0:
                args.append("".join(cur)); cur = []; continue
        cur.append(ch)
    args.append("".join(cur))
    return args


def _check_length_loops(masked, findings):
    for lm in re.finditer(r"for\s*\([^;]*;\s*(\w+)\s*<=\s*(\w+)\.length\b", masked):
        var, arr = lm.group(1), lm.group(2)
        if re.search(arr + r"\s*\[\s*" + var + r"\s*\]", masked[lm.end():lm.end() + 300]):
            findings.append(_f(_line_of(masked, lm.start()), "error", "off-by-one",
                               f"Loop uses '{var} <= {arr}.length' and indexes '{arr}[{var}]'; the last index is "
                               f"{arr}.length - 1. Use '<'.", "pattern"))


def _check_java(code):
    nc = _mask(code, "Java", keep_strings=True)
    masked = _mask(code, "Java")
    findings = []
    for m in re.finditer(r"(==|!=)\s*\"|\"\s*(==|!=)", nc):
        findings.append(_f(_line_of(nc, m.start()), "warning", "string-equality",
                           "Strings compared with ==/!= (compares references). Use .equals().", "pattern"))
    for m in re.finditer(r"\bsystem\.out\b", masked):
        findings.append(_f(_line_of(masked, m.start()), "error", "case-typo",
                           "'system.out' should be 'System.out' (Java is case-sensitive).", "pattern"))
    for m in re.finditer(r"\bint\s+\w+\s*=\s*\"|\bString\s+\w+\s*=\s*-?\d", nc):
        findings.append(_f(_line_of(nc, m.start()), "error", "type-mismatch",
                           "Incompatible types: assigning a String to a numeric variable or a number to a String.",
                           "pattern"))
    _check_length_loops(masked, findings)
    return masked, findings


def _check_js(code):
    masked = _mask(code, "JavaScript")
    findings = []
    for m in re.finditer(r"[^=!<>]==(?!=)", masked):
        findings.append(_f(_line_of(masked, m.start()), "info", "loose-equality",
                           "Loose equality '==' performs type coercion; prefer '==='.", "pattern"))
    for m in re.finditer(r"\bvar\s+\w+", masked):
        findings.append(_f(_line_of(masked, m.start()), "info", "var-usage",
                           "'var' is function-scoped; prefer 'let' or 'const'.", "pattern"))
    for dm in re.finditer(r"\bconst\s+(\w+)", masked):
        name = dm.group(1)
        for rm in re.finditer(r"(?<![\w.])" + name + r"\s*(?:=(?!=)|\+\+|--|\+=|-=|\*=|/=)", masked[dm.end():]):
            findings.append(_f(_line_of(masked, dm.end() + rm.start()), "error", "const-reassign",
                               f"TypeError: assignment to constant variable '{name}' (declared with const).",
                               "pattern"))
            break
    _check_length_loops(masked, findings)
    return masked, findings


def analyze_other(code, language):
    if language == "C":
        masked, findings = _check_c(code)
    elif language == "Java":
        masked, findings = _check_java(code)
    else:
        masked, findings = _check_js(code)
    findings += _check_brackets(masked)
    findings += _check_assign_in_condition(masked, language)
    if language in ("C", "Java"):
        findings += _check_semicolons(masked)
    findings.sort(key=lambda x: (x["line"] or 0))
    return findings


# =============================================================================
# Public API
# =============================================================================
def analyze(code, language):
    """Run static analysis and return a list of finding dicts."""
    if not code or not code.strip():
        return []
    if language == "Python":
        return analyze_python(code)
    return analyze_other(code, language)


def split_findings(findings):
    """Return (errors, warnings_and_info)."""
    return ([f for f in findings if f["severity"] == "error"],
            [f for f in findings if f["severity"] != "error"])
