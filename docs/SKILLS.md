# Allpath Skills

Skills are reusable instruction packages for the Agent. They are different from the Onboarding Curriculum: Skills teach the Agent how to perform a task; Curriculum teaches the user what Allpath can do.

## Discovery layers

Later layers override earlier layers with the same skill name:

1. packaged built-in Skills;
2. `~/.allpath-agent/skills/` user Skills;
3. `<workspace>/.allpath/skills/` project Skills.

Each Skill is a directory containing `SKILL.md` with YAML frontmatter:

```markdown
---
name: my-skill
description: Explain when this Skill should be used.
---

# Instructions
```

Supporting files may live under `references/`, `templates/`, `scripts/`, or `assets/`.

## Progressive disclosure

- `skills_list` returns only name, description, and source.
- `skill_view` loads the full `SKILL.md` or one safe relative supporting file.
- `/skills` lists discoverable Skills in the CLI.
- `/skill-name optional instruction` embeds the selected Skill into the current user turn without changing the system prompt.

Paths, symlinks, binary content, and 100,000-byte limits are checked before loading.

## Built-in Skills

- `/repository-analysis`
- `/connector-setup`
- `/create-automation`

This follows Hermes's progressive-disclosure lesson while keeping Allpath's initial format and management surface deliberately small.
