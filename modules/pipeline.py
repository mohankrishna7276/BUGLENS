"""End-to-end debugging pipeline:

Code -> Static analysis -> (embed query -> ChromaDB search -> top-3 chunks) -> Groq -> structured result
"""
from modules import analyzer, groq_client


def build_query(code, language, findings):
    """Retrieval query: error messages if any were found, else the start of the code."""
    if findings:
        return f"{language} " + " ".join(f["message"] for f in findings[:3])
    return f"{language} common mistakes: " + " ".join(code.split())[:300]


def run_pipeline(code, language, rag_engine=None):
    """Run the full pipeline. Returns a dict; never raises for expected failures.

    Keys: static_findings, retrieval, ai (dict|None), ai_error (str|None)
    """
    findings = analyzer.analyze(code, language)

    if rag_engine is None:
        retrieval = {"available": False, "reason": "RAG engine not initialised.", "chunks": []}
    else:
        retrieval = rag_engine.retrieve(build_query(code, language, findings), language)

    ai, ai_error = None, None
    try:
        ai = groq_client.debug_code(code, language, findings, retrieval["chunks"])
    except groq_client.GroqUnavailableError as exc:
        ai_error = str(exc)
    return {"static_findings": findings, "retrieval": retrieval, "ai": ai, "ai_error": ai_error}
