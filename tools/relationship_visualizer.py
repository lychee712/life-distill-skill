#!/usr/bin/env python3
"""
关系网络可视化工具

从 relationship_analyzer.py 的输出生成关系图可视化。

输出格式：
- HTML（交互式图表，使用 D3.js 或 ECharts）
- Markdown（简单的文本图表）
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def generate_markdown_chart(data: Dict[str, Any]) -> str:
    """生成 Markdown 格式的关系图"""
    lines = []
    lines.append(f"# {data['target_name']} 的关系网络\n")
    lines.append(f"总联系人: {data['total_contacts']} | 有效分析: {data['analyzed_contacts']}\n")
    
    # 按等级分组
    by_level: Dict[str, List[Dict[str, Any]]] = {}
    for contact in data["contacts"]:
        level = contact["level"]
        if level not in by_level:
            by_level[level] = []
        by_level[level].append(contact)
    
    # 等级分布图（使用 Unicode 方块字符）
    lines.append("## 等级分布\n")
    lines.append("```")
    
    max_count = max(len(contacts) for contacts in by_level.values()) if by_level else 1
    
    for level in ["S+", "S", "A", "B", "C", "D"]:
        contacts = by_level.get(level, [])
        count = len(contacts)
        label = contacts[0]["label"] if contacts else ""
        
        # 条形图
        bar_length = int((count / max_count) * 30) if max_count > 0 else 0
        bar = "█" * bar_length
        
        lines.append(f"{level:3s} ({label:6s}) [{count:3d}] {bar}")
    
    lines.append("```\n")
    
    # 详细列表
    lines.append("## 关系详情\n")
    
    for level in ["S+", "S", "A", "B", "C", "D"]:
        contacts = by_level.get(level, [])
        if not contacts:
            continue
        
        label = contacts[0]["label"]
        lines.append(f"### {level} 级 - {label} ({len(contacts)} 人)\n")
        
        for c in contacts[:10]:  # 最多显示 10 个
            freq = c["details"]["avg_per_day"]
            freq_str = f"{freq:.2f} 次/天" if freq >= 1 else f"{freq*7:.1f} 次/周"
            
            lines.append(
                f"- **{c['contact']}** "
                f"(得分: {c['score']}, 联系频率: {freq_str}, "
                f"总消息: {c['details']['total_messages']})"
            )
            lines.append(
                f"  - 关系时长: {c['timeline']['first_contact']} ~ {c['timeline']['last_contact']}"
            )
        
        if len(contacts) > 10:
            lines.append(f"\n  *...还有 {len(contacts) - 10} 人*\n")
        
        lines.append("")
    
    # 统计摘要
    lines.append("## 关系摘要\n")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    
    total = data["analyzed_contacts"]
    core_count = len(by_level.get("S+", [])) + len(by_level.get("S", []))
    important_count = len(by_level.get("A", []))
    
    lines.append(f"| 核心圈（S+/S） | {core_count} 人 ({core_count/total*100:.1f}%) |")
    lines.append(f"| 重要圈（A） | {important_count} 人 ({important_count/total*100:.1f}%) |")
    lines.append(f"| 熟人及以下（B/C/D） | {total - core_count - important_count} 人 ({(total-core_count-important_count)/total*100:.1f}%) |")
    
    return "\n".join(lines)


def generate_html_chart(data: Dict[str, Any]) -> str:
    """生成 HTML 交互式图表（使用 ECharts）"""
    # 准备数据
    by_level: Dict[str, List[Dict[str, Any]]] = {}
    for contact in data["contacts"]:
        level = contact["level"]
        if level not in by_level:
            by_level[level] = []
        by_level[level].append(contact)
    
    # 等级分布数据
    level_data = []
    for level in ["S+", "S", "A", "B", "C", "D"]:
        contacts = by_level.get(level, [])
        label = contacts[0]["label"] if contacts else ""
        level_data.append({
            "name": f"{level} ({label})",
            "value": len(contacts)
        })
    
    # 生成 HTML
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{data['target_name']} 的关系网络</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .chart-container {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        #pieChart, #barChart {{
            width: 100%;
            height: 400px;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .stat-value {{
            font-size: 2em;
            font-weight: bold;
            color: #1890ff;
        }}
        .stat-label {{
            color: #666;
            margin-top: 5px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{data['target_name']} 的关系网络分析</h1>
        <p>总联系人: {data['total_contacts']} | 有效分析: {data['analyzed_contacts']} | 分析窗口: 近 {data['recent_months']} 个月</p>
    </div>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-value">{len(by_level.get('S+', [])) + len(by_level.get('S', []))}</div>
            <div class="stat-label">核心圈 (S+/S)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{len(by_level.get('A', []))}</div>
            <div class="stat-label">重要圈 (A)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{len(by_level.get('B', []))}</div>
            <div class="stat-label">熟人圈 (B)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{len(by_level.get('C', [])) + len(by_level.get('D', []))}</div>
            <div class="stat-label">弱联系 (C/D)</div>
        </div>
    </div>

    <div class="chart-container">
        <h2>关系等级分布</h2>
        <div id="pieChart"></div>
    </div>

    <div class="chart-container">
        <h2>等级对比</h2>
        <div id="barChart"></div>
    </div>

    <script>
        // 饼图
        var pieChart = echarts.init(document.getElementById('pieChart'));
        var pieOption = {{
            tooltip: {{
                trigger: 'item',
                formatter: '{{b}}: {{c}} 人 ({{d}}%)'
            }},
            legend: {{
                orient: 'vertical',
                left: 'left'
            }},
            series: [{{
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: false,
                itemStyle: {{
                    borderRadius: 10,
                    borderColor: '#fff',
                    borderWidth: 2
                }},
                label: {{
                    show: true,
                    formatter: '{{b}}\\n{{c}} 人'
                }},
                data: {json.dumps(level_data, ensure_ascii=False)}
            }}]
        }};
        pieChart.setOption(pieOption);

        // 柱状图
        var barChart = echarts.init(document.getElementById('barChart'));
        var barOption = {{
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{
                    type: 'shadow'
                }}
            }},
            xAxis: {{
                type: 'category',
                data: {json.dumps([d['name'] for d in level_data], ensure_ascii=False)}
            }},
            yAxis: {{
                type: 'value'
            }},
            series: [{{
                type: 'bar',
                data: {json.dumps([d['value'] for d in level_data])},
                itemStyle: {{
                    color: '#1890ff',
                    borderRadius: [4, 4, 0, 0]
                }},
                label: {{
                    show: true,
                    position: 'top'
                }}
            }}]
        }};
        barChart.setOption(barOption);

        // 响应式
        window.addEventListener('resize', function() {{
            pieChart.resize();
            barChart.resize();
        }});
    </script>
</body>
</html>"""
    
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize relationship network")
    parser.add_argument("--input", required=True, help="Input JSON from relationship_analyzer.py")
    parser.add_argument("--format", default="markdown", choices=["markdown", "html"])
    parser.add_argument("--output", help="Output file (default: stdout)")
    
    args = parser.parse_args()
    
    # 加载数据
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return 1
    
    data = json.loads(input_path.read_text(encoding="utf-8"))
    
    # 生成图表
    if args.format == "markdown":
        output = generate_markdown_chart(data)
    else:
        output = generate_html_chart(data)
    
    # 输出
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(output, encoding="utf-8")
        print(f"Visualization saved to {args.output}")
    else:
        print(output)
    
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
