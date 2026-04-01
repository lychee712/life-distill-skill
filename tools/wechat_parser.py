#!/usr/bin/env python3
"""
微信聊天导出解析器

支持输入：
- txt（常见文本导出）
- json（通用 messages/data，CipherTalk detailed-json/chatlab）
- jsonl（CipherTalk chatlab-jsonl）
- html（CipherTalk 单文件导出，内嵌 window.CHAT_DATA）

支持输出：
- text（兼容旧版）
- records-json / records-jsonl（结构化消息）
- chunks-json / chunks-jsonl（RAG chunk）
- rag-json / rag-jsonl（embedding 直接可用的 text + metadata）
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


TIME_LINE_PATTERNS = [
    re.compile(r"^(?P<ts>\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)$"),
    re.compile(r"^(?P<ts>\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}(?::\d{2})?)$"),
]

BRACKET_MSG_LINE = re.compile(
    r"^\[(?P<ts>[^\]]{4,64})\]\s*(?P<speaker>[^:：]{1,80})[:：]\s?(?P<content>.+)$"
)
INLINE_TS_SPEAKER_LINE = re.compile(
    r"^(?P<ts>\d{4}(?:[-/]\d{1,2}[-/]\d{1,2}|年\d{1,2}月\d{1,2}日)\s+\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<speaker>[^:：]{1,80})[:：]\s?(?P<content>.+)$"
)
SPEAKER_LINE = re.compile(r"^(?P<speaker>[^:：]{1,40})[:：]\s?(?P<content>.+)$")

LOCAL_TYPE_TO_CANONICAL = {
    1: "text",
    3: "image",
    8: "file",
    34: "voice",
    43: "video",
    47: "emoji",
    48: "location",
    49: "file",
    50: "call",
    10000: "system",
    266287972401: "system",
}

CHATLAB_TYPE_TO_CANONICAL = {
    0: "text",
    1: "image",
    2: "voice",
    3: "video",
    4: "file",
    5: "emoji",
    7: "link",
    8: "location",
    23: "call",
    27: "contact",
    80: "system",
}

TYPE_HINTS = [
    ("图片", "image"),
    ("image", "image"),
    ("视频", "video"),
    ("video", "video"),
    ("语音", "voice"),
    ("voice", "voice"),
    ("表情", "emoji"),
    ("emoji", "emoji"),
    ("位置", "location"),
    ("location", "location"),
    ("系统", "system"),
    ("system", "system"),
    ("通话", "call"),
    ("call", "call"),
    ("文件", "file"),
    ("file", "file"),
    ("链接", "link"),
    ("link", "link"),
    ("文本", "text"),
    ("text", "text"),
]

NOISE_PATTERNS = [
    re.compile(r"撤回了一条消息"),
    re.compile(r"拍了拍"),
    re.compile(r"加入群聊|离开群聊|被移出群聊"),
    re.compile(r"以上是打招呼的内容"),
    re.compile(r"开启了朋友验证"),
]

PLACEHOLDER_CONTENTS = {
    "[文本消息]",
    "[图片]",
    "[语音消息]",
    "[视频]",
    "[动画表情]",
    "[位置]",
    "[通话]",
    "[文件]",
    "[链接]",
    "[名片]",
    "[系统消息]",
    "[消息]",
}


def normalize_speaker(name: str) -> str:
    text = str(name or "")
    # 去除括号中的设备/备注后缀，如 张三(工作)、张三（手机）
    text = re.sub(r"[\(（\[【].*?[\)）\]】]", "", text)
    cleaned = re.sub(r"[^\w\u4e00-\u9fa5]", "", text, flags=re.UNICODE)
    return cleaned.lower().strip()


def _sanitize_text(value: Any) -> str:
    text = str(value or "")
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def _normalize_ts(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, (int, float)):
        ts_num = float(value)
        if ts_num <= 0:
            return ""
        if ts_num > 1e11:
            ts_num = ts_num / 1000.0
        try:
            return datetime.fromtimestamp(ts_num).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            return str(value)

    text = str(value).strip()
    if not text:
        return ""

    if text.isdigit():
        return _normalize_ts(int(text))

    iso_candidate = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def _normalize_raw_type(raw_type: Any) -> Any:
    if raw_type is None:
        return None
    if isinstance(raw_type, int):
        return raw_type
    if isinstance(raw_type, float):
        return int(raw_type)
    text = str(raw_type).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return text


def _canonical_type(raw_type: Any, type_hint: Any = "", content_hint: Any = "") -> str:
    raw = _normalize_raw_type(raw_type)
    if isinstance(raw, int):
        if raw in LOCAL_TYPE_TO_CANONICAL:
            return LOCAL_TYPE_TO_CANONICAL[raw]
        if raw in CHATLAB_TYPE_TO_CANONICAL:
            return CHATLAB_TYPE_TO_CANONICAL[raw]

    hint_text = f"{_sanitize_text(type_hint)} {_sanitize_text(content_hint)}".lower()
    for hint, msg_type in TYPE_HINTS:
        if hint in hint_text:
            return msg_type

    return "text"


def _placeholder_content(raw_type: Any, type_hint: Any = "") -> str:
    msg_type = _canonical_type(raw_type, type_hint)
    return {
        "text": "[文本消息]",
        "image": "[图片]",
        "voice": "[语音消息]",
        "video": "[视频]",
        "emoji": "[动画表情]",
        "location": "[位置]",
        "call": "[通话]",
        "file": "[文件]",
        "link": "[链接]",
        "contact": "[名片]",
        "system": "[系统消息]",
    }.get(msg_type, "[消息]")


def _effective_text_len(content: str) -> int:
    return len(re.findall(r"[\w\u4e00-\u9fa5]", content, flags=re.UNICODE))


def is_noise(record: Dict[str, Any], min_content_len: int = 2) -> Tuple[bool, str]:
    content = _sanitize_text(record.get("content"))
    msg_type = str(record.get("type") or "")

    if msg_type == "system":
        return True, "system"

    for pattern in NOISE_PATTERNS:
        if pattern.search(content):
            return True, "system_notice"

    if content in PLACEHOLDER_CONTENTS:
        return True, "placeholder"

    if _effective_text_len(content) < min_content_len:
        return True, "too_short"

    if re.fullmatch(r"[\W_]+", content, flags=re.UNICODE):
        return True, "symbol_only"

    return False, ""


def clean_records(records: List[Dict[str, Any]], min_content_len: int = 2) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    dropped = 0
    reason_counts: Dict[str, int] = {}

    for r in records:
        noisy, reason = is_noise(r, min_content_len=min_content_len)
        if noisy:
            dropped += 1
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            continue
        out.append(r)

    return out, {
        "input": len(records),
        "kept": len(out),
        "dropped": dropped,
        "reasons": reason_counts,
    }


def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(k in text for k in keywords)


def _infer_emotion(content: str, msg_type: str) -> str:
    text = content.lower()
    if msg_type == "system":
        return "neutral"
    if _contains_any(text, ["急", "赶紧", "马上", "立刻", "尽快"]):
        return "urgent"
    if _contains_any(text, ["开心", "哈哈", "感谢", "谢谢", "赞", "太好了", "不错", "高兴", "棒"]):
        return "positive"
    if _contains_any(text, ["难过", "烦", "生气", "崩溃", "焦虑", "压力", "累", "糟糕", "伤心", "无语"]):
        return "negative"
    if "?" in text or "？" in text:
        return "questioning"
    return "neutral"


def _infer_topic(content: str, msg_type: str) -> str:
    text = content.lower()
    if msg_type in {"image", "video", "voice", "emoji"}:
        return "media"
    if _contains_any(text, ["项目", "需求", "会议", "汇报", "上线", "排期", "工作", "客户"]):
        return "work"
    if _contains_any(text, ["钱", "预算", "报销", "转账", "工资", "成本", "投资"]):
        return "finance"
    if _contains_any(text, ["身体", "医院", "药", "睡眠", "运动", "体检", "健康"]):
        return "health"
    if _contains_any(text, ["家", "朋友", "恋爱", "关系", "沟通", "情绪"]):
        return "relationship"
    if _contains_any(text, ["学习", "复盘", "总结", "读书", "课程", "成长"]):
        return "learning"
    if _contains_any(text, ["吃饭", "周末", "今天", "明天", "出门", "回家"]):
        return "daily_life"
    return "general"


def _infer_intent(content: str, msg_type: str) -> str:
    text = content.lower()
    if msg_type in {"image", "video", "voice", "emoji"}:
        return "share_media"
    if "?" in text or "？" in text or _contains_any(text, ["请问", "能不能", "可以吗", "要不要"]):
        return "ask"
    if _contains_any(text, ["谢谢", "感谢"]):
        return "gratitude"
    if _contains_any(text, ["建议", "方案", "怎么做", "如何", "是否"]):
        return "decision"
    if _contains_any(text, ["安排", "计划", "明天", "今晚", "几点", "约", "会议"]):
        return "planning"
    if _contains_any(text, ["提醒", "记得", "别忘了"]):
        return "reminder"
    return "statement"


def enrich_record(record: Dict[str, Any]) -> Dict[str, Any]:
    content = _sanitize_text(record.get("content"))
    msg_type = str(record.get("type") or "text")

    enriched = dict(record)
    enriched["emotion"] = _infer_emotion(content, msg_type)
    enriched["topic"] = _infer_topic(content, msg_type)
    enriched["intent"] = _infer_intent(content, msg_type)
    return enriched


def enrich_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [enrich_record(r) for r in records]


def _build_record(
    ts: Any,
    speaker: Any,
    content: Any,
    msg_type: str,
    raw_type: Any,
    session: str,
) -> Optional[Dict[str, Any]]:
    content_text = _sanitize_text(content)
    if not content_text:
        return None

    speaker_text = _sanitize_text(speaker)
    return {
        "ts": _normalize_ts(ts),
        "speaker": speaker_text,
        "speaker_norm": normalize_speaker(speaker_text),
        "content": content_text,
        "type": msg_type,
        "raw_type": _normalize_raw_type(raw_type),
        "session": _sanitize_text(session),
    }


def _append_chat_records(
    records: List[Dict[str, Any]],
    parent_ts: str,
    session: str,
    chat_records: Any,
) -> None:
    if not isinstance(chat_records, list):
        return

    for cr in chat_records:
        if not isinstance(cr, dict):
            continue

        ts = cr.get("formattedTime") or cr.get("timestamp") or cr.get("time") or parent_ts
        speaker = (
            cr.get("senderDisplayName")
            or cr.get("senderName")
            or cr.get("accountName")
            or cr.get("sender")
            or cr.get("sourcename")
            or "forwarded"
        )
        raw_type = cr.get("datatype") or cr.get("type")
        msg_type = _canonical_type(raw_type, cr.get("type"), cr.get("content"))
        content = cr.get("content") or cr.get("datadesc") or cr.get("datatitle")
        if not content:
            content = _placeholder_content(raw_type, cr.get("type"))

        rec = _build_record(ts, speaker, f"[转发] {content}", msg_type, raw_type, session)
        if rec:
            records.append(rec)


def parse_txt(lines: Iterable[str], session: str = "") -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    current_ts: str = ""

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        bracket = BRACKET_MSG_LINE.match(line)
        if bracket:
            rec = _build_record(
                bracket.group("ts"),
                bracket.group("speaker"),
                bracket.group("content"),
                "text",
                1,
                session,
            )
            if rec:
                records.append(rec)
            continue

        inline = INLINE_TS_SPEAKER_LINE.match(line)
        if inline:
            rec = _build_record(
                inline.group("ts"),
                inline.group("speaker"),
                inline.group("content"),
                "text",
                1,
                session,
            )
            if rec:
                records.append(rec)
            continue

        if any(p.match(line) for p in TIME_LINE_PATTERNS):
            current_ts = line
            continue

        m = SPEAKER_LINE.match(line)
        if m:
            rec = _build_record(current_ts, m.group("speaker"), m.group("content"), "text", 1, session)
            if rec:
                records.append(rec)
            continue

        if records:
            records[-1]["content"] += " " + line

    return records


def parse_ciphertalk_detailed_json(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    messages = data.get("messages")
    if not isinstance(messages, list):
        return []

    session_info = data.get("session") if isinstance(data.get("session"), dict) else {}
    session = _sanitize_text(
        session_info.get("displayName") or session_info.get("nickname") or session_info.get("wxid")
    )

    records: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue

        ts = msg.get("formattedTime") or msg.get("createTime") or msg.get("timestamp")
        speaker = (
            msg.get("senderDisplayName")
            or msg.get("groupNickname")
            or msg.get("accountName")
            or msg.get("senderName")
            or msg.get("senderUsername")
            or msg.get("sender")
            or ""
        )
        raw_type = msg.get("localType") or msg.get("local_type") or msg.get("raw_type")
        msg_type = _canonical_type(raw_type, msg.get("type"), msg.get("content"))
        content = msg.get("content") or msg.get("parsedContent") or _placeholder_content(raw_type, msg.get("type"))

        rec = _build_record(ts, speaker, content, msg_type, raw_type, session)
        if rec:
            records.append(rec)
            _append_chat_records(records, rec["ts"], session, msg.get("chatRecords"))

    return records


def parse_ciphertalk_chatlab_json(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    members = data.get("members")
    messages = data.get("messages")
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if not isinstance(messages, list):
        return []

    session = _sanitize_text(meta.get("name") or meta.get("groupId") or "")

    member_names: Dict[str, str] = {}
    if isinstance(members, list):
        for member in members:
            if not isinstance(member, dict):
                continue
            member_id = _sanitize_text(member.get("platformId") or member.get("id"))
            member_name = _sanitize_text(
                member.get("groupNickname") or member.get("accountName") or member.get("name")
            )
            if member_id:
                member_names[member_id] = member_name or member_id

    records: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue

        sender_id = _sanitize_text(msg.get("sender"))
        speaker = msg.get("groupNickname") or msg.get("accountName") or member_names.get(sender_id) or sender_id
        raw_type = msg.get("raw_type") or msg.get("type")
        msg_type = _canonical_type(raw_type, msg.get("type"), msg.get("content"))
        content = msg.get("content") or _placeholder_content(raw_type, msg.get("type"))

        rec = _build_record(msg.get("timestamp") or msg.get("time"), speaker, content, msg_type, raw_type, session)
        if rec:
            records.append(rec)
            _append_chat_records(records, rec["ts"], session, msg.get("chatRecords"))

    return records


def parse_chatlab_jsonl(lines: Iterable[str]) -> List[Dict[str, Any]]:
    member_names: Dict[str, str] = {}
    message_items: List[Dict[str, Any]] = []
    session: str = ""

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue

        item_type = item.get("_type")
        if item_type == "header":
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            session = _sanitize_text(meta.get("name") or meta.get("groupId") or "")
        elif item_type == "member":
            member_id = _sanitize_text(item.get("platformId") or item.get("id"))
            member_name = _sanitize_text(item.get("groupNickname") or item.get("accountName") or item.get("name"))
            if member_id:
                member_names[member_id] = member_name or member_id
        elif item_type == "message":
            message_items.append(item)

    records: List[Dict[str, Any]] = []
    for msg in message_items:
        sender_id = _sanitize_text(msg.get("sender"))
        speaker = msg.get("groupNickname") or msg.get("accountName") or member_names.get(sender_id) or sender_id
        raw_type = msg.get("raw_type") or msg.get("type")
        msg_type = _canonical_type(raw_type, msg.get("type"), msg.get("content"))
        content = msg.get("content") or _placeholder_content(raw_type, msg.get("type"))

        rec = _build_record(msg.get("timestamp") or msg.get("time"), speaker, content, msg_type, raw_type, session)
        if rec:
            records.append(rec)
            _append_chat_records(records, rec["ts"], session, msg.get("chatRecords"))

    return records


def _extract_chat_data_json_from_html(text: str) -> Optional[Any]:
    marker = "window.CHAT_DATA"
    marker_idx = text.find(marker)
    if marker_idx < 0:
        return None

    eq_idx = text.find("=", marker_idx)
    if eq_idx < 0:
        return None

    start = eq_idx + 1
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text) or text[start] not in "[{":
        return None

    quote_char = ""
    escaped = False
    depth = 0
    end = -1
    for i in range(start, len(text)):
        ch = text[i]

        if quote_char:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
            elif ch == quote_char:
                quote_char = ""
            continue

        if ch in ('"', "'"):
            quote_char = ch
            continue

        if ch in "[{":
            depth += 1
            continue

        if ch in "]}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end < 0:
        return None

    payload = text[start:end]
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def parse_ciphertalk_html(text: str) -> List[Dict[str, Any]]:
    data = _extract_chat_data_json_from_html(text)
    if not isinstance(data, dict):
        return []

    members = data.get("members")
    messages = data.get("messages")
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if not isinstance(messages, list):
        return []

    session = _sanitize_text(meta.get("sessionName") or meta.get("sessionId") or "")

    member_names: Dict[str, str] = {}
    if isinstance(members, list):
        for member in members:
            if not isinstance(member, dict):
                continue
            member_id = _sanitize_text(member.get("id") or member.get("platformId"))
            member_name = _sanitize_text(member.get("name") or member.get("accountName") or member.get("groupNickname"))
            if member_id:
                member_names[member_id] = member_name or member_id

    records: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue

        sender_id = _sanitize_text(msg.get("sender"))
        speaker = _sanitize_text(msg.get("senderName") or member_names.get(sender_id) or sender_id)
        raw_type = msg.get("raw_type") or msg.get("type")
        msg_type = _canonical_type(raw_type, msg.get("type"), msg.get("content"))
        content = msg.get("content") or _placeholder_content(raw_type, msg.get("type"))

        rec = _build_record(msg.get("timestamp") or msg.get("time"), speaker, content, msg_type, raw_type, session)
        if rec:
            records.append(rec)
            _append_chat_records(records, rec["ts"], session, msg.get("chatRecords"))

    return records


def parse_generic_json(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("messages") or data.get("data") or []
        top_session = _sanitize_text(data.get("session") or data.get("sessionName") or "")
    elif isinstance(data, list):
        items = data
        top_session = ""
    else:
        items = []
        top_session = ""

    records: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        ts = item.get("time") or item.get("timestamp") or item.get("ts") or item.get("createTime") or item.get("formattedTime")
        speaker = (
            item.get("speaker")
            or item.get("sender")
            or item.get("from")
            or item.get("senderName")
            or item.get("senderDisplayName")
            or item.get("accountName")
            or item.get("senderUsername")
            or ""
        )
        raw_type = item.get("raw_type") or item.get("localType") or item.get("local_type") or item.get("type")
        msg_type = _canonical_type(raw_type, item.get("type"), item.get("content"))
        content = item.get("content") or item.get("text") or item.get("message") or item.get("parsedContent")
        if not content:
            content = _placeholder_content(raw_type, item.get("type"))

        session = item.get("session") or item.get("sessionName") or top_session
        rec = _build_record(ts, speaker, content, msg_type, raw_type, _sanitize_text(session))
        if rec:
            records.append(rec)
            _append_chat_records(records, rec["ts"], rec["session"], item.get("chatRecords"))

    return records


def parse_json(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        if "session" in data and isinstance(data.get("messages"), list):
            return parse_ciphertalk_detailed_json(data)
        if "chatlab" in data and isinstance(data.get("messages"), list):
            return parse_ciphertalk_chatlab_json(data)
    return parse_generic_json(data)


def _parse_input_text(in_path: Path, text: str) -> List[Dict[str, Any]]:
    suffix = in_path.suffix.lower()
    default_session = _sanitize_text(in_path.stem)

    if suffix in (".html", ".htm"):
        html_records = parse_ciphertalk_html(text)
        return html_records or parse_txt(text.splitlines(), session=default_session)

    if suffix == ".jsonl":
        return parse_chatlab_jsonl(text.splitlines())

    if suffix == ".json":
        return parse_json(json.loads(text))

    if "window.CHAT_DATA" in text:
        html_records = parse_ciphertalk_html(text)
        if html_records:
            return html_records

    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return parse_json(json.loads(text))
        except json.JSONDecodeError:
            pass

    return parse_txt(text.splitlines(), session=default_session)


def _finalize_records(records: List[Dict[str, Any]], default_session: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in records:
        content = _sanitize_text(r.get("content"))
        if not content:
            continue

        speaker = _sanitize_text(r.get("speaker")) or "unknown-speaker"
        raw_type = _normalize_raw_type(r.get("raw_type"))
        msg_type = _canonical_type(raw_type, r.get("type"), content)
        session = _sanitize_text(r.get("session")) or default_session or "unknown-session"

        out.append(
            {
                "ts": _normalize_ts(r.get("ts")),
                "speaker": speaker,
                "speaker_norm": normalize_speaker(speaker),
                "content": content,
                "type": msg_type,
                "raw_type": raw_type,
                "session": session,
            }
        )

    return out


def filter_records(records: List[Dict[str, Any]], target: Optional[str]) -> List[Dict[str, Any]]:
    if not target:
        return records

    targets = {normalize_speaker(t) for t in target.split(",") if t.strip()}
    if not targets:
        return records

    out: List[Dict[str, Any]] = []
    for r in records:
        speaker_norm = normalize_speaker(str(r.get("speaker_norm") or r.get("speaker") or ""))
        matched = speaker_norm in targets
        if not matched:
            # target=张三 时，允许匹配 张三手机/张三工作 等变体
            for t in targets:
                if t and speaker_norm.startswith(t):
                    matched = True
                    break
        if matched:
            out.append(r)
    return out


def to_text(records: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for r in records:
        ts = r.get("ts") or "unknown-time"
        speaker = r.get("speaker") or "unknown-speaker"
        content = str(r.get("content", "")).replace("\n", " ").strip()
        lines.append(f"[{ts}] {speaker}: {content}")
    return "\n".join(lines)


def chunk_records(records: List[Dict[str, Any]], chunk_size: int = 30, chunk_overlap: int = 5) -> List[Dict[str, Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be >= 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be < chunk_size")

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        session = str(r.get("session") or "unknown-session")
        grouped.setdefault(session, []).append(r)

    chunks: List[Dict[str, Any]] = []
    step = chunk_size - chunk_overlap
    for session, rows in grouped.items():
        chunk_idx = 0
        for start in range(0, len(rows), step):
            part = rows[start : start + chunk_size]
            if not part:
                continue

            chunk_idx += 1
            lines = [f"[{x.get('ts') or 'unknown-time'}] {x.get('speaker')}: {x.get('content')}" for x in part]
            speakers = sorted({str(x.get("speaker")) for x in part if x.get("speaker")})
            types = sorted({str(x.get("type")) for x in part if x.get("type")})
            topics = sorted({str(x.get("topic")) for x in part if x.get("topic")})
            intents = sorted({str(x.get("intent")) for x in part if x.get("intent")})
            emotions = sorted({str(x.get("emotion")) for x in part if x.get("emotion")})
            chunk_id = f"{normalize_speaker(session) or 'session'}-{chunk_idx}"

            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "session": session,
                    "start_ts": part[0].get("ts", ""),
                    "end_ts": part[-1].get("ts", ""),
                    "record_count": len(part),
                    "speakers": speakers,
                    "types": types,
                    "topics": topics,
                    "intents": intents,
                    "emotions": emotions,
                    "text": "\n".join(lines),
                    "records": part,
                }
            )

    return chunks


def to_rag_docs(
    records: List[Dict[str, Any]],
    chunks: Optional[List[Dict[str, Any]]] = None,
    source: str = "chunks",
) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []

    if source == "records":
        for r in records:
            docs.append(
                {
                    "text": f"{r.get('speaker')}: {r.get('content')}",
                    "metadata": {
                        "ts": r.get("ts"),
                        "speaker": r.get("speaker"),
                        "speaker_norm": r.get("speaker_norm"),
                        "type": r.get("type", "text"),
                        "raw_type": r.get("raw_type"),
                        "session": r.get("session"),
                        "emotion": r.get("emotion"),
                        "topic": r.get("topic"),
                        "intent": r.get("intent"),
                        "source": "record",
                    },
                }
            )
        return docs

    if chunks is None:
        chunks = chunk_records(records)

    for c in chunks:
        docs.append(
            {
                "text": c.get("text", ""),
                "metadata": {
                    "chunk_id": c.get("chunk_id"),
                    "session": c.get("session"),
                    "start_ts": c.get("start_ts"),
                    "end_ts": c.get("end_ts"),
                    "record_count": c.get("record_count", 0),
                    "speakers": c.get("speakers", []),
                    "types": c.get("types", []),
                    "topics": c.get("topics", []),
                    "intents": c.get("intents", []),
                    "emotions": c.get("emotions", []),
                    "source": "chunk",
                },
            }
        )

    return docs


def _to_jsonl(items: List[Dict[str, Any]]) -> str:
    return "\n".join(json.dumps(item, ensure_ascii=False) for item in items)


def _serialize_output(
    emit: str,
    records: List[Dict[str, Any]],
    chunk_size: int,
    chunk_overlap: int,
    rag_source: str,
) -> Tuple[str, Dict[str, int]]:
    if emit == "text":
        return to_text(records), {"records": len(records), "chunks": 0, "docs": 0}

    if emit == "records-json":
        payload = {"records": records}
        return json.dumps(payload, ensure_ascii=False, indent=2), {"records": len(records), "chunks": 0, "docs": 0}

    if emit == "records-jsonl":
        return _to_jsonl(records), {"records": len(records), "chunks": 0, "docs": 0}

    if emit in ("rag-json", "rag-jsonl") and rag_source == "records":
        docs = to_rag_docs(records, chunks=None, source="records")
        if emit == "rag-json":
            payload = {"docs": docs}
            return json.dumps(payload, ensure_ascii=False, indent=2), {"records": len(records), "chunks": 0, "docs": len(docs)}
        return _to_jsonl(docs), {"records": len(records), "chunks": 0, "docs": len(docs)}

    chunks = chunk_records(records, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    if emit == "chunks-json":
        payload = {"chunks": chunks}
        return json.dumps(payload, ensure_ascii=False, indent=2), {"records": len(records), "chunks": len(chunks), "docs": 0}

    if emit == "chunks-jsonl":
        return _to_jsonl(chunks), {"records": len(records), "chunks": len(chunks), "docs": 0}

    docs = to_rag_docs(records, chunks=chunks, source=rag_source)
    if emit == "rag-json":
        payload = {"docs": docs}
        return json.dumps(payload, ensure_ascii=False, indent=2), {"records": len(records), "chunks": len(chunks), "docs": len(docs)}

    if emit == "rag-jsonl":
        return _to_jsonl(docs), {"records": len(records), "chunks": len(chunks), "docs": len(docs)}

    raise ValueError(f"unsupported emit mode: {emit}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse WeChat export into text/structured/chunks/rag docs")
    parser.add_argument("--file", required=True, help="Path to input txt/json/jsonl/html")
    parser.add_argument("--output", required=True, help="Path to output file")
    parser.add_argument("--target", help="Filter speakers, support comma-separated values")
    parser.add_argument(
        "--emit",
        default="text",
        choices=[
            "text",
            "records-json",
            "records-jsonl",
            "chunks-json",
            "chunks-jsonl",
            "rag-json",
            "rag-jsonl",
        ],
        help="Output mode",
    )
    parser.add_argument(
        "--format",
        dest="emit",
        choices=[
            "text",
            "records-json",
            "records-jsonl",
            "chunks-json",
            "chunks-jsonl",
            "rag-json",
            "rag-jsonl",
        ],
        help="Alias of --emit",
    )
    parser.add_argument("--session", help="Override session for all records")
    parser.add_argument("--chunk-size", type=int, default=30, help="Records per chunk")
    parser.add_argument("--chunk-overlap", type=int, default=5, help="Overlap records between chunks")
    parser.add_argument("--rag-source", choices=["records", "chunks"], default="records", help="RAG doc granularity")
    parser.add_argument(
        "--clean-noise",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable noise filtering (default: true)",
    )
    parser.add_argument("--min-content-len", type=int, default=2, help="Minimum effective text length")
    parser.add_argument(
        "--enrich",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable semantic enrichment: emotion/topic/intent (default: true)",
    )
    args = parser.parse_args()

    in_path = Path(args.file)
    if not in_path.exists():
        raise FileNotFoundError(f"input file not found: {in_path}")

    text = in_path.read_text(encoding="utf-8", errors="ignore")
    parsed = _parse_input_text(in_path, text)
    records = _finalize_records(parsed, default_session=_sanitize_text(in_path.stem))

    if args.session:
        override_session = _sanitize_text(args.session)
        for r in records:
            r["session"] = override_session

    filtered = filter_records(records, args.target)

    quality_stats = {"input": len(filtered), "kept": len(filtered), "dropped": 0, "reasons": {}}
    if args.clean_noise:
        filtered, quality_stats = clean_records(filtered, min_content_len=max(args.min_content_len, 1))

    if args.enrich:
        filtered = enrich_records(filtered)

    out_text, stats = _serialize_output(
        emit=args.emit,
        records=filtered,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        rag_source=args.rag_source,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out_text, encoding="utf-8")

    print(
        f"parsed={len(records)} kept={len(filtered)} chunks={stats['chunks']} docs={stats['docs']} "
        f"dropped={quality_stats['dropped']} emit={args.emit} output={out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
