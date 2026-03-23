from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
import sys

import pytest
from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import AgentContext
from helpers import files, projects, skills as skills_helper
from initialize import initialize_agent
from usr.plugins.commands.api.commands import Commands
from usr.plugins.commands.helpers import commands as commands_helper


@dataclass
class ScopeFixture:
    prefix: str
    project_name: str
    agent_profile: str
    created_paths: list[str] = field(default_factory=list)


def _track_command(scope: ScopeFixture, command: dict) -> dict:
    command_path = files.fix_dev_path(command["path"])
    if command_path not in scope.created_paths:
        scope.created_paths.append(command_path)
    return command


def _save_command(
    scope: ScopeFixture,
    *,
    project_name: str = "",
    agent_profile: str = "",
    name: str,
    description: str,
    body: str = "",
    argument_hint: str = "",
    extra_frontmatter: dict | None = None,
) -> dict:
    command = commands_helper.save_command(
        project_name=project_name,
        agent_profile=agent_profile,
        name=name,
        description=description,
        body=body,
        argument_hint=argument_hint,
        extra_frontmatter=extra_frontmatter or {},
    )
    return _track_command(scope, command)


@pytest.fixture
def scope_fixture() -> ScopeFixture:
    suffix = uuid.uuid4().hex[:8]
    scope = ScopeFixture(
        prefix=f"commands-test-{suffix}",
        project_name=f"commands_project_{suffix}",
        agent_profile=f"commands-agent-{suffix}",
    )

    yield scope

    for path in reversed(scope.created_paths):
        files.delete_file(path)

    files.delete_dir(files.get_abs_path("usr", "projects", scope.project_name))
    files.delete_dir(files.get_abs_path("usr", "agents", scope.agent_profile))


def _new_handler() -> Commands:
    app = Flask("commands_plugin_tests")
    app.secret_key = "commands-plugin-tests"
    return Commands(app, threading.RLock())


def test_command_file_name_and_unknown_frontmatter_round_trip(
    scope_fixture: ScopeFixture,
) -> None:
    command = _save_command(
        scope_fixture,
        name=f"Explain {scope_fixture.prefix}",
        description="Explain a code sample clearly.",
        body="Explain the sample.\n\n$ARGUMENTS",
        argument_hint="Paste code or describe the module.",
        extra_frontmatter={"category": "analysis", "audience": "team"},
    )

    command_path = Path(files.fix_dev_path(command["path"]))
    assert command_path.name == f"explain-{scope_fixture.prefix}.command.md"

    loaded = commands_helper.get_command(command["path"])
    assert loaded["frontmatter_extra"] == {
        "category": "analysis",
        "audience": "team",
    }

    markdown = files.read_file(str(command_path))
    assert "category: analysis" in markdown
    assert "audience: team" in markdown
    assert f"name: explain-{scope_fixture.prefix}" in markdown


def test_render_command_body_supports_placeholders() -> None:
    rendered = commands_helper.render_command_body(
        "Topic: $0\n\nEverything:\n$ARGUMENTS\n\nThird: $2",
        '"quoted phrase" alpha beta',
    )

    assert rendered == (
        'Topic: quoted phrase\n\nEverything:\n"quoted phrase" alpha beta\n\nThird: beta'
    )

    appended = commands_helper.render_command_body("Summarize this request.", "alpha beta")
    assert appended == "Summarize this request.\n\nArguments:\nalpha beta"

    literal_dollar = commands_helper.render_command_body(
        "Echo:\n$ARGUMENTS",
        "$1 literal",
    )
    assert literal_dollar == "Echo:\n$1 literal"


def test_list_effective_commands_respects_scope_precedence(
    scope_fixture: ScopeFixture,
) -> None:
    shared_name = f"{scope_fixture.prefix}-shared"

    _save_command(
        scope_fixture,
        name=shared_name,
        description="global description",
        body="global body",
    )
    _save_command(
        scope_fixture,
        project_name="",
        agent_profile=scope_fixture.agent_profile,
        name=shared_name,
        description="agent description",
        body="agent body",
    )
    _save_command(
        scope_fixture,
        project_name=scope_fixture.project_name,
        agent_profile="",
        name=shared_name,
        description="project description",
        body="project body",
    )
    _save_command(
        scope_fixture,
        project_name=scope_fixture.project_name,
        agent_profile=scope_fixture.agent_profile,
        name=shared_name,
        description="project+agent description",
        body="project+agent body",
    )

    project_agent_commands, _ = commands_helper.list_effective_commands(
        scope_fixture.project_name,
        scope_fixture.agent_profile,
    )
    project_commands, _ = commands_helper.list_effective_commands(
        scope_fixture.project_name,
        "",
    )
    agent_commands, _ = commands_helper.list_effective_commands(
        "",
        scope_fixture.agent_profile,
    )
    global_commands, _ = commands_helper.list_effective_commands("", "")

    assert {command["name"]: command for command in project_agent_commands}[shared_name][
        "description"
    ] == "project+agent description"
    assert {command["name"]: command for command in project_commands}[shared_name][
        "description"
    ] == "project description"
    assert {command["name"]: command for command in agent_commands}[shared_name][
        "description"
    ] == "agent description"
    assert {command["name"]: command for command in global_commands}[shared_name][
        "description"
    ] == "global description"

    scoped_commands, _ = commands_helper.list_scope_commands(
        scope_fixture.project_name,
        scope_fixture.agent_profile,
    )
    scoped_command = next(
        command for command in scoped_commands if command["name"] == shared_name
    )
    assert scoped_command["override_count"] == 3
    assert scoped_command["override_scopes"] == ["Project", "Agent", "Global"]


