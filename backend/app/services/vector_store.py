import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.services.data_loader import load_adverse_media, load_watchlist

VECTOR_DIR = Path(__file__).resolve().parents[2] / "vector_db"
INDEX_FILE = VECTOR_DIR / "tfidf_index.pkl"


class VectorStore:
    """Lightweight TF-IDF vector database for sanctions, PEP, and adverse media search."""

    def __init__(self):
        self._ids: list[str] = []
        self._documents: list[str] = []
        self._metadatas: list[dict] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None
        self._loaded = False

    def seed_if_empty(self) -> None:
        if self._loaded:
            return

        if INDEX_FILE.exists():
            self._load_index()
            return

        watchlist = load_watchlist()
        media = load_adverse_media()

        for entry in watchlist:
            doc = (
                f"{entry['name']} {' '.join(entry.get('aliases', []))} "
                f"{entry.get('dob', '')} {entry.get('nationality', '')} "
                f"{entry['type']} {entry.get('reason', '')}"
            )
            self._ids.append(entry["id"])
            self._documents.append(doc)
            self._metadatas.append(
                {
                    "entity_type": entry["type"],
                    "name": entry["name"],
                    "payload": json.dumps(entry),
                }
            )

        for article in media:
            doc = (
                f"{article['subject']} {' '.join(article.get('aliases', []))} "
                f"{article['title']} {article.get('severity', '')} "
                f"{' '.join(article.get('categories', []))} {article.get('summary', '')}"
            )
            self._ids.append(article["id"])
            self._documents.append(doc)
            self._metadatas.append(
                {
                    "entity_type": "adverse_media",
                    "name": article["subject"],
                    "payload": json.dumps(article),
                }
            )

        self._build_index()
        self._save_index()
        self._loaded = True

    def _build_index(self) -> None:
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
        self._matrix = self._vectorizer.fit_transform(self._documents)
        self._loaded = True

    def _save_index(self) -> None:
        VECTOR_DIR.mkdir(parents=True, exist_ok=True)
        with open(INDEX_FILE, "wb") as f:
            pickle.dump(
                {
                    "ids": self._ids,
                    "documents": self._documents,
                    "metadatas": self._metadatas,
                    "vectorizer": self._vectorizer,
                    "matrix": self._matrix,
                },
                f,
            )

    def _load_index(self) -> None:
        with open(INDEX_FILE, "rb") as f:
            data = pickle.load(f)
        self._ids = data["ids"]
        self._documents = data["documents"]
        self._metadatas = data["metadatas"]
        self._vectorizer = data["vectorizer"]
        self._matrix = data["matrix"]
        self._loaded = True

    def search(self, query: str, n_results: int = 5, entity_type: str | None = None) -> list[dict]:
        self.seed_if_empty()
        assert self._vectorizer is not None and self._matrix is not None

        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._matrix).flatten()

        indices = np.argsort(scores)[::-1]
        hits: list[dict] = []

        for idx in indices:
            if len(hits) >= n_results:
                break
            meta = self._metadatas[idx]
            if entity_type and meta.get("entity_type") != entity_type:
                continue
            similarity = float(scores[idx])
            if similarity < 0.01:
                continue
            payload = json.loads(meta.get("payload", "{}"))
            hits.append(
                {
                    "id": self._ids[idx],
                    "entity_type": meta.get("entity_type", ""),
                    "similarity": round(similarity, 4),
                    "document": self._documents[idx],
                    "payload": payload,
                }
            )
        return hits


vector_store = VectorStore()
