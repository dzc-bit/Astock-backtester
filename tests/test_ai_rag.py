from __future__ import annotations

from pathlib import Path

from astock_backtester.ai.context import ContextBudget
from astock_backtester.ai.rag.retriever import KnowledgeIndex, build_knowledge_tool


class CountingEmbedder:
    """Deterministic fake embeddings: vector = [len(text), first-char code]."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(len(text)), float(ord(text[0]))] if text else [0.0, 0.0] for text in texts]


def test_index_info_parses_packaged_corpus():
    embedder = CountingEmbedder()
    index = KnowledgeIndex(embedder=embedder, cache_dir=Path("unused"))
    info = index.info()
    assert info["documents"] >= 3
    assert info["chunks"] > info["documents"]


def test_query_builds_cache_and_reuses_embeddings(tmp_path):
    embedder = CountingEmbedder()
    index = KnowledgeIndex(embedder=embedder, cache_dir=tmp_path)
    hits = index.query("条件 DSL 模板", k=2)
    assert len(hits) == 2
    assert all(hit["source"].endswith(".md") for hit in hits)
    cache_files = list(tmp_path.glob("knowledge-embeddings-*.json"))
    assert len(cache_files) == 1
    corpus_calls = len(embedder.calls)
    assert corpus_calls == 2  # one build call + one query call

    reloaded = KnowledgeIndex(embedder=embedder, cache_dir=tmp_path)
    hits_again = reloaded.query("另一个问题", k=1)
    assert len(hits_again) == 1
    assert len(embedder.calls) == corpus_calls + 1  # corpus vectors came from cache


def test_knowledge_tool_roundtrip(tmp_path):
    embedder = CountingEmbedder()
    index = KnowledgeIndex(embedder=embedder, cache_dir=tmp_path)
    tool = build_knowledge_tool(index, ContextBudget())
    result = tool.executor({"question": "回测只认什么数据"})
    assert result["ok"] is True
    assert result["hits"]
    summary = tool.summarizer(result)
    assert "【" in summary
    missing = tool.executor({"question": ""})
    assert missing["ok"] is False
