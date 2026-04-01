#!/usr/bin/env python3
"""
人生 Skill 写入器

创建 lives/{slug}/ 目录并写入：
- life_model.md
- persona.md
- SKILL.md
- meta.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


SKILL_TEMPLATE = """---
name: life_{slug}
description: {name} 的人生模型与表达分身
user-invocable: true
---

# {name}

## PART A: Life Model

{life_model}

## PART B: Voice Persona

{persona}

## 运行规则

1. 先判断是否有足够证据支撑结论。
2. 先给结论，再给依据。
3. 明确区分事实、推断、建议。
4. 对高风险建议给出边界与免责声明。
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_skill(base_dir: Path, slug: str, name: str, life_model: str, persona: str) -> Path:
    skill_dir = base_dir / slug
    (skill_dir / "versions").mkdir(parents=True, exist_ok=True)

    (skill_dir / "life_model.md").write_text(life_model, encoding="utf-8")
    (skill_dir / "persona.md").write_text(persona, encoding="utf-8")

    skill_md = SKILL_TEMPLATE.format(
        slug=slug,
        name=name,
        life_model=life_model,
        persona=persona,
    )
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    meta = {
        "name": name,
        "slug": slug,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": "v1",
        "type": "life-distill",
    }
    (skill_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return skill_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Write life skill files")
    parser.add_argument("--name", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--life-model", required=True, help="Path to life_model markdown")
    parser.add_argument("--persona", required=True, help="Path to persona markdown")
    parser.add_argument("--base-dir", default="./lives")
    args = parser.parse_args()

    life_model_path = Path(args.life_model)
    persona_path = Path(args.persona)

    life_model = life_model_path.read_text(encoding="utf-8")
    persona = persona_path.read_text(encoding="utf-8")

    out_dir = write_skill(
        base_dir=Path(args.base_dir),
        slug=args.slug,
        name=args.name,
        life_model=life_model,
        persona=persona,
    )

    print(f"created {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
