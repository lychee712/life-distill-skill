<div align="center">
# 活了吗.skill (Life Distill Skill)

[English](./README_EN.md) | [简体中文](./README.md)

> _"You LLM guys are like digital doctors. You saved frontend bros, backend bros, QA bros, ops bros, infosec bros, IC bros, and finally yourselves and the whole mankind."_

<p style="font-size:1.06em; color:#A33A00; font-weight:600;">Some are alive but already dead; some are gone yet still alive.</p>

<br>

<p style="font-size:1.08em; line-height:1.9; color:#2F3542;">
If you can't see yourself clearly yet, that's okay.<br>
Let Cyber Immortality, your professional <span style="color:#E65100; font-weight:700;">"code medic"</span>, pull you back online.<br><br>

Frontend is down, backend is down, QA is down, ops is down, infosec is down, IC is down...<br>
We've all gone through collective crashes under pressure.<br><br>

Now it's your turn, that half-offline version of you,<br>
to come back in <span style="color:#C62828; font-weight:700;">full-power mode</span>.<br><br>

🔥 Turn cold goodbyes into warm <span style="color:#D81B60; font-weight:700;">Skills</span>.<br>
Welcome to Cyber Immortality.<br>
We're not only trying to revive ourselves,<br>
we also want to pull humanity back from emotional downtime together 😂

</p>

🔥 **<span style="color:#D81B60; font-size:1.16em;">Turn cold goodbyes into warm Skills. Welcome to Cyber Immortality!</span>**

<br>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://python.org)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Skill-blueviolet)](https://claude.ai/code)
[![AgentSkills](https://img.shields.io/badge/AgentSkills-Standard-green)](https://agentskills.io)

⚠️ This project is solely for personal review and heritage distillation. It must not be used for harassment, stalking, or privacy infringement.

[Quick Start](#quick-start) · [Usage](#usage) · [Examples](#examples) · [Features](#features)

## </div>

## Quick Start

### Install Dependencies

The parser toolchain provided by this project may require certain dependencies (used when the Agent calls the parsing tools in the background):

```bash
pip install -r requirements.txt
```

Optional dependencies:

```bash
# Vector Search
pip install numpy faiss-cpu sentence-transformers

# PDF Parsing
pip install PyPDF2

# LLM Q&A
pip install openai
```

### Enable Skill in Agent (Recommended)

Load this directory as a Skill package or a standard Workspace into your preferred Agent tool (e.g., **OpenClaw** or **Claude Code**). Ensure the engine can read this project structure (especially the engine execution flow within the `prompts/` directory).

No command-line menu is needed. The whole process uses natural language interaction:

- Create: "Distill my life" / "Generate a life persona using my chat history"
- Update: "I have new chat history, please update this skill"
- Correct: "This doesn't sound like me" / "You misunderstood"

---

## Usage

### Agent Auto-Trigger

We have abandoned the cumbersome command-line parsing process. Simply wake it up directly within your Agent. All scheduling is native to the LLM's understanding.

**Recommended Prompts:**

- "Help me distill my life, here is my chat history export file /path/to/data"
- "Use the diary I uploaded to deduce my life's underlying code architecture"
- "I had an argument with my boss yesterday, here's my comeback record, please extract and incrementally update my Life Skill"
- "This doesn't sound like me. I would never lend money to someone I'm not close with. Please correct the Life Model."

**Agent Automated Execution Flow:**

1. **Material Gathering**: Recognizes the provided path or pasted text, calls the backend `tools/` parser (WeChat/Email/Doc) as needed.
2. **Analysis & Mining**: Dispatches `life_analyzer.md` and `persona_analyzer.md`, extracting elements using the unified evidence protocol.
3. **Architecture & Merging**: Dispatches `life_builder.md` to file a new project, or `updater.md`/`merger.md` for conflict-free or corrective incremental merging of existing archives.
4. **Quality Validation**: Executes the 4 logic gates (Gate A-D) defined in `validator.md` to block non-compliant outputs.
5. **Delivery & Archiving**: Finally generates or updates structured content to `lives/{slug}` and automatically maintains `CHANGELOG.md`.

---

## Examples

### 1) A friend asks to borrow money (Judgment of intimacy + personal funds)

Input A (Average relationship):
`A friend who hasn't contacted you for a long time suddenly messages: Lend me 20k, I'll pay you back at the end of the month.`

Output:
`(No reply)`
`Opens App Store, downloads a loan app`
`Opens TikTok, uses "Fangxin Jie" (a micro-loan service)`

Input B (Good relationship, but tight on cash):
`A good friend asks to borrow 20k, but your cash flow is tight this month.`

Output:
`I understand you're in a hurry now, but I really don't have the money.`
`My funds are tied up lately, I genuinely cannot afford this amount.`

### 2) Wanting to confess to a girl (Judgment of trust + current status)

Input A (Average relationship):
`I want to confess to XXX, is there a chance?`

Output:
`A simp will always be a simp. You'll end up with nothing.`

Input B (Close relationship):
`I want to confess to XXX, is there a chance?`

Output:
`You have a chance.`

---

## Version & Correction Management

When your digital avatar exhibits behavioral deviations, or you need it to revert to a past state:

**Just provide feedback via dialogue:**

- "View the version history of zhangsan"
- "Compare the current me with the v1 version of me, what is the difference in risk tolerance?"
- "You just forced a people-pleaser persona on me. That's not me, I just didn't want to argue for efficiency! Trigger CORRECT to fix it!"
- "Rollback to the previous version v2, the recent batch of corpus is too polluted."

(The Agent will automatically dispatch the corresponding logic and mechanisms in the Prompts to complete the downgrade or rollback.)

---

## Features

- **Dual-Structure Output**: Life Model (Underlying persona infrastructure) + Voice Persona (Behavior and expression mode).
- **Pure Dialogue Trigger**: Fully embraces Agent Native. No cumbersome Python CLI entry is needed.
- **Unified Evidence Traceability**: Every decision inference comes with a confidence threshold `(★★★)` and evidence reference `[E_ID]`.
- **Relationship Rating Analysis**: S+/S/A/B/C/D network social dimension strike.
- **Mandatory Compliance Gate**: Built-in Validator quality check funnel to prevent privacy leaks and hallucinations.
- **Advanced Incremental Control**: Supports state-marked merging and user high-priority explicit correction.

## Notes

- **Data Richness**: The quality of the chat history determines the fidelity. Multi-scenario data including contradiction handling is far superior to single daily perfunctory records.
- **Cautious Imagination**: If the material is extremely insufficient, the avatar should decisively answer "I don't know/Haven't encountered this", rather than generating LLM-native people-pleaser hallucinations.
- **Privacy Masking Tip**: The engine has a built-in masking gate, but users are strongly advised not to directly input highly sensitive account/password level data.

## License

MIT License
