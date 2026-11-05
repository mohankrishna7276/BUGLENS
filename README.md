# 🔍 BugLens AI

**A Generative AI-Based Intelligent Code Debugging and Error Explanation System**

BugLens AI helps students *understand* programming errors. Paste Python, Java, C or JavaScript code and get detected errors, a plain-language root cause, corrected code, optimisation tips, generated test cases and a downloadable PDF report.

It combines **static analysis** (verified findings) + **RAG** (ChromaDB + Sentence Transformers) + **Groq LLM** (explanations), and always separates *detected* errors from *AI-suggested* possible bugs. If the AI is unavailable it shows a clear error - it never makes up results.

![Screenshot placeholder - Home](docs/screenshots/home.png)
![Screenshot placeholder - Debug Code results](docs/screenshots/debug.png)

> 📸 Take screenshots after your first run and save them in `docs/screenshots/` (create the folder) using the names above.

---

## Features

| Feature | Needs Groq key? |
|---|---|
| Code input: text area, file upload, example programs, 4 languages | No |
| Static error detection (Python `ast` + `compile()`; pattern checks for Java/C/JS) | **No** |
| RAG retrieval of top-3 knowledge chunks (ChromaDB + `all-MiniLM-L6-v2`) | No (needs the packages installed) |
| AI debugging: root cause, line, corrected code, explanation, prevention tips | **Yes** |
| Code optimisation (loop/recursion metrics are local; complexity and advice are AI) | AI part: **Yes** |
| Test case generator (normal / edge / boundary) | **Yes** |
| Session debugging history | No |
| PDF report download | No (contents depend on what was generated) |

## Pipeline

```
Code input → Language → Static analysis → Embedding → ChromaDB search (top 3)
          → Groq LLM → Structured response → Dashboard → PDF report
```
Diagrams: see [`docs/architecture.md`](docs/architecture.md).

## Project structure

```
BugLens-AI/
├── app.py                  # Streamlit dashboard (run this)
├── config.py               # settings, reads .env
├── requirements.txt
├── .env.example            # copy to .env and add your key
├── modules/
│   ├── analyzer.py         # static analysis
│   ├── rag_engine.py       # embeddings + ChromaDB
│   ├── groq_client.py      # Groq API + debug prompt
│   ├── pipeline.py         # analyzer → RAG → Groq
│   ├── code_optimizer.py
│   ├── test_generator.py
│   └── report_generator.py # PDF (ReportLab)
├── knowledge_base/programming_errors.json   # 37 documents
├── chroma_db/              # vector DB (created at first run, not committed)
├── reports/
├── tests/                  # sample cases + test runners
└── docs/                   # project_report.md, architecture.md, test_cases.md
```

---

## Setup on Windows

Requires **Python 3.10 - 3.12** (check with `python --version`) and an internet connection for the first install.

**1. Open a terminal in the project folder**
```bat
cd BugLens-AI
```

**2. Create a virtual environment**
```bat
python -m venv venv
```

**3. Activate it**

Command Prompt (cmd):
```bat
venv\Scripts\activate
```
PowerShell:
```powershell
venv\Scripts\Activate.ps1
```
*(If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or just use cmd.)*

**4. Install dependencies** (first time takes several minutes - PyTorch is large)
```bat
pip install -r requirements.txt
```

**5. Add your Groq API key**
1. Create a free key at <https://console.groq.com/keys>.
2. Copy the template: `copy .env.example .env`
3. Open `.env` in Notepad and replace `your_groq_api_key_here` with your key. Never share or commit this file.

**6. Run the app**
```bat
streamlit run app.py
```
Your browser opens at <http://localhost:8501>.

> **First run:** the first time retrieval is used, `all-MiniLM-L6-v2` (about 90 MB) is downloaded and the knowledge base is indexed into `chroma_db/`. Click **Build / check knowledge index** on the Home page to do this up front.

### macOS / Linux
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then edit .env
streamlit run app.py
```

---

## How to use

1. **Debug Code** → choose language → paste code (or load an example/upload a file) → **Analyze Code**.
2. Read **Detected by static analysis** (verified), then the **AI debugging analysis** (AI-generated - verify it), open *Retrieved knowledge* to see what context the AI received.
3. **Code Optimization** and **Test Case Generator** work on the same code.
4. **Debugging History** keeps this session's submissions. **Download PDF report** on any results page.

## Tests

```bat
python tests\run_static_tests.py            :: static analyzer on 17 sample cases (no key needed)
python tests\run_false_positive_probe.py    :: valid programs must produce no findings
python tests\run_ai_tests.py                :: full pipeline, needs GROQ_API_KEY
python tests\build_test_doc.py              :: rebuilds docs\test_cases.md from real results
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Groq API key not found` in the app | Make sure the file is named exactly `.env` (not `.env.txt`), contains `GROQ_API_KEY=...`, and restart Streamlit. |
| `Groq rejected the API key` (401) | Re-copy the key from the Groq console; no quotes or spaces. |
| `Groq rate limit reached` (429) | Free tier limits apply. Wait a minute and retry, or analyze shorter code. |
| Model not found / decommissioned | Groq changes its model list. Pick a current model from <https://console.groq.com/docs/models> and set `GROQ_MODEL=` in `.env`. |
| "Knowledge retrieval unavailable: ModuleNotFoundError…" | Run `pip install -r requirements.txt` inside the activated venv. The app still works without retrieval. |
| "Retrieval unavailable" with a download/connection error | The embedding model could not be downloaded; check internet/proxy and retry. |
| `pip install` fails building `chroma-hnswlib` | Install *Microsoft C++ Build Tools*, or upgrade pip (`python -m pip install -U pip`) and retry; use Python 3.10-3.12. |
| `streamlit` is not recognized | The venv is not activated - repeat step 3. |
| Port 8501 already in use | `streamlit run app.py --server.port 8502` |
| Knowledge base changed but results look old | Delete the `chroma_db` folder contents and restart; the index is rebuilt. |
| PDF shows `?` instead of some characters | The PDF uses Latin-1 fonts; non-Latin text (e.g. Telugu) cannot be shown. |

## Limitations

- Java/C/JavaScript checks are lightweight pattern rules - no compiler is run - so they can miss errors or give false alarms (the UI labels them as pattern checks).
- Logic errors are found only if the AI notices them; AI output can be wrong - always run and verify.
- Code you analyze is sent to Groq's API; do not paste confidential code.
- History is stored only in the browser session.

## Security

`.env` is listed in `.gitignore`. Never commit API keys, `chroma_db/` contents or generated reports.

## Documentation

- [`docs/project_report.md`](docs/project_report.md) - academic report (7 sections + references)
- [`docs/architecture.md`](docs/architecture.md) - diagrams and design decisions
- [`docs/test_cases.md`](docs/test_cases.md) - evaluation table with measured results
