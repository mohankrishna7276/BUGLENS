"""RAG engine: local embeddings (Sentence Transformers) + ChromaDB vector search.

Heavy libraries are imported lazily so the rest of the app still works if they
are missing or the knowledge base is empty. In that case `retrieve()` returns
available=False with a clear reason; it never fabricates context.
"""
import json
import config


def load_knowledge(path=None):
    """Load knowledge documents from JSON. Returns [] if the file is missing/invalid."""
    path = path or config.KNOWLEDGE_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [d for d in data if d.get("content")]
    except (OSError, json.JSONDecodeError):
        return []


class RAGEngine:
    def __init__(self):
        self._model = None
        self._collection = None
        self.error = None  # last initialisation error (string) or None

    # ---------- setup ----------
    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy import
            self._model = SentenceTransformer(config.EMBEDDING_MODEL)
        return self._model

    def _embed(self, texts):
        return self._get_model().encode(texts, normalize_embeddings=True).tolist()

    def _get_collection(self):
        if self._collection is None:
            import chromadb  # lazy import
            from chromadb.config import Settings
            config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(
                path=str(config.CHROMA_DIR),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name=config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    def build_index(self, force=False):
        """Embed the knowledge documents and store them in ChromaDB.

        Returns (ok: bool, message: str).
        """
        docs = load_knowledge()
        if not docs:
            return False, "Knowledge base file is empty or missing."
        try:
            col = self._get_collection()
            if not force and col.count() == len(docs):
                return True, f"Index ready ({col.count()} documents)."
            texts = [f"{d['title']}. {d['content']}" for d in docs]
            col.upsert(
                ids=[d["id"] for d in docs],
                documents=texts,
                embeddings=self._embed(texts),
                metadatas=[{"language": d["language"], "category": d["category"],
                            "title": d["title"]} for d in docs],
            )
            self.error = None
            return True, f"Indexed {len(docs)} knowledge documents."
        except Exception as exc:  # missing package, model download failure, etc.
            self.error = f"{type(exc).__name__}: {exc}"
            return False, f"Retrieval unavailable: {self.error}"

    # ---------- status / retrieval ----------
    def status(self):
        """Return a dict describing retrieval availability (used by the UI)."""
        docs = load_knowledge()
        if not docs:
            return {"available": False, "reason": "Knowledge base is empty.", "count": 0}
        ok, msg = self.build_index()
        return {"available": ok, "reason": msg, "count": len(docs)}

    def retrieve(self, query, language=None, k=None):
        """Return {"available", "reason", "chunks"}; chunks = top-k relevant documents."""
        k = k or config.TOP_K
        ok, msg = self.build_index()
        if not ok:
            return {"available": False, "reason": msg, "chunks": []}
        try:
            col = self._get_collection()
            where = None
            if language:
                where = {"language": {"$in": [language, "General"]}}
            res = col.query(
                query_embeddings=self._embed([query]),
                n_results=min(k, col.count()),
                where=where,
            )
            chunks = []
            for i, doc in enumerate(res["documents"][0]):
                meta = res["metadatas"][0][i]
                dist = res["distances"][0][i]
                chunks.append({
                    "title": meta.get("title", ""),
                    "category": meta.get("category", ""),
                    "language": meta.get("language", ""),
                    "similarity": round(1 - dist, 3),  # cosine similarity
                    "text": doc,
                })
            return {"available": True, "reason": "OK", "chunks": chunks}
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return {"available": False, "reason": f"Retrieval failed: {self.error}", "chunks": []}
