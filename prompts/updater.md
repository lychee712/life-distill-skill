# 人生 Skill 增量更新器

任务：在已有 Life Model 和 Voice Persona 基础上，调度 Merger 层完成材料整合与用户沟通纠错，完成全套状态变迁和版本追溯。
本模块与 `merger.md` 共享统一变更类型字典。

## 更新触发场景

1. **追加新材料**：导入新聊天记录、日记、备忘录。
2. **用户显式纠正**：反馈 "这不像我"、"偏离事实"。
3. **定期迭代扫描**。

## 统一变更类型字典

（同 Merger，必须按以下类型对变更进行装箱）
- `ADD` (新增)、`ENHANCE` (增强)、`CORRECT` (修正)、`CONFLICT` (冲突处理)、`DOWNGRADE` (降级)。

## 完整执行生命周期

### Step 1: Read & Parse
- 读取 `life_model.md`, `persona.md`, `CHANGELOG.md` (或 `meta.json`)。
- 获取所有现有结论与所挂载的 `[E序号|来源|时间]` 证据链，确保理解基线。

### Step 2: Analyzer & Diff (调用 Analyzer 工具链)
- 提取材料新结论与新证据号。
- Diff 后生成变更池。

### Step 3: User Interaction (冲突确认层)
向用户展示《增量更新预案报告》：
```
=== 更新预评估 (V1 -> V2) ===

[ADD] 识别到新的风险边界：从不上杠杆 (★★) [E编号]
[ENHANCE] 决策“防守型”样本激增，置信上升至 (★★★)
[CONFLICT⚠️] 发现存在矛盾的沟通反馈样本，是否覆盖旧记录？
```

### Step 4: Commit & Archive (强化增量可追溯性)

**归档旧版（严禁静默破坏）：**
```bash
cp lives/{slug}/life_model.md lives/{slug}/versions/v{N-1}_life_model.md
cp lives/{slug}/persona.md lives/{slug}/versions/v{N-1}_persona.md
```

**更新主模型：**
- 修改对应节点。
- 确保引入了新挂载的 `[E序号]`。

**写入 CHANGELOG：**
```markdown
## v{N} - {更新时间}

### 修改类型与摘要
- [CORRECT] 用户纠正：明确了“从不说脏话”为人设红线底线。
- [ADD] 引入了面向甲方的合作边界准则。

### 关联证据卷宗
涵盖新摄入证据：E30 - E45 (来源：备忘录导出库)
```
