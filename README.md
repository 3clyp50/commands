# Commands

Markdown-backed slash commands for Agent Zero.

This plugin lets you define reusable `/commands` as `.command.md` files, manage them from a dedicated modal, and insert them directly from the main chat composer when the first token starts with `/`.

## Features

- Markdown files are the source of truth, with YAML frontmatter for command metadata
- Structured command manager with create, edit, duplicate, delete, refresh, and scope browsing
- Slash picker above the inline composer with keyboard navigation and create-on-empty flow
- Scope-aware command resolution across global, project, agent profile, and project+agent layers
- Plugin-scoped skill so Agent Zero can create or update slash commands for you

## Command File Format

```md
---
name: explain-code
description: Explain code clearly with examples
argument_hint: Optional free-form text after /explain-code
---
Explain the following:

$ARGUMENTS
```

Supported placeholders:

- `$ARGUMENTS`
- `$0` through `$9`

If a command body omits `$ARGUMENTS`, the typed tail is appended automatically as:

```md
Arguments:
<typed text>
```

## Scope Resolution

Commands are discovered from these scope folders:

- Global: `usr/plugins/commands/commands/`
- Project: `usr/projects/<project>/.a0proj/plugins/commands/commands/`
- Agent profile: `usr/agents/<profile>/plugins/commands/commands/`
- Project + agent profile: `usr/projects/<project>/.a0proj/agents/<profile>/plugins/commands/commands/`

Precedence in the chat picker:

1. Project + agent
2. Project
3. Agent profile
4. Global

## UI Surfaces

- Plugin modal: open the Commands manager from the Plugins dialog
- Sidebar quick action: terminal icon next to the Plugins button
- Chat composer: type `/` at the start of the inline input to browse commands

## Agent Skill

The plugin ships with `commands-create-slash-command`, a plugin-scoped skill that helps Agent Zero create or update command files while preserving unknown frontmatter keys.

## Development

Run the plugin test file with:

```bash
pytest usr/plugins/commands/tests/test_commands_plugin.py -q
```

When publishing this plugin as its own repository, place the contents of this folder at the repository root so `plugin.yaml`, `README.md`, and `LICENSE` sit at the top level.
