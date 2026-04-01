#!/usr/bin/env python3
"""
邮件解析器

支持输入：
- .eml（单个邮件文件）
- .mbox（邮箱导出文件）
- Gmail takeout（JSON 格式）

支持输出：
- text（纯文本）
- records-json / records-jsonl（结构化消息）
- rag-json / rag-jsonl（RAG 格式）
"""

from __future__ import annotations

import argparse
import email
import email.message
import json
import mailbox
import re
import sys
from datetime import datetime
from email.header import decode_header
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def decode_email_header(header: Optional[str]) -> str:
    """解码邮件头部（处理编码）"""
    if not header:
        return ""
    
    decoded_parts = []
    for part, encoding in decode_header(header):
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(encoding or "utf-8", errors="ignore"))
        else:
            decoded_parts.append(str(part))
    
    return " ".join(decoded_parts)


def extract_email_body(msg: email.message.Message) -> str:
    """提取邮件正文"""
    body = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body += payload.decode(charset, errors="ignore")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="ignore")
    
    return body.strip()


def clean_email_body(body: str) -> str:
    """清理邮件正文（去除引用、签名等）"""
    lines = body.split("\n")
    cleaned_lines = []
    
    for line in lines:
        # 跳过引用行
        if line.startswith(">"):
            continue
        # 跳过常见签名分隔符
        if re.match(r"^--\s*$", line):
            break
        cleaned_lines.append(line)
    
    return "\n".join(cleaned_lines).strip()


def parse_eml_file(eml_path: Path, target_email: Optional[str] = None) -> List[Dict[str, Any]]:
    """解析单个 .eml 文件"""
    with open(eml_path, "rb") as f:
        msg = email.message_from_binary_file(f)
    
    from_addr = decode_email_header(msg.get("From", ""))
    to_addr = decode_email_header(msg.get("To", ""))
    subject = decode_email_header(msg.get("Subject", ""))
    date_str = msg.get("Date", "")
    
    body = extract_email_body(msg)
    body = clean_email_body(body)
    
    # 判断是发件还是收件
    is_sent = target_email and target_email.lower() in from_addr.lower()
    
    record = {
        "type": "email",
        "from": from_addr,
        "to": to_addr,
        "subject": subject,
        "date": date_str,
        "body": body,
        "is_sent": is_sent,
    }
    
    return [record] if body else []


def parse_mbox_file(mbox_path: Path, target_email: Optional[str] = None) -> List[Dict[str, Any]]:
    """解析 .mbox 文件"""
    records = []
    
    try:
        mbox = mailbox.mbox(str(mbox_path))
        for msg in mbox:
            from_addr = decode_email_header(msg.get("From", ""))
            to_addr = decode_email_header(msg.get("To", ""))
            subject = decode_email_header(msg.get("Subject", ""))
            date_str = msg.get("Date", "")
            
            body = extract_email_body(msg)
            body = clean_email_body(body)
            
            if not body:
                continue
            
            is_sent = target_email and target_email.lower() in from_addr.lower()
            
            record = {
                "type": "email",
                "from": from_addr,
                "to": to_addr,
                "subject": subject,
                "date": date_str,
                "body": body,
                "is_sent": is_sent,
            }
            
            records.append(record)
    except Exception as e:
        print(f"Error parsing mbox: {e}", file=sys.stderr)
    
    return records


def records_to_text(records: List[Dict[str, Any]]) -> str:
    """将记录转换为纯文本"""
    lines = []
    for rec in records:
        direction = "我发送" if rec.get("is_sent") else "我接收"
        lines.append(f"=== {direction} [{rec.get('date', 'Unknown')}] ===")
        lines.append(f"主题: {rec.get('subject', 'No Subject')}")
        lines.append(f"从: {rec.get('from', 'Unknown')}")
        lines.append(f"到: {rec.get('to', 'Unknown')}")
        lines.append("")
        lines.append(rec.get("body", ""))
        lines.append("")
    
    return "\n".join(lines)


def records_to_rag(records: List[Dict[str, Any]], rag_source: str = "records") -> List[Dict[str, Any]]:
    """将记录转换为 RAG 格式"""
    rag_docs = []
    
    for i, rec in enumerate(records):
        text = rec.get("body", "")
        if not text:
            continue
        
        metadata = {
            "source": rag_source,
            "index": i,
            "type": "email",
            "from": rec.get("from", ""),
            "to": rec.get("to", ""),
            "subject": rec.get("subject", ""),
            "date": rec.get("date", ""),
            "is_sent": rec.get("is_sent", False),
        }
        
        rag_docs.append({
            "text": text,
            "metadata": metadata,
        })
    
    return rag_docs


def main() -> int:
    import sys
    
    parser = argparse.ArgumentParser(description="Parse email files (.eml / .mbox)")
    parser.add_argument("--file", required=True, help="Email file path (.eml or .mbox)")
    parser.add_argument("--target-email", help="Your email address (to identify sent vs received)")
    parser.add_argument("--format", default="text", choices=["text", "records-json", "records-jsonl", "rag-json", "rag-jsonl"])
    parser.add_argument("--rag-source", default="emails", help="Source label for RAG metadata")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    
    args = parser.parse_args()
    
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1
    
    # 解析邮件
    if file_path.suffix.lower() == ".eml":
        records = parse_eml_file(file_path, args.target_email)
    elif file_path.suffix.lower() == ".mbox":
        records = parse_mbox_file(file_path, args.target_email)
    else:
        print(f"Error: Unsupported file format: {file_path.suffix}", file=sys.stderr)
        return 1
    
    if not records:
        print("Warning: No valid emails found", file=sys.stderr)
        return 0
    
    # 格式化输出
    if args.format == "text":
        output = records_to_text(records)
    elif args.format == "records-json":
        output = json.dumps({"records": records}, ensure_ascii=False, indent=2)
    elif args.format == "records-jsonl":
        output = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    elif args.format == "rag-json":
        rag_docs = records_to_rag(records, args.rag_source)
        output = json.dumps({"docs": rag_docs}, ensure_ascii=False, indent=2)
    elif args.format == "rag-jsonl":
        rag_docs = records_to_rag(records, args.rag_source)
        output = "\n".join(json.dumps(d, ensure_ascii=False) for d in rag_docs)
    else:
        output = records_to_text(records)
    
    # 写入输出
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Parsed {len(records)} emails -> {args.output}")
    else:
        print(output)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
