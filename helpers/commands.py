from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

from agent import AgentContext
from helpers import files, plugins, projects, yaml as yaml_helper
from helpers.skills import split_frontmatter


PLUGIN_NAME = "commands"
COMMANDS_DIR = "commands"
COMMAND_FILE_SUFFIX = ".command.md"
STANDARD_FRONTMATTER_KEYS = {"name", "description", "argument_hint"}
_INVALID_COMMAND_CHARS_RE = re.compile(r"[^a-z0-9_-]+")
_MULTI_DASH_RE = re.compile(r"-{2,}")


def sanitize_command_name(raw_name: str) -> str:
    name = (raw_name or "").strip().lower().replace(" ", "-")
    name = _INVALID_COMMAND_CHARS_RE.sub("-", name)
    name = _MULTI_DASH_RE.sub("-", name).strip("-_")
    if not name:
        raise ValueError("Command name must contain at least one letter or number")
    return name


def command_file_name(command_name: str) -> str:
    return f"{sanitize_command_name(command_name)}{COMMAND_FILE_SUFFIX}"


def render_command_body(body: str, raw_arguments: str) -> str:
    template = body or ""
    arguments = (raw_arguments or "").strip()
    rendered = template
    tokens = _split_arguments(arguments)

    for index in range(10):
        rendered = rendered.replace(f"${index}", tokens[index] if index < len(tokens) else "")

    rendered = rendered.replace("$ARGUMENTS", arguments)
    rendered = rendered.strip()
    if arguments and "$ARGUMENTS" not in template:
        suffix = f"Arguments:\n{arguments}"
        rendered = f"{rendered}\n\n{suffix}" if rendered else suffix

    return rendered.strip()


def get_scope_key(project_name: str = "", agent_profile: str = "") -> str:
    if project_name and agent_profile:
        return "project_agent"
    if project_name:
        return "project"
    if agent_profile:
        return "agent"
    return "global"


def get_scope_label(project_name: str = "", agent_profile: str = "") -> str:
    scope_key = get_scope_key(project_name, agent_profile)
    if scope_key == "project_agent":
        return "Project + Agent"
    if scope_key == "project":
        return "Project"
    if scope_key == "agent":
        return "Agent"
    return "Global"


def get_scope_directory(project_name: str = "", agent_profile: str = "") -> str:
    return plugins.determine_plugin_asset_path(
        PLUGIN_NAME,
        project_name,
        agent_profile,
        COMMANDS_DIR,
    )


def ensure_scope_directory(project_name: str = "", agent_profile: str = "") -> str:
    directory = get_scope_directory(project_name, agent_profile)
    Path(directory).mkdir(parents=True, exist_ok=True)
    return directory


def get_scope_payload(
    project_name: str = "",
    agent_profile: str = "",
    *,
    ensure_directory: bool = False,
) -> dict[str, Any]:
    directory_path = (
        ensure_scope_directory(project_name, agent_profile)
        if ensure_directory
        else get_scope_directory(project_name, agent_profile)
    )
    return {
        "project_name": project_name,
        "agent_profile": agent_profile,
        "scope_key": get_scope_key(project_name, agent_profile),
        "scope_label": get_scope_label(project_name, agent_profile),
        "directory_path": _normalize_client_path(directory_path),
        "exists": os.path.isdir(directory_path),
        "_directory_abs_path": directory_path,
    }


def get_context_scope(context_id: str = "") -> dict[str, str]:
    context = _get_context(context_id)
    if not context:
        return {"project_name": "", "agent_profile": ""}

    return {
        "project_name": projects.get_context_project_name(context) or "",
        "agent_profile": context.agent0.config.profile or "",
    }


