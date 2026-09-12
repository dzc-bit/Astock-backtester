"""Local knowledge retrieval: markdown corpus -> chunks -> embeddings -> cosine.

Chunking reuses ``langchain-text-splitters`` (MarkdownHeaderTextSplitter keeps
section headings as metadata).  Embeddings come from the configured
OpenAI-compatible provider and are cached on disk keyed by corpus hash, so the
corpus is embedded exactly once per model.  At this corpus scale (~dozens of
chunks) numpy cosine top-k is the honest choice; no vector database needed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np

from astock_backtester.ai.context import ContextBudget
from astock_backtester.ai.tools.registry import AiTool

Embedder = Callable[[list[str]], list[list[float]]]


def _corpus_dir() -> Path | None:
    direct = Path(__file__).resolve().parent / "corpus"
    if direct.is_dir():
        return direct
    try:
        packaged = resources.files("astock_backtester.ai.rag").joinpath("corpus")
        path = Path(str(packaged))
        if path.is_dir():
            return path
    except (ModuleNotFoundError, FileNotFoundError, NotImplementedError):
        return None
    return None


class KnowledgeIndex:
    def __init__(
        self,
        *,
        embedder: Embedder,
        cache_dir: Path,
        chunk_size: int = 500,
        chunk_overlap: int = 80,
    ) -> None:
        self._embedder = embedder
        self._cache_dir = Path(cache_dir)
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._chunks: list[dict[str, Any]] = []
        self._matrix: np.ndarray | None = None
        self._cache_key = ""

    # ---------------------------------------------------------------- build
    def _load_documents(self) -> list[dict[str, str]]:
        directory = _corpus_dir()
        if directory is None:
            return []
        documents: list[dict[str, str]] = []
        for path in sorted(directory.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if text.strip():
                documents.append({"source": path.name, "text": text})
        return documents

    def _chunk_document(self, text: str) -> list[dict[str, Any]]:
        from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

        header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")])
        sections = header_splitter.split_text(text)
        size_splitter = RecursiveCharacterTextSplitter(chunk_size=self._chunk_size, chunk_overlap=self._chunk_overlap)
        chunks: list[dict[str, Any]] = []
        for section in sections:
            heading = " / ".join(filter(None, [section.metadata.get("h1"), section.metadata.get("h2"), section.metadata.get("h3")]))
            for piece in size_splitter.split_text(section.page_content):
                if piece.strip():
                    chunks.append({"heading": heading, "text": piece.strip()})
        return chunks

    def _corpus_signature(self, documents: list[dict[str, str]]) -> str:
        digest = hashlib.sha256()
        for document in documents:
            digest.update(document["source"].encode("utf-8"))
            digest.update(document["text"].encode("utf-8"))
        digest.update(f"{self._chunk_size}:{self._chunk_overlap}".encode())
        return digest.hexdigest()[:16]

    def _ensure_built(self) -> None:
        if self._matrix is not None:
            return
        documents = self._load_documents()
        if not documents:
            return
        self._chunks = []
        for document in documents:
            for chunk in self._chunk_document(document["text"]):
                self._chunks.append({"source": document["source"], **chunk})
        if not self._chunks:
            return
        self._cache_key = self._corpus_signature(documents)
        vectors = self._load_cached_vectors() or self._embed_vectors()
        self._matrix = np.asarray(vectors, dtype=np.float32)

    def _cache_path(self) -> Path:
        return self._cache_dir / f"knowledge-embeddings-{self._cache_key}.json"

    def _load_cached_vectors(self) -> list[list[float]] | None:
        path = self._cache_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            vectors = payload["vectors"]
            if len(vectors) == len(self._chunks):
                return vectors
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return None
        return None

    def _embed_vectors(self) -> list[list[float]]:
        texts = [f"{chunk['heading']}\n{chunk['text']}" if chunk["heading"] else chunk["text"] for chunk in self._chunks]
        vectors = self._embedder(texts)
        if len(vectors) != len(self._chunks):
            raise ValueError("embedding 数量与分块数量不一致")
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path().write_text(json.dumps({"vectors": vectors}), encoding="utf-8")
        except OSError:
            pass
        return vectors

    # --------------------------------------------------------------- query
    def is_ready(self) -> bool:
        return self._matrix is not None

    def info(self) -> dict[str, Any]:
        documents = self._load_documents()
        chunk_count = sum(len(self._chunk_document(document["text"])) for document in documents)
        return {
            "documents": len(documents),
            "chunks": chunk_count,
            "ready": self._matrix is not None,
        }

    def query(self, question: str, k: int = 4) -> list[dict[str, Any]]:
        self._ensure_built()
        if self._matrix is None or not self._chunks:
            return []
        [query_vector] = self._embedder([question])
        query_array = np.asarray([query_vector], dtype=np.float32)
        query_array /= (np.linalg.norm(query_array, axis=1, keepdims=True) + 1e-9)
        matrix = self._matrix / (np.linalg.norm(self._matrix, axis=1, keepdims=True) + 1e-9)
        scores = (matrix @ query_array.T).ravel()
        top = np.argsort(-scores)[: max(1, min(k, len(self._chunks)))]
        return [
            {
                "source": self._chunks[index]["source"],
                "heading": self._chunks[index]["heading"],
                "text": self._chunks[index]["text"],
                "score": round(float(scores[index]), 4),
            }
            for index in top
        ]


def build_knowledge_tool(index: KnowledgeIndex, budget: ContextBudget) -> AiTool:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        question = str(args.get("question", "")).strip()
        if not question:
            return {"ok": False, "error": "question 不能为空"}
        try:
            hits = index.query(question, k=int(args.get("k", 4)))
        except Exception as exc:  # noqa: BLE001 - embedding provider errors become tool failures
            return {"ok": False, "error": f"知识检索失败：{exc}"}
        if not hits:
            return {"ok": False, "error": "知识库为空或未就绪（需配置 embedding_model）"}
        return {"ok": True, "hits": hits}

    def summarize(payload: dict[str, Any]) -> str:
        lines = []
        for hit in payload.get("hits", []):
            text = budget.digest(str(hit.get("text", "")))
            lines.append(f"【{hit.get('source')}·{hit.get('heading')}】{text}")
        return "\n".join(lines)

    return AiTool(
        name="retrieve_knowledge",
        description="检索本地知识库（投研方法论、条件 DSL 语法、数据字段规则），回答方法论类问题前先调用。",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "检索问题"},
                "k": {"type": "integer", "description": "返回条数，默认 4"},
            },
            "required": ["question"],
        },
        executor=execute,
        summarizer=summarize,
    )
