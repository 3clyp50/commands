---
name: commands-create-slash-command
description: Create or update Agent Zero slash commands for the Commands plugin. Use when the user asks to add, edit, duplicate, or refine a reusable /command backed by a markdown file.
version: 1.0.0
tags: ["commands", "slash-commands", "plugin", "markdown"]
triggers:
  - create slash command
  - add slash command
  - update slash command
  - edit slash command
  - commands plugin
---

# Commands Plugin Slash Command Authoring

Use this skill when the user wants a reusable `/command` for Agent Zero's `commands` plugin.

## Source Of Truth

- Slash commands are markdown files, not database rows.
- Required frontmatter:
  - `name`
  - `description`
- Optional frontmatter:
  - `argument_hint`
- The body is the prompt text that will be inserted into the chat composer.
- Preserve any unknown frontmatter keys when editing an existing command.

## Scope Resolution

Choose the target folder from the requested scope:

- Global: `usr/plugins/commands/commands/`
- Project: `usr/projects/<project>/.a0proj/plugins/commands/commands/`
- Agent profile: `usr/agents/<profile>/plugins/commands/commands/`
- Project + agent profile: `usr/projects/<project>/.a0proj/agents/<profile>/plugins/commands/commands/`

If the user does not specify a scope, prefer the active chat scope when it is clear. Otherwise use the global scope.

## File Rules

- File name format: `<slug>.command.md`
- Slash command name should be lowercase and hyphenated, for example `explain-code`
- Keep the markdown body concise and directly reusable
- If the command expects trailing free-form input, include `$ARGUMENTS` or `$0`..`$9` in the body

Use the bundled template in `template.command.md` when creating a new command from scratch.

## Editing Workflow

1. Determine scope and final slash command name.
2. Check whether a command file already exists in that scope.
3. If it exists, load the file first and preserve unknown frontmatter keys.
4. Update the frontmatter and body.
5. Save the file in the correct scope folder.
6. Report:
   - the saved file path
   - the slash command name in `/name` form
   - a short note about supported trailing arguments if relevant

## Output Contract

After saving, explicitly state the final file path and the exact slash command invocation, for example:

- `Saved: /a0/usr/plugins/commands/commands/explain-code.command.md`
- `Invoke with: /explain-code`