def list_scope_commands(
    project_name: str = "",
    agent_profile: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scope = get_scope_payload(project_name, agent_profile)
    commands = _load_scope_commands(project_name, agent_profile)
    overrides = _collect_lower_scope_matches(project_name, agent_profile)

    for command in commands:
        override_scopes = overrides.get(command["name"], [])
        command["override_scopes"] = override_scopes
        command["override_count"] = len(override_scopes)

    return commands, strip_private_scope(scope)


def list_effective_commands(
    project_name: str = "",
    agent_profile: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved_scope = get_scope_payload(project_name, agent_profile)
    merged: dict[str, dict[str, Any]] = {}

    for scope_project, scope_agent in _iter_precedence_scopes(project_name, agent_profile):
        commands = _load_scope_commands(scope_project, scope_agent)
        for command in commands:
            merged.setdefault(command["name"], command)

    effective = sorted(merged.values(), key=lambda item: item["name"])
    return effective, strip_private_scope(resolved_scope)


def get_command(
    path: str,
    project_name: str = "",
    agent_profile: str = "",
) -> dict[str, Any]:
    command_path = _validate_command_path(path, project_name, agent_profile)
    command = _load_command_file(
        command_path,
        project_name=project_name,
        agent_profile=agent_profile,
    )
    if not command:
        raise ValueError("Command file is invalid or missing required frontmatter")
    return command


def save_command(
    *,
    project_name: str = "",
    agent_profile: str = "",
    existing_path: str = "",
    name: str,
    description: str,
    argument_hint: str = "",
    body: str = "",
    extra_frontmatter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    command_name = sanitize_command_name(name)
    command_description = (description or "").strip()
    if not command_description:
        raise ValueError("Command description is required")

    scope_dir = ensure_scope_directory(project_name, agent_profile)
    target_path = files.get_abs_path(scope_dir, command_file_name(command_name))
    existing_abs_path = ""
    if existing_path:
        try:
            existing_abs_path = _validate_command_path(
                existing_path,
                project_name,
                agent_profile,
            )
        except FileNotFoundError:
            existing_abs_path = ""

    if existing_abs_path and not os.path.exists(existing_abs_path):
        existing_abs_path = ""

    if (
        os.path.exists(target_path)
        and not _paths_equal(target_path, existing_abs_path)
    ):
        raise FileExistsError(f'A command named "{command_name}" already exists in this scope')

    frontmatter = _build_frontmatter(
        name=command_name,
        description=command_description,
        argument_hint=argument_hint,
        extra_frontmatter=extra_frontmatter or {},
    )
    files.write_file(target_path, _build_command_markdown(frontmatter, body))

    if existing_abs_path and not _paths_equal(existing_abs_path, target_path):
        files.delete_file(existing_abs_path)

    return get_command(target_path, project_name, agent_profile)


def delete_command(
    path: str,
    project_name: str = "",
    agent_profile: str = "",
) -> None:
    command_path = _validate_command_path(path, project_name, agent_profile)
    files.delete_file(command_path)


def duplicate_command(
    path: str,
    project_name: str = "",
    agent_profile: str = "",
) -> dict[str, Any]:
    command = get_command(path, project_name, agent_profile)
    duplicated_name = _generate_duplicate_name(
        command["name"],
        project_name=project_name,
        agent_profile=agent_profile,
    )
    return save_command(
        project_name=project_name,
        agent_profile=agent_profile,
        name=duplicated_name,
        description=command["description"],
        argument_hint=command.get("argument_hint", ""),
        body=command.get("body", ""),
        extra_frontmatter=command.get("frontmatter_extra", {}),
    )


def _build_frontmatter(
    *,
    name: str,
    description: str,
    argument_hint: str,
    extra_frontmatter: dict[str, Any],
) -> dict[str, Any]:
    frontmatter: dict[str, Any] = {
        "name": name,
        "description": description,
    }
    clean_argument_hint = (argument_hint or "").strip()
    if clean_argument_hint:
        frontmatter["argument_hint"] = clean_argument_hint

    for key, value in (extra_frontmatter or {}).items():
        if key in STANDARD_FRONTMATTER_KEYS:
            continue
        frontmatter[key] = value

    return frontmatter


def _build_command_markdown(frontmatter: dict[str, Any], body: str) -> str:
    yaml_block = yaml_helper.dumps(frontmatter).strip()
    clean_body = (body or "").lstrip("\n").rstrip()
    content = f"---\n{yaml_block}\n---\n"
    if clean_body:
        content += f"\n{clean_body}\n"
    return content


def _generate_duplicate_name(
    command_name: str,
    *,
    project_name: str = "",
    agent_profile: str = "",
) -> str:
    base_name = sanitize_command_name(f"{command_name}-copy")
    candidate = base_name
    counter = 2
    scope_dir = ensure_scope_directory(project_name, agent_profile)

    while os.path.exists(files.get_abs_path(scope_dir, command_file_name(candidate))):
        candidate = f"{base_name}-{counter}"
        counter += 1

    return candidate


def _load_command_file(
    file_path: str,
    *,
    project_name: str = "",
    agent_profile: str = "",
) -> dict[str, Any] | None:
    try:
        content = files.read_file(file_path)
    except FileNotFoundError:
        return None

    frontmatter, body, errors = split_frontmatter(content)
    if errors:
        return None

    raw_name = str(frontmatter.get("name") or "").strip()
    description = str(frontmatter.get("description") or "").strip()
    if not raw_name or not description:
        return None

    try:
        command_name = sanitize_command_name(raw_name)
    except ValueError:
        return None

    argument_hint = str(frontmatter.get("argument_hint") or "").strip()
    extra_frontmatter = {
        key: value
        for key, value in frontmatter.items()
        if key not in STANDARD_FRONTMATTER_KEYS
    }

    directory_path = str(Path(file_path).parent)
    return {
        "name": command_name,
        "description": description,
        "argument_hint": argument_hint,
        "body": body,
        "path": _normalize_client_path(file_path),
        "directory_path": _normalize_client_path(directory_path),
        "project_name": project_name,
        "agent_profile": agent_profile,
        "scope_key": get_scope_key(project_name, agent_profile),
        "scope_label": get_scope_label(project_name, agent_profile),
        "source_scope_key": get_scope_key(project_name, agent_profile),
        "source_scope_label": get_scope_label(project_name, agent_profile),
        "frontmatter_extra": extra_frontmatter,
    }


def _validate_command_path(
    path: str,
    project_name: str = "",
    agent_profile: str = "",
) -> str:
    command_path = _to_abs_path(path)
    scope_root = get_scope_directory(project_name, agent_profile)
    if not files.is_in_dir(command_path, scope_root):
        raise ValueError("Command path is outside the selected scope")
    if not command_path.endswith(COMMAND_FILE_SUFFIX):
        raise ValueError("Command path must point to a .command.md file")
    if not os.path.exists(command_path):
        raise FileNotFoundError("Command file not found")
    return command_path


def _iter_precedence_scopes(project_name: str, agent_profile: str) -> list[tuple[str, str]]:
    scopes: list[tuple[str, str]] = []
    if project_name and agent_profile:
        scopes.append((project_name, agent_profile))
    if project_name:
        scopes.append((project_name, ""))
    if agent_profile:
        scopes.append(("", agent_profile))
    scopes.append(("", ""))
    return scopes


def _list_scope_files(scope_dir: str) -> list[str]:
    if not os.path.isdir(scope_dir):
        return []
    files_in_scope = [
        str(path)
        for path in Path(scope_dir).glob(f"*{COMMAND_FILE_SUFFIX}")
        if path.is_file()
    ]
    files_in_scope.sort(key=lambda item: Path(item).name.lower())
    return files_in_scope


def _load_scope_commands(
    project_name: str = "",
    agent_profile: str = "",
) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    scope_dir = get_scope_directory(project_name, agent_profile)

    for file_path in _list_scope_files(scope_dir):
        command = _load_command_file(
            file_path,
            project_name=project_name,
            agent_profile=agent_profile,
        )
        if command:
            commands.append(command)

    commands.sort(key=lambda item: item["name"])
    return commands


def _collect_lower_scope_matches(
    project_name: str = "",
    agent_profile: str = "",
) -> dict[str, list[str]]:
    lower_scope_matches: dict[str, list[str]] = {}

    for lower_project, lower_agent in _iter_precedence_scopes(project_name, agent_profile)[1:]:
        for command in _load_scope_commands(lower_project, lower_agent):
            lower_scope_matches.setdefault(command["name"], []).append(
                get_scope_label(lower_project, lower_agent)
            )

    return lower_scope_matches


def _normalize_client_path(path: str) -> str:
    return files.normalize_a0_path(path).replace("\\", "/")


def _paths_equal(path_a: str, path_b: str) -> bool:
    if not path_a or not path_b:
        return False
    return os.path.normcase(os.path.normpath(path_a)) == os.path.normcase(os.path.normpath(path_b))


def _split_arguments(raw_arguments: str) -> list[str]:
    if not raw_arguments:
        return []
    try:
        return shlex.split(raw_arguments)
    except ValueError:
        return raw_arguments.split()


def _get_context(context_id: str = "") -> AgentContext | None:
    if context_id:
        return AgentContext.get(context_id)
    return AgentContext.current() or AgentContext.first()


def _to_abs_path(path: str) -> str:
    return files.fix_dev_path(path)


def strip_private_scope(scope: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in scope.items() if not key.startswith("_")}


def _strip_private_scope(scope: dict[str, Any]) -> dict[str, Any]:
    return strip_private_scope(scope)
