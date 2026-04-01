#!/usr/bin/env python3
"""
版本管理器

功能：
- 查看所有历史版本
- 对比两个版本的差异
- 回滚到指定版本
- 导出版本历史
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def list_versions(skill_dir: Path) -> List[Dict[str, Any]]:
    """列出所有版本"""
    versions_dir = skill_dir / "versions"
    if not versions_dir.exists():
        return []
    
    meta_path = skill_dir / "meta.json"
    if not meta_path.exists():
        return []
    
    current_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    current_version = current_meta.get("version", "v1")
    
    versions = []
    
    # 收集所有版本文件
    version_files = {}
    for file in versions_dir.iterdir():
        if not file.is_file():
            continue
        
        # 文件名格式：v1_life_model.md, v2_persona.md
        match = file.stem.split("_", 1)
        if len(match) != 2:
            continue
        
        ver, file_type = match
        if ver not in version_files:
            version_files[ver] = {}
        version_files[ver][file_type] = file
    
    # 构建版本列表
    for ver in sorted(version_files.keys(), key=lambda v: int(v.lstrip("v"))):
        files = version_files[ver]
        version_info = {
            "version": ver,
            "is_current": ver == current_version,
            "files": files,
        }
        versions.append(version_info)
    
    # 添加当前版本
    if current_version not in version_files:
        versions.append({
            "version": current_version,
            "is_current": True,
            "files": {
                "life_model": skill_dir / "life_model.md",
                "persona": skill_dir / "persona.md",
            },
        })
    
    return versions


def show_version_diff(skill_dir: Path, ver1: str, ver2: str) -> str:
    """对比两个版本的差异（简单文本对比）"""
    versions = list_versions(skill_dir)
    
    v1_files = None
    v2_files = None
    
    for v in versions:
        if v["version"] == ver1:
            v1_files = v["files"]
        if v["version"] == ver2:
            v2_files = v["files"]
    
    if not v1_files or not v2_files:
        return f"Error: Version not found ({ver1} or {ver2})"
    
    diff_lines = []
    diff_lines.append(f"=== Comparing {ver1} -> {ver2} ===\n")
    
    # 对比 life_model.md
    if "life_model" in v1_files and "life_model" in v2_files:
        v1_text = v1_files["life_model"].read_text(encoding="utf-8")
        v2_text = v2_files["life_model"].read_text(encoding="utf-8")
        
        if v1_text != v2_text:
            diff_lines.append("## life_model.md")
            diff_lines.append(f"Length: {len(v1_text)} -> {len(v2_text)}")
            diff_lines.append("")
    
    # 对比 persona.md
    if "persona" in v1_files and "persona" in v2_files:
        v1_text = v1_files["persona"].read_text(encoding="utf-8")
        v2_text = v2_files["persona"].read_text(encoding="utf-8")
        
        if v1_text != v2_text:
            diff_lines.append("## persona.md")
            diff_lines.append(f"Length: {len(v1_text)} -> {len(v2_text)}")
            diff_lines.append("")
    
    return "\n".join(diff_lines)


def rollback_to_version(skill_dir: Path, target_version: str) -> bool:
    """回滚到指定版本"""
    versions = list_versions(skill_dir)
    
    target_files = None
    for v in versions:
        if v["version"] == target_version:
            target_files = v["files"]
            break
    
    if not target_files:
        print(f"Error: Version {target_version} not found")
        return False
    
    # 备份当前版本
    meta_path = skill_dir / "meta.json"
    if meta_path.exists():
        current_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        current_version = current_meta.get("version", "v1")
        
        # 创建备份
        backup_version = f"{current_version}_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        versions_dir = skill_dir / "versions"
        versions_dir.mkdir(exist_ok=True)
        
        for file_type in ["life_model", "persona"]:
            src = skill_dir / f"{file_type}.md"
            if src.exists():
                dst = versions_dir / f"{backup_version}_{file_type}.md"
                shutil.copy2(src, dst)
    
    # 恢复目标版本
    for file_type, file_path in target_files.items():
        if file_path.exists():
            dst = skill_dir / f"{file_type}.md"
            shutil.copy2(file_path, dst)
    
    # 更新 meta.json
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["version"] = target_version
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        meta["rollback_from"] = current_version
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    
    print(f"Rolled back to {target_version}")
    return True


def export_version_history(skill_dir: Path, output: Optional[Path] = None) -> str:
    """导出版本历史（JSON 格式）"""
    versions = list_versions(skill_dir)
    
    history = {
        "skill": skill_dir.name,
        "versions": [],
    }
    
    for v in versions:
        version_info = {
            "version": v["version"],
            "is_current": v["is_current"],
            "files": [str(f) for f in v["files"].values()],
        }
        history["versions"].append(version_info)
    
    output_str = json.dumps(history, ensure_ascii=False, indent=2)
    
    if output:
        output.write_text(output_str, encoding="utf-8")
        print(f"Exported version history to {output}")
    
    return output_str


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage skill versions")
    parser.add_argument("--skill-dir", required=True, help="Path to skill directory (e.g., lives/john)")
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # list 命令
    subparsers.add_parser("list", help="List all versions")
    
    # diff 命令
    diff_parser = subparsers.add_parser("diff", help="Compare two versions")
    diff_parser.add_argument("--v1", required=True, help="Version 1")
    diff_parser.add_argument("--v2", required=True, help="Version 2")
    
    # rollback 命令
    rollback_parser = subparsers.add_parser("rollback", help="Rollback to a version")
    rollback_parser.add_argument("--version", required=True, help="Target version")
    
    # export 命令
    export_parser = subparsers.add_parser("export", help="Export version history")
    export_parser.add_argument("--output", help="Output JSON file")
    
    args = parser.parse_args()
    
    skill_dir = Path(args.skill_dir)
    if not skill_dir.exists():
        print(f"Error: Skill directory not found: {skill_dir}")
        return 1
    
    if args.command == "list":
        versions = list_versions(skill_dir)
        print(f"=== Versions for {skill_dir.name} ===\n")
        for v in versions:
            marker = " (current)" if v["is_current"] else ""
            print(f"- {v['version']}{marker}")
            for file_type, file_path in v["files"].items():
                print(f"  - {file_type}: {file_path}")
        print(f"\nTotal: {len(versions)} versions")
    
    elif args.command == "diff":
        diff = show_version_diff(skill_dir, args.v1, args.v2)
        print(diff)
    
    elif args.command == "rollback":
        success = rollback_to_version(skill_dir, args.version)
        return 0 if success else 1
    
    elif args.command == "export":
        output_path = Path(args.output) if args.output else None
        export_version_history(skill_dir, output_path)
        if not args.output:
            print(export_version_history(skill_dir))
    
    else:
        parser.print_help()
        return 1
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
