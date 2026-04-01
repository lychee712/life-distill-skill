#!/usr/bin/env python3
"""
关系亲密度分析工具

从聊天记录中计算联系人的亲密度等级，分析关系演变趋势。

输入：
- wechat_parser.py 生成的 records-json/jsonl
- 时间窗口参数

输出：
- 亲密度分级清单
- 关系演变报告
- JSON/CSV 格式的详细数据
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """解析时间戳"""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y年%m月%d日 %H:%M:%S",
        "%Y年%m月%d日 %H:%M",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    
    return None


def calculate_message_depth(msg: str) -> int:
    """计算消息深度（1-3分）"""
    length = len(msg)
    
    if length > 50:
        return 3  # 深度对话
    elif length > 20:
        return 2  # 中度对话
    else:
        return 1  # 浅度对话


def calculate_emotion_density(msg: str) -> int:
    """计算情感浓度（1-3分）"""
    # 情感词列表
    emotion_words = [
        "开心", "高兴", "快乐", "幸福", "难过", "伤心", "想你", "爱",
        "哈哈", "嘿嘿", "呜呜", "嘻嘻", "心疼", "担心", "想念"
    ]
    
    # 亲昵称呼
    intimate_words = [
        "宝贝", "亲爱", "亲", "哥们", "兄弟", "姐妹", "老铁",
        "小可爱", "宝宝", "哥", "姐", "弟", "妹"
    ]
    
    # 表情符号（简单统计特殊字符）
    emoji_count = len(re.findall(r"[😀-🙏🌀-🗿]", msg))
    
    score = 0
    
    # 情感词
    if any(word in msg for word in emotion_words):
        score += 1
    
    # 亲昵称呼
    if any(word in msg for word in intimate_words):
        score += 1
    
    # 表情符号密度
    msg_len = len(msg)
    if msg_len > 0 and emoji_count / msg_len > 0.3:
        score += 1
    elif msg_len > 0 and emoji_count / msg_len > 0.1:
        score += 0.5
    
    return min(3, max(1, int(score + 1)))


def analyze_contact_intimacy(
    records: List[Dict[str, Any]],
    target_name: str,
    recent_months: int = 3,
) -> Dict[str, Any]:
    """分析与某个联系人的亲密度"""
    
    # 按联系人分组
    by_contact: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    
    for rec in records:
        speaker = rec.get("speaker", "")
        if not speaker or speaker == target_name:
            continue
        by_contact[speaker].append(rec)
    
    # 计算每个联系人的亲密度
    results = []
    
    for contact, messages in by_contact.items():
        if len(messages) < 10:  # 至少 10 条消息才分析
            continue
        
        # 解析时间戳
        timestamps = []
        for msg in messages:
            ts = parse_timestamp(msg.get("timestamp", ""))
            if ts:
                timestamps.append(ts)
        
        if not timestamps:
            continue
        
        timestamps.sort()
        first_time = timestamps[0]
        last_time = timestamps[-1]
        
        # 计算时间跨度（天数）
        duration_days = (last_time - first_time).days + 1
        
        # 计算最近 N 个月的消息
        cutoff_date = datetime.now() - timedelta(days=recent_months * 30)
        recent_messages = [msg for msg in messages if parse_timestamp(msg.get("timestamp", "")) and parse_timestamp(msg.get("timestamp", "")) >= cutoff_date]
        
        # 1. 联系频率得分（0-3）
        recent_count = len(recent_messages)
        recent_days = (datetime.now() - cutoff_date).days
        avg_per_day = recent_count / max(1, recent_days)
        
        if avg_per_day >= 1:
            freq_score = 3  # S 级
        elif avg_per_day >= 0.43:  # ~3次/周
            freq_score = 2.5  # A 级
        elif avg_per_day >= 0.14:  # ~1次/周
            freq_score = 2  # B 级
        elif avg_per_day >= 0.033:  # ~1次/月
            freq_score = 1.5  # C 级
        else:
            freq_score = 1  # D 级
        
        # 2. 消息深度得分（1-3）
        depth_scores = [calculate_message_depth(msg.get("content", "")) for msg in messages]
        avg_depth = sum(depth_scores) / len(depth_scores) if depth_scores else 1
        
        # 3. 情感浓度得分（1-3）
        emotion_scores = [calculate_emotion_density(msg.get("content", "")) for msg in messages]
        avg_emotion = sum(emotion_scores) / len(emotion_scores) if emotion_scores else 1
        
        # 4. 互动对称性得分（1-3）
        # 统计双方消息数
        my_count = sum(1 for msg in messages if msg.get("speaker") == target_name)
        their_count = len(messages) - my_count
        
        if their_count > 0:
            ratio = my_count / their_count
        else:
            ratio = 0
        
        if 0.6 <= ratio <= 1.4:
            symmetry_score = 3
        elif 0.4 <= ratio <= 2.0:
            symmetry_score = 2
        else:
            symmetry_score = 1
        
        # 5. 关系持续时长得分（1-3）
        if duration_days > 730:  # 2年
            duration_score = 3
        elif duration_days > 180:  # 6个月
            duration_score = 2
        else:
            duration_score = 1
        
        # 综合得分
        total_score = (
            freq_score * 0.30 +
            avg_depth * 0.25 +
            avg_emotion * 0.20 +
            symmetry_score * 0.15 +
            duration_score * 0.10
        )
        
        # 等级判定
        if total_score >= 2.7:
            level = "S+"
            label = "核心圈"
        elif total_score >= 2.4:
            level = "S"
            label = "亲密圈"
        elif total_score >= 2.0:
            level = "A"
            label = "重要圈"
        elif total_score >= 1.6:
            level = "B"
            label = "熟人圈"
        elif total_score >= 1.2:
            level = "C"
            label = "泛熟人"
        else:
            level = "D"
            label = "弱联系"
        
        results.append({
            "contact": contact,
            "level": level,
            "label": label,
            "score": round(total_score, 2),
            "details": {
                "total_messages": len(messages),
                "recent_messages": recent_count,
                "duration_days": duration_days,
                "avg_per_day": round(avg_per_day, 3),
                "freq_score": round(freq_score, 2),
                "depth_score": round(avg_depth, 2),
                "emotion_score": round(avg_emotion, 2),
                "symmetry_score": symmetry_score,
                "duration_score": duration_score,
                "my_messages": my_count,
                "their_messages": their_count,
            },
            "timeline": {
                "first_contact": first_time.strftime("%Y-%m-%d"),
                "last_contact": last_time.strftime("%Y-%m-%d"),
            },
        })
    
    # 按得分排序
    results.sort(key=lambda x: x["score"], reverse=True)
    
    return {
        "target_name": target_name,
        "total_contacts": len(by_contact),
        "analyzed_contacts": len(results),
        "recent_months": recent_months,
        "contacts": results,
    }


def format_text_report(data: Dict[str, Any]) -> str:
    """格式化为文本报告"""
    lines = []
    lines.append(f"=== 关系网络分析报告 ===\n")
    lines.append(f"分析对象: {data['target_name']}")
    lines.append(f"总联系人数: {data['total_contacts']}")
    lines.append(f"有效对话联系人: {data['analyzed_contacts']} (>10条消息)")
    lines.append(f"分析时间窗口: 近 {data['recent_months']} 个月\n")
    
    # 按等级统计
    by_level: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for contact in data["contacts"]:
        by_level[contact["level"]].append(contact)
    
    lines.append("## 等级分布\n")
    for level in ["S+", "S", "A", "B", "C", "D"]:
        contacts = by_level.get(level, [])
        if contacts:
            label = contacts[0]["label"]
            lines.append(f"### {level} 级（{label}）: {len(contacts)} 人\n")
            for c in contacts[:5]:  # 只显示前5个
                lines.append(
                    f"- {c['contact']} (得分: {c['score']}, "
                    f"消息: {c['details']['total_messages']}, "
                    f"最近: {c['timeline']['last_contact']})"
                )
            if len(contacts) > 5:
                lines.append(f"  ... 还有 {len(contacts) - 5} 人")
            lines.append("")
    
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze relationship intimacy from chat records")
    parser.add_argument("--input", required=True, help="Input records file (json/jsonl)")
    parser.add_argument("--target-name", required=True, help="Your name in the chat")
    parser.add_argument("--recent-months", type=int, default=3, help="Analyze recent N months")
    parser.add_argument("--format", default="text", choices=["text", "json", "csv"])
    parser.add_argument("--output", help="Output file (default: stdout)")
    parser.add_argument("--min-level", help="Filter by minimum level (e.g., B)")
    
    args = parser.parse_args()
    
    # 加载数据
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return 1
    
    text = input_path.read_text(encoding="utf-8")
    suffix = input_path.suffix.lower()
    
    if suffix == ".jsonl":
        records = []
        for line in text.splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    else:
        data = json.loads(text)
        if isinstance(data, dict) and "records" in data:
            records = data["records"]
        elif isinstance(data, list):
            records = data
        else:
            print("Error: Invalid JSON format")
            return 1
    
    # 分析
    result = analyze_contact_intimacy(records, args.target_name, args.recent_months)
    
    # 过滤
    if args.min_level:
        level_order = ["D", "C", "B", "A", "S", "S+"]
        min_idx = level_order.index(args.min_level)
        result["contacts"] = [
            c for c in result["contacts"]
            if level_order.index(c["level"]) >= min_idx
        ]
        result["analyzed_contacts"] = len(result["contacts"])
    
    # 输出
    if args.format == "text":
        output = format_text_report(result)
    elif args.format == "json":
        output = json.dumps(result, ensure_ascii=False, indent=2)
    elif args.format == "csv":
        import csv
        import io
        
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["联系人", "等级", "标签", "得分", "总消息数", "最近消息数", "首次联系", "最后联系"])
        
        for c in result["contacts"]:
            writer.writerow([
                c["contact"],
                c["level"],
                c["label"],
                c["score"],
                c["details"]["total_messages"],
                c["details"]["recent_messages"],
                c["timeline"]["first_contact"],
                c["timeline"]["last_contact"],
            ])
        
        output = buf.getvalue()
    
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Analysis saved to {args.output}")
    else:
        print(output)
    
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
