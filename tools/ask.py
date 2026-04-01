#!/usr/bin/env python3
"""
基于 FAISS 索引的问答脚本（检索增强，支持 rerank 与可选 LLM 生成）。

流程：
1) 检索 top-k 相关 docs/chunks
2) 可选 CrossEncoder rerank
3) 提取高相关证据行
4) 规则答案或 LLM 生成答案
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def _vector_retrieve(
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
    question: str,
    hits: List[Dict[str, Any]],
    reranker_model: str,
    top_k: int,
) -> List[Dict[str, Any]]:
    if not hits:
        return []

    reranker = _get_reranker(reranker_model)
    pairs = [(question, str(h.get("text") or "")) for h in hits]
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


def retrieve(
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
    hits = _vector_retrieve(
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


STOPWORDS = {
    "什么", "怎么", "如何", "是不是", "是否", "吗", "呢", "吧", "啊", "呀", "了", "的", "得", "地",
    "这个", "那个", "一下", "一下子", "请问", "关于", "帮我", "请", "一个", "哪些", "多少", "为什么",
}


def _extract_terms(text: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fa5]+", text)
    terms: List[str] = []
    for t in tokens:
        t = t.strip().lower()
        if not t:
            continue
        if t in STOPWORDS:
            continue
        if len(t) == 1 and not re.match(r"[0-9a-zA-Z_]", t):
            continue
        terms.append(t)
    return terms


def _split_lines(text: str) -> List[str]:
    rows = [x.strip() for x in str(text or "").replace("\r", "").split("\n")]
    return [x for x in rows if x]


def _line_overlap_score(line: str, terms: List[str]) -> float:
    low = line.lower()
    score = 0.0
    for t in terms:
        if t in low:
            score += 1.0
    if ("?" in line or "？" in line) and any(x in low for x in ["吗", "是否", "请问", "怎么", "如何"]):
        score += 0.25
    return score


def _extract_evidence(
    question: str,
    hits: List[Dict[str, Any]],
    max_evidence: int,
) -> List[Dict[str, Any]]:
    terms = _extract_terms(question)
    scored: List[Dict[str, Any]] = []

    for hit in hits:
        base = float(hit.get("score", 0.0))
        for line in _split_lines(hit.get("text", "")):
            line_score = _line_overlap_score(line, terms)
            total = base + 2.0 * line_score
            if line_score <= 0 and not terms:
                total = base
            if line_score <= 0 and terms:
                continue

            scored.append(
                {
                    "line": line,
                    "score": float(total),
                    "retrieval_score": base,
                    "rank": hit.get("rank"),
                    "metadata": hit.get("metadata", {}),
                }
            )

    if not scored:
        for hit in hits[:max_evidence]:
            text = str(hit.get("text") or "").strip()
            if not text:
                continue
            first = _split_lines(text)
            if not first:
                continue
            scored.append(
                {
                    "line": first[0],
                    "score": float(hit.get("score", 0.0)),
                    "retrieval_score": float(hit.get("score", 0.0)),
                    "rank": hit.get("rank"),
                    "metadata": hit.get("metadata", {}),
                }
            )

    scored.sort(key=lambda x: x["score"], reverse=True)

    out: List[Dict[str, Any]] = []
    seen = set()
    for item in scored:
        key = item["line"]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max_evidence:
            break
    return out


def _synthesize_answer(question: str, evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return "没有检索到足够相关证据，暂时无法给出可靠答案。"

    top_lines = [e["line"] for e in evidence[:3]]
    if len(top_lines) == 1:
        return f"根据检索证据，答案最可能是：{top_lines[0]}"

    joined = "；".join(top_lines)
    return f"基于检索到的高相关片段，综合答案是：{joined}"


def _build_context(evidence: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for i, e in enumerate(evidence, start=1):
        md = e.get("metadata") if isinstance(e.get("metadata"), dict) else {}
        session = md.get("session", "")
        chunk_id = md.get("chunk_id", "")
        lines.append(f"[{i}] {e.get('line', '')} (session={session}, chunk={chunk_id})")
    return "\n".join(lines)


def _call_openai_compatible(
    question: str,
    evidence: List[Dict[str, Any]],
    model: str,
    base_url: str,
    api_key: str,
    temperature: float,
    timeout: int,
) -> Optional[str]:
    context = _build_context(evidence)
    if not context:
        return None

    prompt = (
        "你是一个严谨的问答助手。请仅基于提供的聊天证据回答，不要编造。"
        "若证据不足，请明确说明。\n\n"
        f"证据:\n{context}\n\n"
        f"问题: {question}\n"
        "请给出简洁答案。"
    )

    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = endpoint + "/chat/completions"

    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": "你是一个基于证据回答的助手。"},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError:
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    msg = first.get("message")
    if not isinstance(msg, dict):
        return None
    content = str(msg.get("content") or "").strip()
    return content or None


def ask(
    question: str,
    index_dir: Path,
    top_k: int,
    max_evidence: int,
    model_name: str,
    metric: str,
    candidate_k: int,
    nprobe: int,
    use_cache: bool,
    rerank: bool,
    reranker_model: str,
    llm_enabled: bool,
    llm_model: str,
    llm_base_url: str,
    llm_api_key: str,
    llm_temperature: float,
    llm_timeout: int,
) -> Dict[str, Any]:
    hits = retrieve(
        query=question,
        index_dir=index_dir,
        top_k=top_k,
        model_name=model_name,
        metric=metric,
        candidate_k=candidate_k,
        nprobe=nprobe,
        use_cache=use_cache,
        rerank=rerank,
        reranker_model=reranker_model,
    )
    evidence = _extract_evidence(question, hits, max_evidence=max_evidence)

    llm_answer: Optional[str] = None
    llm_error = ""
    if llm_enabled:
        llm_answer = _call_openai_compatible(
            question=question,
            evidence=evidence,
            model=llm_model,
            base_url=llm_base_url,
            api_key=llm_api_key,
            temperature=llm_temperature,
            timeout=llm_timeout,
        )
        if not llm_answer:
            llm_error = "llm_unavailable_or_empty"

    answer = llm_answer or _synthesize_answer(question, evidence)

    return {
        "question": question,
        "answer": answer,
        "evidence": evidence,
        "retrieved": hits,
        "generation": {
            "mode": "llm" if llm_answer else "rules",
            "llm_enabled": llm_enabled,
            "llm_error": llm_error,
        },
    }


def _format_text_output(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"问题: {result.get('question', '')}")
    lines.append(f"答案: {result.get('answer', '')}")

    generation = result.get("generation") if isinstance(result.get("generation"), dict) else {}
    mode = generation.get("mode", "")
    llm_error = generation.get("llm_error", "")
    lines.append(f"生成模式: {mode}")
    if llm_error:
        lines.append(f"LLM状态: {llm_error}")

    lines.append("")
    lines.append("证据:")

    evidence = result.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        lines.append("- (none)")
        return "\n".join(lines)

    for i, e in enumerate(evidence, start=1):
        md = e.get("metadata") if isinstance(e.get("metadata"), dict) else {}
        session = md.get("session", "")
        chunk = md.get("chunk_id", "")
        lines.append(
            f"{i}. [score={float(e.get('score', 0.0)):.4f}] {e.get('line', '')} (session={session}, chunk={chunk})"
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask question over FAISS index")
    parser.add_argument("--question", required=True, help="Question text")
    parser.add_argument("--index-dir", required=True, help="Directory containing index.faiss/docs.jsonl")
    parser.add_argument("--top-k", type=int, default=8, help="Top K retrieval results")
    parser.add_argument("--candidate-k", type=int, default=50, help="Initial retrieval size before rerank")
    parser.add_argument("--max-evidence", type=int, default=5, help="Max evidence lines in final answer")
    parser.add_argument("--model", help="Embedding model override")
    parser.add_argument("--metric", choices=["cosine", "l2"], help="Metric override")
    parser.add_argument("--nprobe", type=int, help="IVF nprobe override")
    parser.add_argument(
        "--rerank",
        action=argparse.BooleanOptionalAction,
        default=True,
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
        help="Interactive mode: multiple questions in one process",
    )

    parser.add_argument(
        "--use-llm",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use OpenAI-compatible LLM for final answer generation",
    )
    parser.add_argument("--llm-model", default="gpt-4o-mini", help="LLM model name")
    parser.add_argument(
        "--llm-base-url",
        default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        help="OpenAI-compatible base url (default from OPENAI_BASE_URL)",
    )
    parser.add_argument(
        "--llm-api-key",
        default=os.environ.get("OPENAI_API_KEY", ""),
        help="API key (default from OPENAI_API_KEY)",
    )
    parser.add_argument("--llm-temperature", type=float, default=0.2, help="LLM sampling temperature")
    parser.add_argument("--llm-timeout", type=int, default=60, help="LLM request timeout seconds")

    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--output", help="Optional output file")
    args = parser.parse_args()

    index_dir = Path(args.index_dir)
    if not index_dir.exists():
        raise FileNotFoundError(f"index dir not found: {index_dir}")

    manifest = _load_manifest(index_dir, use_cache=args.cache)
    model_name = args.model or str(manifest.get("model") or "BAAI/bge-small-zh-v1.5")
    metric = args.metric or str(manifest.get("metric") or "cosine")
    nprobe = args.nprobe if args.nprobe is not None else int(manifest.get("nprobe") or 0)

    if args.use_llm and not args.llm_api_key:
        print("warning: --use-llm enabled but no API key provided, fallback may occur", file=sys.stderr)

    def run_question(q: str) -> str:
        result = ask(
            question=q,
            index_dir=index_dir,
            top_k=args.top_k,
            max_evidence=args.max_evidence,
            model_name=model_name,
            metric=metric,
            candidate_k=args.candidate_k,
            nprobe=nprobe,
            use_cache=args.cache,
            rerank=args.rerank,
            reranker_model=args.reranker_model,
            llm_enabled=args.use_llm,
            llm_model=args.llm_model,
            llm_base_url=args.llm_base_url,
            llm_api_key=args.llm_api_key,
            llm_temperature=args.llm_temperature,
            llm_timeout=args.llm_timeout,
        )
        return json.dumps(result, ensure_ascii=False, indent=2) if args.json else _format_text_output(result)

    if args.interactive:
        if args.output:
            print("warning: --output is ignored in interactive mode")
        print("interactive mode enabled. input empty line to exit.")

        q = args.question
        while True:
            question = str(q).strip()
            if not question:
                break
            print(run_question(question))
            print("---")
            q = input("question> ")
    else:
        out = run_question(args.question)
        if args.output:
            Path(args.output).write_text(out, encoding="utf-8")
            print(f"written={args.output}")
        else:
            print(out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
