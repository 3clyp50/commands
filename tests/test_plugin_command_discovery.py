from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import cache, files, plugins
from usr.plugins.commands.helpers import commands as commands_helper


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_plugin_cache():
    """Ensure plugin list cache is fresh for every test."""
    cache.remove(plugins.PLUGINS_LIST_CACHE_AREA, "")
    yield
    cache.remove(plugins.PLUGINS_LIST_CACHE_AREA, "")


@pytest.fixture()
def fake_plugin():
    """Create a temporary plugin in usr/plugins/ with a commands/ directory."""
    suffix = uuid.uuid4().hex[:8]
    plugin_name = f"_test_cmd_disc_{suffix}"
    plugin_dir = files.get_abs_path(files.USER_DIR, files.PLUGINS_DIR, plugin_name)
    commands_dir = os.path.join(plugin_dir, "commands")
    os.makedirs(commands_dir, exist_ok=True)

    # Write plugin.yaml so the plugin is discoverable
    files.write_file(
        os.path.join(plugin_dir, "plugin.yaml"),
        f"name: {plugin_name}\ntitle: Test\ndescription: Test\n",
    )

    yield {"name": plugin_name, "dir": plugin_dir, "commands_dir": commands_dir}

    # Cleanup
    shutil.rmtree(plugin_dir, ignore_errors=True)
    cache.remove(plugins.PLUGINS_LIST_CACHE_AREA, "")


def _write_plugin_command(
    fake_plugin: dict,
    *,
    name: str,
    description: str,
    body: str = "default body",
) -> str:
    """Write a .command.yaml + .txt into the fake plugin's commands/ dir.

    Returns the config file path.
    """
    slug = commands_helper.sanitize_command_name(name)
    cdir = fake_plugin["commands_dir"]
    config_path = os.path.join(cdir, f"{slug}.command.yaml")
    content_path = os.path.join(cdir, f"{slug}.txt")

    files.write_file(
        config_path,
        f"name: {slug}\ndescription: {description}\ntype: text\ntemplate_path: {slug}.txt\n",
    )
    files.write_file(content_path, body)
    return config_path


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_discover_plugin_commands_finds_a0_agent_skills():
    """Real plugin a0_agent_skills has commands — they must be discovered."""
    discovered = commands_helper._discover_plugin_commands()
    names = {c["name"] for c in discovered}
    assert "build" in names, f"Expected 'build' in discovered names, got {names}"

    for cmd in discovered:
        if cmd["name"] == "build":
            assert cmd["source_plugin"] == "a0_agent_skills"
            assert cmd["source_scope_key"] == "plugin"
            assert "Plugin:" in cmd["source_scope_label"]
            break


def test_discover_plugin_commands_skips_own_plugin():
    """The commands plugin itself must NOT appear in _discover_plugin_commands."""
    discovered = commands_helper._discover_plugin_commands()
    for cmd in discovered:
        assert cmd.get("source_plugin") != "commands"


def test_list_effective_includes_plugin_commands():
    """list_effective_commands must include commands from other plugins."""
    effective, _ = commands_helper.list_effective_commands("")
    effective_names = {c["name"] for c in effective}
    assert "build" in effective_names


def test_plugin_commands_appear_in_effective_list(fake_plugin: dict):
    """Commands from a freshly-created plugin appear in effective list."""
    _write_plugin_command(
        fake_plugin,
        name=f"{fake_plugin['name']}-hello",
        description="A test command from a plugin",
        body="Hello from plugin",
    )

    effective, _ = commands_helper.list_effective_commands("")
    names = {c["name"] for c in effective}
    expected = commands_helper.sanitize_command_name(f"{fake_plugin['name']}-hello")
    assert expected in names


def test_precedence_global_overrides_plugin(fake_plugin: dict):
    """A global command with the same name takes precedence over a plugin command."""
    shared_name = f"{fake_plugin['name']}-shared"
    slug = commands_helper.sanitize_command_name(shared_name)

    # 1. Plugin command (lowest precedence)
    _write_plugin_command(
        fake_plugin,
        name=shared_name,
        description="plugin version",
        body="plugin body",
    )

    # 2. Global command (higher precedence)
    try:
        commands_helper.save_command(
            name=shared_name,
            description="global version",
            body="global body",
        )

        effective, _ = commands_helper.list_effective_commands("")
        by_name = {c["name"]: c for c in effective}
        assert slug in by_name
        assert by_name[slug]["description"] == "global version"
    finally:
        scope_dir = commands_helper.get_scope_directory("")
        files.delete_file(os.path.join(scope_dir, f"{slug}.command.yaml"))
        files.delete_file(os.path.join(scope_dir, f"{slug}.txt"))


def test_source_plugin_field_on_discovered_command(fake_plugin: dict):
    """Discovered commands must carry the source_plugin field."""
    _write_plugin_command(
        fake_plugin,
        name=f"{fake_plugin['name']}-src-test",
        description="source plugin test",
    )

    discovered = commands_helper._discover_plugin_commands()
    slug = commands_helper.sanitize_command_name(f"{fake_plugin['name']}-src-test")
    match = next((c for c in discovered if c["name"] == slug), None)
    assert match is not None
    assert match["source_plugin"] == fake_plugin["name"]
    assert match["source_scope_key"] == "plugin"


def test_is_plugin_commands_dir_recognises_plugin_path(fake_plugin: dict):
    """_is_plugin_commands_dir must return True for files inside plugin commands/ dirs."""
    _write_plugin_command(
        fake_plugin,
        name=f"{fake_plugin['name']}-path-check",
        description="path test",
    )
    slug = commands_helper.sanitize_command_name(f"{fake_plugin['name']}-path-check")
    config_path = os.path.join(fake_plugin["commands_dir"], f"{slug}.command.yaml")

    assert commands_helper._is_plugin_commands_dir(config_path) is True


def test_is_plugin_commands_dir_rejects_non_plugin_path():
    """_is_plugin_commands_dir must return False for arbitrary paths."""
    assert commands_helper._is_plugin_commands_dir("/tmp/not-a-plugin/commands/foo.txt") is False


def test_get_command_can_load_plugin_command(fake_plugin: dict):
    """get_command must work for commands inside plugin directories."""
    _write_plugin_command(
        fake_plugin,
        name=f"{fake_plugin['name']}-loadable",
        description="loadable test",
        body="load me",
    )
    slug = commands_helper.sanitize_command_name(f"{fake_plugin['name']}-loadable")
    config_path = os.path.join(fake_plugin["commands_dir"], f"{slug}.command.yaml")
    normalized = commands_helper._normalize_client_path(config_path)

    command = commands_helper.get_command(normalized)
    assert command["name"] == slug
    assert command["description"] == "loadable test"
    assert command["body"] == "load me"
