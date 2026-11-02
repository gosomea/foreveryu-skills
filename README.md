# foreveryu-skills

Personal collection of Agent skills (Claude Code / DeepSeek Harness compatible).

Each directory under `skills/` is a self-contained skill with a `SKILL.md`.

## Skills

| Skill | Description |
| --- | --- |
| [dsh-plugin-isolated-test](./skills/dsh-plugin-isolated-test/) | Test DeepSeek Harness plugins against real behavior with layered isolation (unit → package → profile composition → real host → browser UI), without disturbing the daily running instance. Includes an environment registry script and a step-by-step runbook. |

## Usage

Copy (or symlink) a skill directory into your agent's skills location, e.g. `.agents/skills/` for DeepSeek Harness or `~/.claude/skills/` for Claude Code. See each skill's `SKILL.md` for details.

## License

MIT
