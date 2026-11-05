"""BugLens AI - Streamlit dashboard.

Run with:  streamlit run app.py
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, TextLexer

import config
from modules import analyzer, groq_client, code_optimizer, test_generator
from modules.pipeline import run_pipeline
from modules.rag_engine import RAGEngine, load_knowledge
from modules.report_generator import generate_pdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:  # sample programs for the "Load example" dropdown
    from tests.sample_cases import CASES as SAMPLE_CASES
except Exception:  # pragma: no cover - the app works without examples
    SAMPLE_CASES = []

st.set_page_config(page_title=config.APP_NAME, page_icon="🔍", layout="wide")

PAGES = ["Home", "Debug Code", "Code Optimization", "Test Case Generator", "Debugging History", "About Project"]
LEXERS = {"Python": "python", "Java": "java", "C": "c", "JavaScript": "javascript"}

CSS = """
<style>
html, body, [class*="css"] { font-family: 'Segoe UI', 'Inter', system-ui, sans-serif; }
h1, h2, h3 { letter-spacing: -0.01em; }
.bl-hero { padding: 1.4rem 1.6rem; border-radius: 14px; margin-bottom: 1rem;
  background: linear-gradient(135deg, #12233d 0%, #161B26 70%); border: 1px solid #263248; }
.bl-hero h1 { margin: 0 0 .3rem 0; color: #4FC3F7; }
.bl-hero p { margin: 0; color: #B8C4D9; }
.bl-card { padding: 1rem 1.1rem; border-radius: 12px; background: #161B26; border: 1px solid #263248;
  height: 100%; }
.bl-card h4 { margin: 0 0 .4rem 0; color: #E6EAF2; }
.bl-card p { margin: 0; color: #9FB0CC; font-size: .92rem; }
.bl-badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem;
  font-weight: 600; margin-right: .4rem; }
.bl-red { background: #4a1d24; color: #ff8a95; } .bl-green { background: #1b3a2a; color: #7ee2a8; }
.bl-amber { background: #4a3a12; color: #ffd36b; } .bl-blue { background: #14324a; color: #7cc4ff; }
.bl-gray { background: #2a3140; color: #b8c4d9; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_rag():
    return RAGEngine()


def badge(text, color="gray"):
    return f'<span class="bl-badge bl-{color}">{text}</span>'


def show_code(code, language, title=None):
    """Syntax-highlighted code block (Pygments, monokai)."""
    if title:
        st.markdown(f"**{title}**")
    try:
        lexer = get_lexer_by_name(LEXERS.get(language, "text"))
    except Exception:
        lexer = TextLexer()
    html = highlight(code or "", lexer, HtmlFormatter(style="monokai", noclasses=True,
                                                     cssstyles="padding:12px;border-radius:8px;overflow-x:auto;font-size:13px;"))
    if hasattr(st, "html"):
        st.html(html)
    else:  # very old Streamlit
        st.code(code or "", language=LEXERS.get(language, "text"))


def init_state():
    ss = st.session_state
    ss.setdefault("history", [])       # list of records (one per code + language)
    ss.setdefault("next_id", 1)
    ss.setdefault("debug_id", None)    # id of the record shown on the Debug page
    # Keep widget values alive when the user switches pages (documented Streamlit workaround)
    for key in ("debug_code", "debug_lang", "opt_code", "opt_lang", "test_code", "test_lang"):
        if key in ss:
            ss[key] = ss[key]


def get_or_create_record(code, language):
    """One record per (code, language) so debug/optimization/tests are combined in one PDF."""
    ss = st.session_state
    for r in reversed(ss.history):
        if r["code"] == code and r["language"] == language:
            return r
    rec = {"id": ss.next_id, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "language": language, "code": code, "static_findings": None, "retrieval": None,
           "ai": None, "ai_error": None, "optimization": None, "tests": None}
    ss.next_id += 1
    ss.history.append(rec)
    return rec


def find_record(rec_id):
    return next((r for r in st.session_state.history if r["id"] == rec_id), None)


def _load_example(code, language):
    st.session_state["debug_code"] = code
    st.session_state["debug_lang"] = language


def _on_upload():
    f = st.session_state.get("debug_upload")
    if f is not None:
        st.session_state["debug_code"] = f.getvalue().decode("utf-8", errors="replace")
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext in config.FILE_EXTENSIONS:
            st.session_state["debug_lang"] = config.FILE_EXTENSIONS[ext]


def code_input(prefix, button_label):
    """Language selector + text area. Returns (language, code, clicked)."""
    ss = st.session_state
    ss.setdefault(f"{prefix}_lang", ss.get("last_lang", "Python"))
    ss.setdefault(f"{prefix}_code", ss.get("last_code", ""))
    c1, c2 = st.columns([1, 3])
    with c1:
        language = st.selectbox("Programming language", config.SUPPORTED_LANGUAGES, key=f"{prefix}_lang")
    code = st.text_area("Paste your code here", height=300, key=f"{prefix}_code",
                        placeholder="Paste source code or an error message...")
    clicked = st.button(button_label, type="primary", key=f"{prefix}_btn")
    return language, code, clicked


def validate(code):
    if not code or not code.strip():
        st.warning("Please paste some code first.")
        return False
    if len(code) > config.MAX_CODE_CHARS:
        st.warning(f"Code is longer than {config.MAX_CODE_CHARS} characters; only the first part "
                   "will be sent to the AI model (free-tier limits).")
    return True


def pdf_button(record, key):
    st.download_button("Download PDF report", data=generate_pdf(record),
                       file_name=f"buglens_report_{record['id']}.pdf", mime="application/pdf", key=key)


# ----------------------------------------------------------------------------
# Result renderers
# ----------------------------------------------------------------------------
def render_findings(findings):
    st.markdown("### Detected by static analysis")
    st.caption("Deterministic checks (Python compiler/AST, or lightweight pattern rules for other languages).")
    if findings is None:
        st.info("Static analysis has not been run yet.")
    elif not findings:
        st.success("No errors detected by static analysis. (This does not prove the code is correct.)")
    else:
        df = pd.DataFrame([{"Line": f["line"], "Severity": f["severity"], "Rule": f["rule"],
                            "Message": f["message"], "Method": f["method"]} for f in findings])
        st.dataframe(df, hide_index=True)
        st.markdown(badge("Pattern checks can have false positives", "amber") if any(
            f["method"] == "pattern" for f in findings) else "", unsafe_allow_html=True)


def render_retrieval(retrieval):
    if retrieval is None:
        return
    if not retrieval["available"]:
        st.warning(f"Knowledge retrieval unavailable: {retrieval['reason']} "
                   "The AI analysis ran WITHOUT retrieved context.")
        return
    with st.expander(f"Retrieved knowledge (top {len(retrieval['chunks'])} from ChromaDB)"):
        for c in retrieval["chunks"]:
            st.markdown(f"**{c['title']}**  \n{badge(c['category'], 'blue')}"
                        f"{badge('similarity ' + str(c['similarity']), 'gray')}", unsafe_allow_html=True)
            st.write(c["text"])
            st.divider()


def render_ai(record):
    st.markdown("### AI debugging analysis")
    if record.get("ai_error"):
        st.error(record["ai_error"])
        st.caption("No AI result is shown because none was generated. Static analysis results above are still valid.")
        return
    ai = record.get("ai")
    if not ai:
        st.info("AI analysis has not been run yet.")
        return
    st.markdown(badge("AI-generated", "blue") + badge("verify before trusting", "amber"), unsafe_allow_html=True)
    if ai["summary"]:
        st.write(ai["summary"])
    if ai["errors"]:
        st.markdown("**Errors identified by the AI**")
        st.dataframe(pd.DataFrame([{"Line": e.get("line"), "Type": e.get("type"),
                                    "Description": e.get("description")} for e in ai["errors"]]),
                     hide_index=True)
    if ai["possible_bugs"]:
        st.markdown("**Possible bugs (AI-suggested, not verified)**")
        for b in ai["possible_bugs"]:
            st.markdown(f"- Line {b.get('line') or '?'}: {b.get('description')}")
    st.markdown("**Root cause**")
    st.write(ai["root_cause"] or "Not provided.")
    if ai["affected_section"]:
        st.markdown(f"**Affected section:** {ai['affected_section']}")
    if ai["corrected_code"]:
        show_code(ai["corrected_code"], record["language"], "Corrected code")
    with st.expander("Explanation of the correction", expanded=True):
        st.write(ai["explanation"] or "Not provided.")
    with st.expander("Prevention tips"):
        for t in ai["prevention_tips"]:
            st.markdown(f"- {t}")


def render_debug_results(record, key_prefix):
    render_findings(record["static_findings"])
    render_retrieval(record["retrieval"])
    render_ai(record)
    st.divider()
    pdf_button(record, key=f"pdf_{key_prefix}_{record['id']}")


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------
def page_home():
    st.markdown(f"""<div class="bl-hero"><h1>🔍 {config.APP_NAME}</h1>
    <p>{config.APP_TAGLINE}. Paste code, understand the bug, learn how to fix it.</p></div>""",
                unsafe_allow_html=True)
    cols = st.columns(3)
    cards = [("Debug Code", "Static analysis + RAG + Groq LLM explain the error, root cause and fix."),
             ("Code Optimization", "Complexity hints, readability and best-practice suggestions."),
             ("Test Case Generator", "Normal, edge and boundary test cases with expected outputs when known."),
             ("Debugging History", "Every submission in this browser session, with its analysis."),
             ("PDF Reports", "Download code, errors, fixes, explanations, optimizations and tests."),
             ("Learn, don't just copy", "Explanations are written for students, with prevention tips.")]
    for i, (t, d) in enumerate(cards):
        with cols[i % 3]:
            st.markdown(f'<div class="bl-card"><h4>{t}</h4><p>{d}</p></div>', unsafe_allow_html=True)
            st.write("")

    st.markdown("### System status")
    c1, c2, c3 = st.columns(3)
    c1.markdown("**Groq API key**<br>" + (badge("configured", "green") if groq_client.is_configured()
                                          else badge("missing - add to .env", "red")), unsafe_allow_html=True)
    c2.markdown(f"**Knowledge base**<br>{badge(str(len(load_knowledge())) + ' documents', 'blue')}",
                unsafe_allow_html=True)
    rag_state = st.session_state.get("rag_status")
    c3.markdown("**Vector index (ChromaDB)**<br>" + (
        badge("not checked yet", "gray") if rag_state is None else
        badge("ready", "green") if rag_state[0] else badge("unavailable", "red")), unsafe_allow_html=True)
    if st.button("Build / check knowledge index"):
        with st.spinner("Loading embedding model and indexing (first run downloads ~90 MB)..."):
            st.session_state["rag_status"] = get_rag().build_index()
        ok, msg = st.session_state["rag_status"]
        (st.success if ok else st.error)(msg)
    st.caption("Static analysis, history and the PDF report work without an API key. "
               "AI debugging, optimization and test generation need a Groq API key.")


def page_debug():
    st.title("Debug Code")
    ss = st.session_state
    with st.expander("Load an example or upload a file"):
        ex_lang = ss.get("debug_lang", "Python")
        examples = [c for c in SAMPLE_CASES if c["language"] == ex_lang]
        if examples:
            titles = [f"{c['id']} - {c['title']}" for c in examples]
            choice = st.selectbox(f"Example programs ({ex_lang})", titles, key=f"example_choice_{ex_lang}")
            case = examples[titles.index(choice)] if choice in titles else examples[0]
            st.button("Load example", on_click=_load_example, args=(case["code"], case["language"]))
        st.file_uploader("Or upload a code file", type=list(config.FILE_EXTENSIONS) + ["txt"],
                         key="debug_upload", on_change=_on_upload)

    language, code, clicked = code_input("debug", "Analyze Code")
    if clicked and validate(code):
        ss["last_code"], ss["last_lang"] = code, language
        record = get_or_create_record(code, language)
        with st.spinner("Analyzing: static checks -> retrieval -> Groq (first run may download the embedding model)..."):
            result = run_pipeline(code, language, get_rag())
        record.update(static_findings=result["static_findings"], retrieval=result["retrieval"],
                      ai=result["ai"], ai_error=result["ai_error"])
        ss["debug_id"] = record["id"]
    rec = find_record(ss.get("debug_id"))
    if rec:
        st.divider()
        render_debug_results(rec, "debug")


def page_optimize():
    st.title("Code Optimization")
    st.caption("Complexity is only estimated when it can be reasonably inferred from your code.")
    language, code, clicked = code_input("opt", "Analyze Optimization")
    if clicked and validate(code):
        st.session_state["last_code"], st.session_state["last_lang"] = code, language
        record = get_or_create_record(code, language)
        try:
            with st.spinner("Asking Groq for optimization suggestions..."):
                record["optimization"] = code_optimizer.optimize_code(code, language)
            if record["static_findings"] is None:
                record["static_findings"] = analyzer.analyze(code, language)
        except groq_client.GroqUnavailableError as exc:
            st.error(str(exc))
        st.session_state["opt_id"] = record["id"]
    rec = find_record(st.session_state.get("opt_id"))
    if rec and rec["optimization"]:
        opt = rec["optimization"]
        m = opt["static_metrics"]
        st.markdown("### Verified static metrics")
        c1, c2, c3 = st.columns(3)
        c1.metric("Lines of code", m["lines_of_code"])
        c2.metric("Max loop nesting", "n/a" if m["max_loop_depth"] is None else m["max_loop_depth"])
        c3.metric("Recursion detected", "Yes" if m["recursion_detected"] else "No")
        for n in m["notes"]:
            st.info(n)
        st.markdown("### AI-estimated complexity")
        c1, c2 = st.columns(2)
        c1.markdown(f"**Time:** `{opt['time_complexity'].get('estimate', '')}`")
        c1.caption(opt["time_complexity"].get("reasoning", ""))
        c2.markdown(f"**Space:** `{opt['space_complexity'].get('estimate', '')}`")
        c2.caption(opt["space_complexity"].get("reasoning", ""))
        with st.expander("Readability suggestions", expanded=True):
            for s in opt["readability"]:
                st.markdown(f"- {s}")
        with st.expander("Best practices", expanded=True):
            for s in opt["best_practices"]:
                st.markdown(f"- {s}")
        if opt["optimized_code"]:
            show_code(opt["optimized_code"], rec["language"], "Suggested optimized code")
            if opt["optimization_notes"]:
                st.caption(opt["optimization_notes"])
        st.divider()
        pdf_button(rec, key=f"pdf_opt_{rec['id']}")


def page_tests():
    st.title("Test Case Generator")
    st.caption("Expected outputs are only given when they can be determined from the code.")
    language, code, clicked = code_input("test", "Generate Test Cases")
    if clicked and validate(code):
        st.session_state["last_code"], st.session_state["last_lang"] = code, language
        record = get_or_create_record(code, language)
        if record["static_findings"] is None:
            record["static_findings"] = analyzer.analyze(code, language)
        try:
            with st.spinner("Asking Groq to generate test cases..."):
                record["tests"] = test_generator.generate_tests(code, language, record["static_findings"])
        except groq_client.GroqUnavailableError as exc:
            st.error(str(exc))
        st.session_state["test_id"] = record["id"]
    rec = find_record(st.session_state.get("test_id"))
    if rec and rec["tests"]:
        rows = test_generator.tests_to_rows(rec["tests"])
        if not rows:
            st.warning("The model returned no test cases. Try again.")
            return
        df = pd.DataFrame(rows)
        tabs = st.tabs(["Normal", "Edge", "Boundary"])
        for tab, kind in zip(tabs, ["Normal", "Edge", "Boundary"]):
            with tab:
                sub = df[df["Type"] == kind].drop(columns="Type")
                st.dataframe(sub, hide_index=True) if len(sub) else st.info("None generated.")
        st.download_button("Download test cases (CSV)", df.to_csv(index=False), "buglens_tests.csv",
                           "text/csv", key=f"csv_{rec['id']}")
        pdf_button(rec, key=f"pdf_test_{rec['id']}")


def page_history():
    st.title("Debugging History")
    st.caption("Stored only in this browser session (Streamlit session state). It is cleared when you close or refresh the page.")
    hist = st.session_state.history
    if not hist:
        st.info("No submissions yet. Analyze some code on the Debug Code page.")
        return
    if st.button("Clear history"):
        st.session_state.history = []
        st.session_state["debug_id"] = None
        st.rerun()
    for rec in reversed(hist):
        n_err = len([f for f in (rec["static_findings"] or []) if f["severity"] == "error"])
        label = f"#{rec['id']} | {rec['language']} | {rec['timestamp']} | {n_err} detected error(s)"
        with st.expander(label):
            show_code(rec["code"], rec["language"], "Submitted code")
            if rec["static_findings"] is None and not rec["ai"] and not rec["ai_error"]:
                st.info("Only optimization/test generation was run for this code.")
            else:
                render_debug_results(rec, "hist")


def page_about():
    st.title("About Project")
    st.markdown(f"""
**{config.APP_NAME}** - {config.APP_TAGLINE}.

It helps students *understand* programming errors: it detects problems, explains the root cause,
shows corrected code and gives tips to avoid the mistake next time.

**Pipeline:** Code input -> Static analysis -> Embedding (all-MiniLM-L6-v2) -> ChromaDB top-3 search ->
Groq LLM -> Structured response -> Dashboard -> PDF report.
""")
    st.dataframe(pd.DataFrame([
        ["Frontend", "Streamlit"], ["LLM", f"Groq API ({config.GROQ_MODEL})"],
        ["Vector DB", "ChromaDB (local)"], ["Embeddings", f"Sentence Transformers ({config.EMBEDDING_MODEL})"],
        ["Python analysis", "ast + compile()"], ["Highlighting", "Pygments"],
        ["Tables", "Pandas"], ["Reports", "ReportLab"]], columns=["Component", "Technology"]),
        hide_index=True)
    st.markdown("### Which features need a Groq API key?")
    st.markdown("- **No key needed:** static analysis, knowledge-base retrieval, debugging history, PDF export.\n"
                "- **Key needed:** AI debugging explanation, corrected code, optimization suggestions, test generation.")
    st.markdown("### Limitations")
    st.markdown("- Non-Python static checks are lightweight pattern rules (no real compiler) and may miss errors or give false positives.\n"
                "- AI output can be wrong; always run and verify the code.\n"
                "- Free-tier Groq rate limits apply. History is lost when the session ends.\n"
                "- PDF reports use Latin-1 fonts, so non-Latin characters appear as '?'.")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    init_state()
    with st.sidebar:
        st.markdown(f"## 🔍 {config.APP_NAME}")
        page = st.radio("Navigation", PAGES, label_visibility="collapsed", key="nav")
        st.divider()
        st.markdown("**Status**")
        st.markdown(("Groq key: " + badge("OK", "green")) if groq_client.is_configured()
                    else ("Groq key: " + badge("missing", "red")), unsafe_allow_html=True)
        st.markdown(f"Model: `{config.GROQ_MODEL}`")
        st.markdown(f"Knowledge docs: `{len(load_knowledge())}`")
        st.markdown(f"History items: `{len(st.session_state.history)}`")
    {"Home": page_home, "Debug Code": page_debug, "Code Optimization": page_optimize,
     "Test Case Generator": page_tests, "Debugging History": page_history, "About Project": page_about}[page]()


main()