@pytest.mark.asyncio
async def test_commands_api_crud_and_context_scope_resolution(
    scope_fixture: ScopeFixture,
) -> None:
    handler = _new_handler()
    command_name = f"{scope_fixture.prefix}-context"

    global_command = _save_command(
        scope_fixture,
        name=command_name,
        description="global command",
        body="global body",
    )

    context = AgentContext(
        config=initialize_agent({"agent_profile": scope_fixture.agent_profile}),
        set_current=True,
    )
    context.set_data(projects.CONTEXT_DATA_KEY_PROJECT, scope_fixture.project_name)

    try:
        saved = await handler.process(
            {
                "action": "save",
                "project_name": scope_fixture.project_name,
                "agent_profile": scope_fixture.agent_profile,
                "name": command_name,
                "description": "context override",
                "body": "context body",
            },
            None,
        )
        assert isinstance(saved, dict)
        assert saved["ok"] is True
        saved_command = _track_command(scope_fixture, saved["command"])

        loaded = await handler.process(
            {
                "action": "get",
                "project_name": scope_fixture.project_name,
                "agent_profile": scope_fixture.agent_profile,
                "path": saved_command["path"],
            },
            None,
        )
        assert isinstance(loaded, dict)
        assert loaded["command"]["description"] == "context override"

        duplicated = await handler.process(
            {
                "action": "duplicate",
                "project_name": scope_fixture.project_name,
                "agent_profile": scope_fixture.agent_profile,
                "path": saved_command["path"],
            },
            None,
        )
        assert isinstance(duplicated, dict)
        assert duplicated["ok"] is True
        assert duplicated["command"]["name"].startswith(f"{command_name}-copy")
        duplicated_command = _track_command(scope_fixture, duplicated["command"])

        scoped_list = await handler.process(
            {
                "action": "list_scope",
                "project_name": scope_fixture.project_name,
                "agent_profile": scope_fixture.agent_profile,
            },
            None,
        )
        assert isinstance(scoped_list, dict)
        scoped_names = {command["name"] for command in scoped_list["commands"]}
        assert saved_command["name"] in scoped_names
        assert duplicated_command["name"] in scoped_names

        effective_list = await handler.process(
            {"action": "list_effective", "context_id": context.id},
            None,
        )
        assert isinstance(effective_list, dict)
        effective_by_name = {
            command["name"]: command for command in effective_list["commands"]
        }
        assert effective_by_name[command_name]["description"] == "context override"
        assert effective_by_name[command_name]["source_scope_key"] == "project_agent"

        scope_info = await handler.process(
            {"action": "scope_info", "context_id": context.id},
            None,
        )
        assert isinstance(scope_info, dict)
        assert scope_info["scope"]["project_name"] == scope_fixture.project_name
        assert scope_info["scope"]["agent_profile"] == scope_fixture.agent_profile

        deleted = await handler.process(
            {
                "action": "delete",
                "project_name": scope_fixture.project_name,
                "agent_profile": scope_fixture.agent_profile,
                "path": duplicated_command["path"],
            },
            None,
        )
        assert isinstance(deleted, dict)
        assert deleted["ok"] is True

        after_delete = await handler.process(
            {
                "action": "list_scope",
                "project_name": scope_fixture.project_name,
                "agent_profile": scope_fixture.agent_profile,
            },
            None,
        )
        assert isinstance(after_delete, dict)
        assert duplicated_command["name"] not in {
            command["name"] for command in after_delete["commands"]
        }
        assert global_command["name"] == command_name
    finally:
        AgentContext.remove(context.id)
        AgentContext.set_current("")


def test_plugin_scoped_skill_is_discoverable() -> None:
    skill = skills_helper.find_skill("commands-create-slash-command")
    assert skill is not None
    assert skill.skill_md_path.as_posix().endswith(
        "usr/plugins/commands/skills/commands-create-slash-command/SKILL.md"
    )
