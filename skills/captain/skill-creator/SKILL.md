---
name: skill-creator
description: Create new skills for any agent in this multi-agent system. Use this skill whenever you need to extract, generate, or write a new skill — whether from a conversation workflow, a user request, a web resource, or an existing task pattern. Always use this skill when creating skills, so they follow Claude Code standard format with proper YAML frontmatter, SKILL.md, and metadata.json.
---

# Skill Creator

A captain-level skill for creating new skills and adding them to the HyperAgents skill library.

Use this skill whenever:
- A user asks to "learn" or "extract" a skill from something
- You recognize a repeated workflow pattern worth capturing
- You finish a task and want to save the approach as a reusable skill
- A user asks you to create a skill from scratch

---

## Skill File Structure (Claude Code Standard)

Every skill must follow this exact layout:

```
skills/<agent-name>/<skill-name>/
├── SKILL.md          (required — YAML frontmatter + instructions)
├── metadata.json     (required — skill registry entry)
└── examples/         (optional — example inputs/outputs)
```

### SKILL.md format

```markdown
---
name: <skill-name>
description: <one-sentence trigger description — see below>
---

# <Skill Title>

Brief overview of what this skill does and when to use it.

## Steps

1. Step one
2. Step two
3. Step three

## Examples

...
```

### metadata.json format

```json
{
  "id": "<skill-name>",
  "name": "<skill-name>",
  "agent": "<agent-name>",
  "created_at": "<ISO 8601 timestamp>",
  "source": "skill_creator",
  "source_url": "",
  "usage_count": 0,
  "success_count": 0,
  "last_used": null
}
```

---

## Step 1: Capture Intent

Understand what the skill should do. If the user says "turn this into a skill" or "learn this", extract the workflow from the current conversation. Otherwise, ask:

1. What should this skill enable the agent to do?
2. Which agent should own it? (captain / pm / researcher / analyst / developer / auditor)
3. When should it trigger — what user phrases or contexts?
4. What is the expected output?

If extracting from conversation history: identify the tools used, the sequence of steps, any corrections the user made, and the input/output formats.

## Step 2: Choose the Agent Owner

Map the skill to the right agent role:

| Agent      | Skills for...                                      |
|------------|----------------------------------------------------|
| captain    | Orchestration, delegation, meta-tasks, skill mgmt  |
| pm         | Planning, requirements, roadmaps, coordination     |
| researcher | Web search, information gathering, summarization   |
| analyst    | Data analysis, evaluation, reporting               |
| developer  | Code writing, debugging, implementation            |
| auditor    | Code review, quality checks, security audits       |

## Step 3: Write the SKILL.md

### Description field (most important)

The `description` field in the YAML frontmatter is the primary trigger mechanism. Write it to be specific and slightly "pushy" — include both what the skill does AND concrete trigger contexts:

**Bad:** `"How to analyze data."`

**Good:** `"Analyze datasets, generate reports, and surface insights. Use whenever the user shares a CSV, asks about data patterns, mentions metrics or KPIs, or wants to understand numbers — even if they don't say 'analyze'."`

### Skill body

- Use imperative form: "Run X", "Check Y", "Save Z"
- Explain *why* behind each step, not just *what*
- Keep SKILL.md under 500 lines
- Include concrete examples where helpful

## Step 4: Write the metadata.json

Use the current ISO 8601 timestamp. Set `agent` to the owner agent name. Set `source` to `"skill_creator"`.

## Step 5: Save the Files

Save to:
```
d:\a2a-agents\skills\<agent-name>\<skill-name>\SKILL.md
d:\a2a-agents\skills\<agent-name>\<skill-name>\metadata.json
```

Use kebab-case for `<skill-name>` (e.g., `analyze-discord-logs`, `generate-weekly-report`).

## Step 6: Confirm

Tell the user:
- Where the skill was saved
- Which agent owns it
- What phrase/context triggers it
- Offer to test it or refine the description

---

## Quality Checklist

Before saving, verify:

- [ ] YAML frontmatter has `name` and `description`
- [ ] `description` includes trigger contexts (not just what it does)
- [ ] Skill body uses imperative form
- [ ] Steps are clear and ordered
- [ ] `metadata.json` has correct `agent` field
- [ ] Saved to correct path under `skills/<agent>/`
- [ ] Skill name is kebab-case

---

## Examples

**Example 1: Extract from conversation**

User: "That approach of checking Discord logs then summarizing — save that as a skill for the analyst."

→ Skill name: `analyze-discord-logs`, agent: `analyst`
→ Extract the steps performed in the conversation into SKILL.md
→ Write metadata.json with `"agent": "analyst"`

**Example 2: Create from scratch**

User: "Teach the researcher how to find GitHub issues related to a bug report."

→ Skill name: `find-related-github-issues`, agent: `researcher`
→ Write SKILL.md with steps: search GitHub, filter by relevance, summarize findings
→ Write metadata.json

**Example 3: Learn from a URL**

User: "Learn this technique: https://..."

→ Use WebFetch to read the page
→ Distill the technique into SKILL.md steps
→ Determine appropriate agent owner
→ Save with metadata.json
