#!/usr/bin/env python3
"""
将 rag-json / rag-jsonl 向量化并写入 FAISS。

输入格式支持：
1) rag-json: {"docs": [{"text": "...", "metadata": {...}}, ...]}
2) rag-json: [{"text": "...", "metadata": {...}}, ...]
3) rag-jsonl: 每行一个 {"text": "...", "metadata": {...}}

输出文件：
- index.faiss: FAISS 索引
- docs.jsonl: 行号与原始 metadata 映射（召回后可回查）
- manifest.json: 索引构建参数
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _safe_nlist(total: int, nlist: int) -> int:
    if total <= 0:
        return 1
    return max(1, min(int(nlist), int(total)))


def _load_docs(in_path: Path) -> List[Dict[str, Any]]:
    suffix = in_path.suffix.lower()
    text = in_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []

    if suffix == ".jsonl":
        docs: List[Dict[str, Any]] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                docs.append(item)
        return docs

    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        return [x for x in data["docs"] if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _normalize_docs(raw_docs: List[Dict[str, Any]]) -> Tuple[List[str], List[Dict[str, Any]]]:
    texts: List[str] = []
    payloads: List[Dict[str, Any]] = []

    for i, doc in enumerate(raw_docs):
        text = str(doc.get("text") or "").strip()
        if not text:
            continue

        metadata = doc.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        texts.append(text)
        payloads.append(
            {
                "id": len(payloads),
                "source_idx": i,
                "text": text,
                "metadata": metadata,
            }
        )

    return texts, payloads


def _import_vector_backend():
    try:
        import numpy as np
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("missing dependency: numpy") from exc

    try:
        import faiss
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("missing dependency: faiss-cpu") from exc

    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("missing dependency: sentence-transformers") from exc

    return np, faiss, SentenceTransformer


def _build_faiss(
    texts: List[str],
    model_name: str,
    batch_size: int,
    metric: str,
    index_type: str,
    nlist: int,
    nprobe: int,
) -> Tuple[Any, int, Dict[str, Any]]:
    np, faiss, SentenceTransformer = _import_vector_backend()

    model = SentenceTransformer(model_name)
    normalize_embeddings = metric == "cosine"
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=normalize_embeddings,
    )
    vectors = np.asarray(vectors, dtype="float32")
    if vectors.ndim != 2 or vectors.shape[0] == 0:
        raise ValueError("embedding failed: empty vectors")

    total = int(vectors.shape[0])
    dim = int(vectors.shape[1])

    if metric == "cosine":
        quantizer = faiss.IndexFlatIP(dim)
        metric_type = faiss.METRIC_INNER_PRODUCT
    else:
        quantizer = faiss.IndexFlatL2(dim)
        metric_type = faiss.METRIC_L2

    actual_nlist = _safe_nlist(total, nlist)
    actual_nprobe = max(1, min(int(nprobe), actual_nlist))

    if index_type == "ivf":
        index = faiss.IndexIVFFlat(quantizer, dim, actual_nlist, metric_type)
        index.train(vectors)
        index.add(vectors)
        index.nprobe = actual_nprobe
    else:
        index = quantizer
        index.add(vectors)

    index_meta = {
        "index_type": index_type,
        "nlist": actual_nlist if index_type == "ivf" else None,
        "nprobe": actual_nprobe if index_type == "ivf" else None,
    }

    return index, dim, index_meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Build FAISS index from rag-json/rag-jsonl")
    parser.add_argument("--input", required=True, help="Path to rag-json or rag-jsonl")
    parser.add_argument("--out-dir", required=True, help="Output directory for index and metadata")
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5", help="SentenceTransformer model name")
    parser.add_argument("--batch-size", type=int, default=64, help="Embedding batch size")
    parser.add_argument("--metric", choices=["cosine", "l2"], default="cosine", help="Vector similarity metric")
    parser.add_argument(
        "--index-type",
        choices=["flat", "ivf"],
        default="ivf",
        help="FAISS index type. flat=精确检索, ivf=近似检索",
    )
    parser.add_argument("--nlist", type=int, default=100, help="IVF centroids (used when --index-type ivf)")
    parser.add_argument("--nprobe", type=int, default=10, help="IVF probes at search time")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise FileNotFoundError(f"input not found: {in_path}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_docs = _load_docs(in_path)
    texts, payloads = _normalize_docs(raw_docs)
    if not texts:
        raise ValueError("no valid docs found in input")

    index, dim, index_meta = _build_faiss(
        texts,
        model_name=args.model,
        batch_size=args.batch_size,
        metric=args.metric,
        index_type=args.index_type,
        nlist=args.nlist,
        nprobe=args.nprobe,
    )

    _, faiss, _ = _import_vector_backend()
    index_path = out_dir / "index.faiss"
    docs_path = out_dir / "docs.jsonl"
    manifest_path = out_dir / "manifest.json"

    faiss.write_index(index, str(index_path))

    docs_text = "\n".join(json.dumps(item, ensure_ascii=False) for item in payloads)
    docs_path.write_text(docs_text, encoding="utf-8")

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input": str(in_path),
        "count": len(payloads),
        "dim": dim,
        "model": args.model,
        "metric": args.metric,
        "index_type": index_meta["index_type"],
        "nlist": index_meta["nlist"],
        "nprobe": index_meta["nprobe"],
        "files": {
            "index": str(index_path),
            "docs": str(docs_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"indexed={len(payloads)} dim={dim} metric={args.metric} "
        f"index_type={index_meta['index_type']} nlist={index_meta['nlist']} nprobe={index_meta['nprobe']} "
        f"index={index_path} docs={docs_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
