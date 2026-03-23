import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import {
  toastFrontendError,
  toastFrontendSuccess,
} from "/components/notifications/notification-store.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";
import { store as fileBrowserStore } from "/components/modals/file-browser/file-browser-store.js";

const COMMANDS_API_PATH = "/plugins/commands/commands";
const MAIN_MODAL_PATH = "/plugins/commands/webui/main.html";
const EDITOR_MODAL_PATH = "/plugins/commands/webui/editor.html";

function createEmptyEditor() {
  return {
    mode: "create",
    existingPath: "",
    path: "",
    name: "",
    description: "",
    argumentHint: "",
    body: "",
    extraFrontmatter: {},
  };
}

function safeStringify(value) {
  try {
    return JSON.stringify(value ?? {});
  } catch {
    return "";
  }
}

function sanitizeCommandName(rawName) {
  return (rawName || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^[-_]+|[-_]+$/g, "");
}

function buildDefaultBody() {
  return "Describe the work to perform here.\n\n$ARGUMENTS";
}

function notifyError(message) {
  void toastFrontendError(message, "Commands");
}

function notifySuccess(message) {
  void toastFrontendSuccess(message, "Commands");
}

function emitCommandsUpdated() {
  window.dispatchEvent(new CustomEvent("commands:updated"));
}

