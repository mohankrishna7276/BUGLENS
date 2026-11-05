"""Groq LLM integration. Never fabricates output: if the API cannot be used,
a GroqUnavailableError with a clear message is raised and the UI shows it."""
import json
import re

import config


class GroqUnavailableError(Exception):
    """Raised when the Groq API cannot be used (no key, no package, network/API error)."""


def is_configured():
    return bool(config.GROQ_API_KEY) and config.GROQ_API_KEY != "your_groq_api_key_here"


def _get_client():
    if not is_configured():
        raise GroqUnavailableError(
            "Groq API key not found. Copy .env.example to .env and set GROQ_API_KEY "
            "(free key: https://console.groq.com/keys), then restart the app.")
    try:
        from groq import Groq
    except ImportError as exc:
        raise GroqUnavailableError(
            "The 'groq' package is not installed. Run: pip install -r requirements.txt") from exc
    return Groq(api_key=config.GROQ_API_KEY)


def _parse_json(text):
    """Parse model output as JSON, tolerating ```json fences and extra text."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def chat_json(system_prompt, user_prompt):
    """Send a chat request and return the parsed JSON dict."""
    client = _get_client()
    try:
        resp = client.chat.completions.create(
            model=config.GROQ_MODEL,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_prompt}],
            temperature=config.GROQ_TEMPERATURE,
            max_tokens=config.GROQ_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
    except Exception as exc:
        msg = str(exc)
        if "429" in msg or "rate" in msg.lower():
            raise GroqUnavailableError(
                "Groq rate limit reached (free tier). Wait a minute and try again.") from exc
        if "401" in msg or "invalid api key" in msg.lower():
            raise GroqUnavailableError("Groq rejected the API key. Check GROQ_API_KEY in .env.") from exc
        raise GroqUnavailableError(f"Groq API request failed: {type(exc).__name__}: {msg}") from exc
    try:
        return _parse_json(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GroqUnavailableError(
            "Groq returned a response that was not valid JSON. Please try again.") from exc


def _truncate(code):
    if len(code) > config.MAX_CODE_CHARS:
        return code[:config.MAX_CODE_CHARS] + "\n... [truncated to fit model limits]"
    return code


DEBUG_SYSTEM = """You are BugLens AI, a patient programming tutor that helps students understand bugs.
Rules:
- Be accurate. If the code has no bug, say so; do NOT invent problems.
- 'Static analysis findings' are verified facts from tools. 'possible_bugs' are YOUR suggestions only.
- Use the 'Retrieved knowledge' only when relevant; never cite knowledge that was not provided.
- Reference real line numbers from the submitted code (1-based) or null if unknown.
- Explain simply, as to a beginner. Keep corrected_code complete and runnable.
Return ONLY a JSON object with exactly these keys:
{"summary": str,
 "errors": [{"line": int|null, "type": str, "description": str}],
 "possible_bugs": [{"line": int|null, "description": str}],
 "root_cause": str,
 "affected_section": str,
 "corrected_code": str,
 "explanation": str,
 "prevention_tips": [str]}"""


def debug_code(code, language, static_findings, chunks):
    """Ask Groq to analyse the code, grounded by static findings and retrieved context."""
    findings_txt = "\n".join(
        f"- line {f['line']}: [{f['severity']}] {f['message']}" for f in static_findings
    ) or "None detected."
    context_txt = "\n\n".join(
        f"[{i + 1}] {c['title']}: {c['text']}" for i, c in enumerate(chunks)
    ) or "Retrieval unavailable or no relevant context."
    numbered = "\n".join(f"{i + 1}: {l}" for i, l in enumerate(_truncate(code).splitlines()))
    user = (f"Language: {language}\n\nSubmitted code (with line numbers):\n{numbered}\n\n"
            f"Static analysis findings:\n{findings_txt}\n\nRetrieved knowledge:\n{context_txt}\n\n"
            "Analyse the code and respond with the JSON object.")
    data = chat_json(DEBUG_SYSTEM, user)
    # Normalise so the UI never crashes on missing keys
    return {
        "summary": data.get("summary", ""),
        "errors": data.get("errors") or [],
        "possible_bugs": data.get("possible_bugs") or [],
        "root_cause": data.get("root_cause", ""),
        "affected_section": data.get("affected_section", ""),
        "corrected_code": data.get("corrected_code", ""),
        "explanation": data.get("explanation", ""),
        "prevention_tips": data.get("prevention_tips") or [],
    }
