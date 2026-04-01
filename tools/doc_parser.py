#!/usr/bin/env python3
"""
文档解析器

支持输入：
- .md（Markdown）
- .txt（纯文本）
- .pdf（PDF 文档）
- 目录（批量解析）

支持输出：
- text（纯文本合并）
- records-json / records-jsonl（按文件或章节分段）
- rag-json / rag-jsonl（RAG 格式，按段落分块）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def parse_markdown(md_path: Path) -> Dict[str, Any]:
    """解析 Markdown 文件"""
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    
    # 提取标题和日期（如果有）
    title = md_path.stem
    date = None
    
    # 尝试提取 YAML front matter 中的日期
    yaml_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if yaml_match:
        front_matter = yaml_match.group(1)
        date_match = re.search(r"date:\s*(\d{4}-\d{2}-\d{2})", front_matter)
        if date_match:
            date = date_match.group(1)
        title_match = re.search(r"title:\s*(.+)", front_matter)
        if title_match:
            title = title_match.group(1).strip('"\'')
    
    # 尝试从文件名提取日期（格式：2024-01-01-title.md）
    if not date:
        date_match = re.match(r"^(\d{4}-\d{2}-\d{2})", md_path.stem)
        if date_match:
            date = date_match.group(1)
    
    # 尝试从文件修改时间获取日期
    if not date:
        mtime = md_path.stat().st_mtime
        date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    
    return {
        "type": "markdown",
        "path": str(md_path),
        "title": title,
        "date": date,
        "content": text,
    }


def parse_text(txt_path: Path) -> Dict[str, Any]:
    """解析纯文本文件"""
    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    
    title = txt_path.stem
    mtime = txt_path.stat().st_mtime
    date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    
    return {
        "type": "text",
        "path": str(txt_path),
        "title": title,
        "date": date,
        "content": text,
    }


def parse_pdf(pdf_path: Path) -> Dict[str, Any]:
    """解析 PDF 文件（需要 PyPDF2 或 pdfplumber）"""
    try:
        import PyPDF2
    except ImportError:
        raise RuntimeError(
            "PDF parsing requires PyPDF2. Install: pip install PyPDF2"
        )
    
    text_parts = []
    
    with open(pdf_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text_parts.append(page.extract_text())
    
    text = "\n".join(text_parts)
    title = pdf_path.stem
    mtime = pdf_path.stat().st_mtime
    date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    
    return {
        "type": "pdf",
        "path": str(pdf_path),
        "title": title,
        "date": date,
        "content": text,
    }


def parse_directory(dir_path: Path, extensions: List[str]) -> List[Dict[str, Any]]:
    """批量解析目录下的文档"""
    records = []
    
    for ext in extensions:
        for file_path in dir_path.rglob(f"*.{ext}"):
            try:
                if ext == "md":
                    record = parse_markdown(file_path)
                elif ext == "txt":
                    record = parse_text(file_path)
                elif ext == "pdf":
                    record = parse_pdf(file_path)
                else:
                    continue
                
                if record.get("content"):
                    records.append(record)
            except Exception as e:
                print(f"Warning: Failed to parse {file_path}: {e}")
    
    return records


def split_text_to_chunks(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """将长文本分块（按段落优先，再按字数）"""
    # 先按段落分割
    paragraphs = re.split(r"\n\s*\n", text)
    
    chunks = []
    current_chunk = []
    current_size = 0
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        para_size = len(para)
        
        if current_size + para_size > chunk_size and current_chunk:
            # 当前 chunk 已满，保存
            chunks.append("\n\n".join(current_chunk))
            # 保留最后一段作为重叠
            if overlap > 0 and current_chunk:
                current_chunk = [current_chunk[-1]]
                current_size = len(current_chunk[0])
            else:
                current_chunk = []
                current_size = 0
        
        current_chunk.append(para)
        current_size += para_size
    
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    
    return chunks


def records_to_text(records: List[Dict[str, Any]]) -> str:
    """将记录转换为纯文本"""
    lines = []
    for rec in records:
        lines.append(f"=== {rec.get('title', 'Untitled')} [{rec.get('date', 'Unknown')}] ===")
        lines.append("")
        lines.append(rec.get("content", ""))
        lines.append("")
    
    return "\n".join(lines)


def records_to_rag(
    records: List[Dict[str, Any]], 
    rag_source: str = "docs",
    chunk_size: int = 500,
    overlap: int = 50,
) -> List[Dict[str, Any]]:
    """将记录转换为 RAG 格式（分块）"""
    rag_docs = []
    
    for rec in records:
        content = rec.get("content", "")
        if not content:
            continue
        
        # 分块
        chunks = split_text_to_chunks(content, chunk_size, overlap)
        
        for i, chunk in enumerate(chunks):
            metadata = {
                "source": rag_source,
                "type": rec.get("type", "unknown"),
                "path": rec.get("path", ""),
                "title": rec.get("title", ""),
                "date": rec.get("date", ""),
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            
            rag_docs.append({
                "text": chunk,
                "metadata": metadata,
            })
    
    return rag_docs


def main() -> int:
    import sys
    
    parser = argparse.ArgumentParser(description="Parse documents (md/txt/pdf)")
    parser.add_argument("--file", help="Single file path")
    parser.add_argument("--dir", help="Directory path (for batch processing)")
    parser.add_argument("--ext", nargs="+", default=["md", "txt"], help="File extensions to parse")
    parser.add_argument("--format", default="text", choices=["text", "records-json", "records-jsonl", "rag-json", "rag-jsonl"])
    parser.add_argument("--rag-source", default="docs", help="Source label for RAG metadata")
    parser.add_argument("--chunk-size", type=int, default=500, help="Chunk size for RAG format")
    parser.add_argument("--overlap", type=int, default=50, help="Overlap size between chunks")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    
    args = parser.parse_args()
    
    # 解析文档
    records = []
    
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            return 1
        
        ext = file_path.suffix.lstrip(".")
        if ext == "md":
            records = [parse_markdown(file_path)]
        elif ext == "txt":
            records = [parse_text(file_path)]
        elif ext == "pdf":
            records = [parse_pdf(file_path)]
        else:
            print(f"Error: Unsupported file format: {ext}", file=sys.stderr)
            return 1
    
    elif args.dir:
        dir_path = Path(args.dir)
        if not dir_path.exists():
            print(f"Error: Directory not found: {dir_path}", file=sys.stderr)
            return 1
        
        records = parse_directory(dir_path, args.ext)
    
    else:
        print("Error: Must specify --file or --dir", file=sys.stderr)
        return 1
    
    if not records:
        print("Warning: No valid documents found", file=sys.stderr)
        return 0
    
    # 格式化输出
    if args.format == "text":
        output = records_to_text(records)
    elif args.format == "records-json":
        output = json.dumps({"records": records}, ensure_ascii=False, indent=2)
    elif args.format == "records-jsonl":
        output = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    elif args.format == "rag-json":
        rag_docs = records_to_rag(records, args.rag_source, args.chunk_size, args.overlap)
        output = json.dumps({"docs": rag_docs}, ensure_ascii=False, indent=2)
    elif args.format == "rag-jsonl":
        rag_docs = records_to_rag(records, args.rag_source, args.chunk_size, args.overlap)
        output = "\n".join(json.dumps(d, ensure_ascii=False) for d in rag_docs)
    else:
        output = records_to_text(records)
    
    # 写入输出
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Parsed {len(records)} documents -> {args.output}")
    else:
        print(output)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