const model = {
  loading: false,
  saving: false,
  projects: [],
  agentProfiles: [],
  projectName: "",
  agentProfile: "",
  scope: null,
  contextScope: { project_name: "", agent_profile: "" },
  commands: [],
  pendingScope: null,
  pendingCreate: null,
  editor: createEmptyEditor(),
  editorSnapshot: "",

  get selectedScopeLabel() {
    return this.scope?.scope_label || "Global";
  },

  get selectedScopeDirectory() {
    return this.scope?.directory_path || "";
  },

  get hasCommands() {
    return (this.commands || []).length > 0;
  },

  get editorTitle() {
    return this.editor.mode === "edit" ? "Edit Slash Command" : "Create Slash Command";
  },

  get editorDirty() {
    return this._serializeEditor() !== this.editorSnapshot;
  },

  openManager(options = {}) {
    const hasExplicitScope =
      Object.prototype.hasOwnProperty.call(options, "projectName") ||
      Object.prototype.hasOwnProperty.call(options, "agentProfile");

    this.pendingScope = hasExplicitScope
      ? {
          projectName: options.projectName || "",
          agentProfile: options.agentProfile || "",
        }
      : null;

    this.pendingCreate =
      options.openEditor || options.prefillName
        ? {
            name: options.prefillName || "",
          }
        : null;

    return window.openModal?.(MAIN_MODAL_PATH);
  },

  async onOpen() {
    await Promise.all([this.loadProjects(), this.loadAgentProfiles()]);

    try {
      await this.resolveInitialScope();
      await this.loadCommands();
    } catch (error) {
      console.error("Failed to initialize commands manager:", error);
      this.scope = null;
      this.commands = [];
      notifyError(error?.message || "Failed to open the commands manager.");
    }

    if (this.pendingCreate) {
      const pendingCreate = { ...this.pendingCreate };
      this.pendingCreate = null;
      await this.openCreateCommand({ name: pendingCreate.name });
    }
  },

  cleanup() {
    this.loading = false;
    this.saving = false;
    this.projects = [];
    this.agentProfiles = [];
    this.projectName = "";
    this.agentProfile = "";
    this.scope = null;
    this.contextScope = { project_name: "", agent_profile: "" };
    this.commands = [];
    this.pendingScope = null;
    this.pendingCreate = null;
    this.resetEditor();
  },

  async loadProjects() {
    try {
      const response = await callJsonApi("projects", { action: "list_options" });
      this.projects = Array.isArray(response?.data) ? response.data : [];
    } catch {
      this.projects = [];
    }
  },

  async loadAgentProfiles() {
    try {
      const response = await callJsonApi("agents", { action: "list" });
      this.agentProfiles = Array.isArray(response?.data) ? response.data : [];
    } catch {
      this.agentProfiles = [];
    }
  },

  normalizeProject(projectName) {
    if (!projectName) return "";
    return (this.projects || []).some((project) => project?.key === projectName)
      ? projectName
      : "";
  },

  normalizeAgentProfile(agentProfile) {
    if (!agentProfile) return "";
    return (this.agentProfiles || []).some((profile) => profile?.key === agentProfile)
      ? agentProfile
      : "";
  },

  async resolveInitialScope() {
    const contextId =
      chatsStore?.getSelectedChatId?.() || globalThis.getContext?.() || "";
    const scopeInfo = await callJsonApi(COMMANDS_API_PATH, {
      action: "scope_info",
      context_id: contextId,
    });

    this.contextScope = scopeInfo?.context_scope || {
      project_name: "",
      agent_profile: "",
    };

    const preferredScope = this.pendingScope || scopeInfo?.scope || {};
    this.projectName = this.normalizeProject(preferredScope.project_name || "");
    this.agentProfile = this.normalizeAgentProfile(
      preferredScope.agent_profile || "",
    );
    this.pendingScope = null;
  },

  async loadCommands() {
    this.loading = true;

    try {
      const response = await callJsonApi(COMMANDS_API_PATH, {
        action: "list_scope",
        project_name: this.projectName || "",
        agent_profile: this.agentProfile || "",
      });

      this.commands = Array.isArray(response?.commands) ? response.commands : [];
      this.scope = response?.scope || null;
    } catch (error) {
      console.error("Failed to load commands:", error);
      this.commands = [];
      this.scope = null;
      notifyError(error?.message || "Failed to load commands.");
    } finally {
      this.loading = false;
    }
  },

  async refresh() {
    await this.loadCommands();
  },

  async onScopeChanged() {
    this.projectName = this.normalizeProject(this.projectName);
    this.agentProfile = this.normalizeAgentProfile(this.agentProfile);
    await this.loadCommands();
  },

  overrideBadgeLabel(command) {
    const count = Number(command?.override_count || 0);
    if (!count) return "";
    if (count === 1) {
      return `Overrides ${command.override_scopes[0]}`;
    }
    return `Overrides ${count} lower scopes`;
  },

  async browseScopeFolder() {
    try {
      const response = await callJsonApi(COMMANDS_API_PATH, {
        action: "scope_info",
        project_name: this.projectName || "",
        agent_profile: this.agentProfile || "",
        ensure_directory: true,
      });
      if (response?.scope?.directory_path) {
        await fileBrowserStore.open(response.scope.directory_path);
      }
    } catch (error) {
      console.error("Failed to open scope folder:", error);
      notifyError(error?.message || "Failed to open scope folder.");
    }
  },

  async openCreateCommand(options = {}) {
    if (Object.prototype.hasOwnProperty.call(options, "projectName")) {
      this.projectName = this.normalizeProject(options.projectName || "");
    }
    if (Object.prototype.hasOwnProperty.call(options, "agentProfile")) {
      this.agentProfile = this.normalizeAgentProfile(options.agentProfile || "");
    }

    if (
      Object.prototype.hasOwnProperty.call(options, "projectName") ||
      Object.prototype.hasOwnProperty.call(options, "agentProfile")
    ) {
      await this.loadCommands();
    }

    const suggestedName = sanitizeCommandName(options.name || "");
    this.editor = {
      ...createEmptyEditor(),
      mode: "create",
      name: suggestedName,
      body: buildDefaultBody(),
    };
    this.editorSnapshot = this._serializeEditor();
    await this.openEditorModal();
  },

  async openEditCommand(command) {
    if (!command?.path) return;

    try {
      const response = await callJsonApi(COMMANDS_API_PATH, {
        action: "get",
        path: command.path,
        project_name: this.projectName || "",
        agent_profile: this.agentProfile || "",
      });
      const loaded = response?.command || command;
      this.editor = {
        mode: "edit",
        existingPath: loaded.path || "",
        path: loaded.path || "",
        name: loaded.name || "",
        description: loaded.description || "",
        argumentHint: loaded.argument_hint || "",
        body: loaded.body || "",
        extraFrontmatter: loaded.frontmatter_extra || {},
      };
      this.editorSnapshot = this._serializeEditor();
      await this.openEditorModal();
    } catch (error) {
      console.error("Failed to load command:", error);
      notifyError(error?.message || "Failed to load command.");
    }
  },

  async duplicateCommand(command) {
    if (!command?.path) return;

    try {
      const response = await callJsonApi(COMMANDS_API_PATH, {
        action: "duplicate",
        path: command.path,
        project_name: this.projectName || "",
        agent_profile: this.agentProfile || "",
      });
      await this.loadCommands();
      emitCommandsUpdated();
      notifySuccess(`Duplicated /${response?.command?.name || command.name}`);
      if (response?.command) {
        await this.openEditCommand(response.command);
      }
    } catch (error) {
      console.error("Failed to duplicate command:", error);
      notifyError(error?.message || "Failed to duplicate command.");
    }
  },

  async deleteCommand(command) {
    if (!command?.path) return;

    try {
      await callJsonApi(COMMANDS_API_PATH, {
        action: "delete",
        path: command.path,
        project_name: this.projectName || "",
        agent_profile: this.agentProfile || "",
      });
      await this.loadCommands();
      emitCommandsUpdated();
      notifySuccess(`Deleted /${command.name}`);
    } catch (error) {
      console.error("Failed to delete command:", error);
      notifyError(error?.message || "Failed to delete command.");
    }
  },

  async openEditorModal() {
    await window.openModal?.(EDITOR_MODAL_PATH, () => this.confirmCloseEditor());
    this.resetEditor();
  },

  confirmCloseEditor() {
    if (!this.editorDirty) return true;
    return window.confirm("Discard unsaved slash command changes?");
  },

  async closeEditor() {
    await window.closeModal?.(EDITOR_MODAL_PATH);
  },

  async saveEditor() {
    this.saving = true;

    try {
      const response = await callJsonApi(COMMANDS_API_PATH, {
        action: "save",
        project_name: this.projectName || "",
        agent_profile: this.agentProfile || "",
        existing_path: this.editor.existingPath || "",
        name: this.editor.name || "",
        description: this.editor.description || "",
        argument_hint: this.editor.argumentHint || "",
        body: this.editor.body || "",
        extra_frontmatter: this.editor.extraFrontmatter || {},
      });

      this.editor.path = response?.command?.path || "";
      this.editor.existingPath = response?.command?.path || "";
      this.editorSnapshot = this._serializeEditor();
      await this.loadCommands();
      emitCommandsUpdated();
      notifySuccess(
        `${this.editor.mode === "edit" ? "Updated" : "Saved"} /${response?.command?.name || this.editor.name}`,
      );
      await window.closeModal?.(EDITOR_MODAL_PATH);
    } catch (error) {
      console.error("Failed to save command:", error);
      notifyError(error?.message || "Failed to save command.");
    } finally {
      this.saving = false;
    }
  },

  resetEditor() {
    this.editor = createEmptyEditor();
    this.editorSnapshot = this._serializeEditor();
  },

  _serializeEditor() {
    return safeStringify({
      existingPath: this.editor.existingPath || "",
      name: this.editor.name || "",
      description: this.editor.description || "",
      argumentHint: this.editor.argumentHint || "",
      body: this.editor.body || "",
      extraFrontmatter: this.editor.extraFrontmatter || {},
    });
  },
};

export const store = createStore("commandsManager", model);
