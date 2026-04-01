#!/usr/bin/env python3
"""
FAISS 检索脚本。

输入：
- query 文本
- build_index.py 生成的索引目录（index.faiss + docs.jsonl + manifest.json）

输出：
- top-k 检索结果（json 或可读文本）
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

_MODEL_CACHE: Dict[str, Any] = {}
_RERANKER_CACHE: Dict[str, Any] = {}
_DOCS_CACHE: Dict[Tuple[str, int, int], List[Dict[str, Any]]] = {}
_MANIFEST_CACHE: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
_INDEX_CACHE: Dict[Tuple[str, int, int], Any] = {}


def _import_deps():
    try:
        import numpy as np
        import faiss
        from sentence_transformers import CrossEncoder, SentenceTransformer
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "missing dependencies. install: numpy faiss-cpu sentence-transformers"
        ) from exc
    return np, faiss, SentenceTransformer, CrossEncoder


def _file_sig(path: Path) -> Tuple[str, int, int]:
    st = path.stat()
    return (str(path), int(st.st_mtime_ns), int(st.st_size))


def _get_model(model_name: str):
    _, _, SentenceTransformer, _ = _import_deps()
    if model_name not in _MODEL_CACHE:
        _MODEL_CACHE[model_name] = SentenceTransformer(model_name)
    return _MODEL_CACHE[model_name]


def _get_reranker(model_name: str):
    _, _, _, CrossEncoder = _import_deps()
    if model_name not in _RERANKER_CACHE:
        _RERANKER_CACHE[model_name] = CrossEncoder(model_name)
    return _RERANKER_CACHE[model_name]


def _load_manifest(index_dir: Path, use_cache: bool = True) -> Dict[str, Any]:
    path = index_dir / "manifest.json"
    if not path.exists():
        return {}

    sig = _file_sig(path)
    if use_cache and sig in _MANIFEST_CACHE:
        return _MANIFEST_CACHE[sig]

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        manifest = {}

    if use_cache:
        _MANIFEST_CACHE[sig] = manifest
    return manifest


def _load_docs(index_dir: Path, use_cache: bool = True) -> List[Dict[str, Any]]:
    docs_path = index_dir / "docs.jsonl"
    if not docs_path.exists():
        raise FileNotFoundError(f"docs file not found: {docs_path}")

    sig = _file_sig(docs_path)
    if use_cache and sig in _DOCS_CACHE:
        return _DOCS_CACHE[sig]

    docs: List[Dict[str, Any]] = []
    for raw in docs_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            docs.append(item)

    if use_cache:
        _DOCS_CACHE[sig] = docs
    return docs


def _load_index(index_dir: Path, use_cache: bool = True):
    _, faiss, _, _ = _import_deps()

    index_path = index_dir / "index.faiss"
    if not index_path.exists():
        raise FileNotFoundError(f"index file not found: {index_path}")

    sig = _file_sig(index_path)
    if use_cache and sig in _INDEX_CACHE:
        return _INDEX_CACHE[sig]

    index = faiss.read_index(str(index_path))
    if use_cache:
        _INDEX_CACHE[sig] = index
    return index


def _embed_query(query: str, model_name: str, metric: str):
    np, _, _, _ = _import_deps()
    model = _get_model(model_name)
    vec = model.encode([query], normalize_embeddings=(metric == "cosine"))
    vec = np.asarray(vec, dtype="float32")
    if vec.ndim != 2 or vec.shape[0] != 1:
        raise ValueError("failed to embed query")
    return vec


def _vector_search(
    query: str,
    index_dir: Path,
    top_k: int,
    model_name: str,
    metric: str,
    candidate_k: int,
    nprobe: int,
    use_cache: bool,
) -> List[Dict[str, Any]]:
    docs = _load_docs(index_dir, use_cache=use_cache)
    index = _load_index(index_dir, use_cache=use_cache)

    if hasattr(index, "nprobe") and nprobe > 0:
        index.nprobe = int(nprobe)

    qv = _embed_query(query, model_name=model_name, metric=metric)
    fetch_k = max(top_k, candidate_k)
    k = max(1, min(fetch_k, max(1, int(index.ntotal))))
    scores, indices = index.search(qv, k)

    out: List[Dict[str, Any]] = []
    for rank, (score, idx) in enumerate(zip(scores[0], indices[0]), start=1):
        if idx < 0 or idx >= len(docs):
            continue
        item = docs[idx]
        out.append(
            {
                "rank": rank,
                "vector_score": float(score),
                "score": float(score),
                "id": item.get("id", idx),
                "text": item.get("text", ""),
                "metadata": item.get("metadata", {}),
            }
        )

    return out


def _apply_rerank(
    query: str,
    hits: List[Dict[str, Any]],
    reranker_model: str,
    top_k: int,
) -> List[Dict[str, Any]]:
    if not hits:
        return []

    reranker = _get_reranker(reranker_model)
    pairs = [(query, str(h.get("text") or "")) for h in hits]
    scores = reranker.predict(pairs)

    merged: List[Dict[str, Any]] = []
    for hit, sc in zip(hits, scores):
        item = dict(hit)
        item["rerank_score"] = float(sc)
        item["score"] = float(sc)
        merged.append(item)

    merged.sort(key=lambda x: x["rerank_score"], reverse=True)

    for i, item in enumerate(merged, start=1):
        item["rank"] = i

    return merged[:top_k]


def search(
    query: str,
    index_dir: Path,
    top_k: int,
    model_name: str,
    metric: str,
    candidate_k: int,
    nprobe: int,
    use_cache: bool,
    rerank: bool,
    reranker_model: str,
) -> List[Dict[str, Any]]:
    hits = _vector_search(
        query=query,
        index_dir=index_dir,
        top_k=top_k,
        model_name=model_name,
        metric=metric,
        candidate_k=candidate_k,
        nprobe=nprobe,
        use_cache=use_cache,
    )

    if rerank:
        return _apply_rerank(query, hits, reranker_model=reranker_model, top_k=top_k)

    return hits[:top_k]


def _format_text_results(results: List[Dict[str, Any]], metric: str, rerank: bool) -> str:
    if not results:
        return "no results"

    lines: List[str] = []
    lines.append(f"results={len(results)} metric={metric} rerank={str(rerank).lower()}")
    for r in results:
        md = r.get("metadata") if isinstance(r.get("metadata"), dict) else {}
        session = md.get("session", "")
        chunk_id = md.get("chunk_id", "")

        if rerank:
            score_label = "rerank_score"
            score = float(r.get("rerank_score", r.get("score", 0.0)))
        else:
            score_label = "similarity" if metric == "cosine" else "distance"
            score = float(r.get("vector_score", r.get("score", 0.0)))

        lines.append(
            f"\n#{r.get('rank')} {score_label}={score:.6f} session={session} chunk={chunk_id}"
        )
        text = str(r.get("text") or "").strip().replace("\r", "")
        if len(text) > 300:
            text = text[:300] + " ..."
        lines.append(text)

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Search related docs/chunks from FAISS index")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--index-dir", required=True, help="Directory containing index.faiss and docs.jsonl")
    parser.add_argument("--top-k", type=int, default=5, help="Top K final results")
    parser.add_argument("--candidate-k", type=int, default=50, help="Initial retrieval size before rerank")
    parser.add_argument("--model", help="Embedding model override")
    parser.add_argument("--metric", choices=["cosine", "l2"], help="Metric override")
    parser.add_argument("--nprobe", type=int, help="IVF nprobe override")
    parser.add_argument(
        "--rerank",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable CrossEncoder rerank",
    )
    parser.add_argument("--reranker-model", default="BAAI/bge-reranker-base", help="CrossEncoder model name")
    parser.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable in-process cache for model/index/docs",
    )
    parser.add_argument(
        "--interactive",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Interactive mode: multiple queries in one process",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--output", help="Optional output file path")
    args = parser.parse_args()

    index_dir = Path(args.index_dir)
    if not index_dir.exists():
        raise FileNotFoundError(f"index dir not found: {index_dir}")

    manifest = _load_manifest(index_dir, use_cache=args.cache)
    model_name = args.model or str(manifest.get("model") or "BAAI/bge-small-zh-v1.5")
    metric = args.metric or str(manifest.get("metric") or "cosine")
    nprobe = args.nprobe if args.nprobe is not None else int(manifest.get("nprobe") or 0)

    def run_query(q: str) -> str:
        results = search(
            query=q,
            index_dir=index_dir,
            top_k=args.top_k,
            model_name=model_name,
            metric=metric,
            candidate_k=args.candidate_k,
            nprobe=nprobe,
            use_cache=args.cache,
            rerank=args.rerank,
            reranker_model=args.reranker_model,
        )

        if args.json:
            return json.dumps(
                {
                    "query": q,
                    "top_k": args.top_k,
                    "candidate_k": args.candidate_k,
                    "model": model_name,
                    "metric": metric,
                    "nprobe": nprobe,
                    "rerank": args.rerank,
                    "reranker_model": args.reranker_model if args.rerank else "",
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        return _format_text_results(results, metric=metric, rerank=args.rerank)

    if args.interactive:
        if args.output:
            print("warning: --output is ignored in interactive mode")
        print("interactive mode enabled. input empty line to exit.")

        q = args.query
        while True:
            query = str(q).strip()
            if not query:
                break
            print(run_query(query))
            print("---")
            q = input("query> ")
    else:
        out = run_query(args.query)
        if args.output:
            Path(args.output).write_text(out, encoding="utf-8")
            print(f"written={args.output}")
        else:
            print(out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
