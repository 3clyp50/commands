import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";
import { store as chatInputStore } from "/components/chat/input/input-store.js";
import {
  toastFrontendError,
  toastFrontendSuccess,
} from "/components/notifications/notification-store.js";
import { store as commandsManagerStore } from "/plugins/commands/webui/commands-store.js";

const COMMANDS_API_PATH = "/plugins/commands/commands";

function sanitizeCommandName(rawName) {
  return (rawName || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^[-_]+|[-_]+$/g, "");
}

function parseSlashInput(message) {
  const text = String(message || "");
  const match = text.match(/^\s*\/([^\s]*)(?:\s+([\s\S]*))?$/);
  if (!match) {
    return {
      active: false,
      query: "",
      rawArguments: "",
      rawMessage: text,
    };
  }

  return {
    active: true,
    query: (match[1] || "").trim().toLowerCase(),
    rawArguments: match[2] || "",
    rawMessage: text,
  };
}

function notifyError(message) {
  void toastFrontendError(message, "Commands");
}

function notifySuccess(message) {
  void toastFrontendSuccess(message, "Commands");
}

const model = {
  loading: false,
  applying: false,
  commands: [],
  contextScope: { project_name: "" },
  lastContextId: "",
  active: false,
  dismissed: false,
  query: "",
  rawArguments: "",
  rawMessage: "",
  selectedIndex: 0,
  boundInput: null,
  keydownHandler: null,
  inputHandler: null,
  focusHandler: null,
  commandsUpdatedHandler: null,

  get menuVisible() {
    return this.active && !this.dismissed;
  },

  get filteredCommands() {
    const needle = (this.query || "").trim().toLowerCase();
    const commands = Array.isArray(this.commands) ? this.commands : [];

    if (!needle) return commands;

    return commands.filter((command) => {
      const haystack = `${command?.name || ""} ${command?.description || ""}`.toLowerCase();
      return haystack.includes(needle);
    });
  },

  get selectedCommand() {
    const commands = this.filteredCommands;
    if (!commands.length) return null;
    return commands[this.selectedIndex] || commands[0] || null;
  },

  get emptyStateLabel() {
    const name = sanitizeCommandName(this.query || "");
    return name ? `Create /${name}` : "Create slash command";
  },

  get projectBadgeLabel() {
    const projectName = this.contextScope?.project_name || "";
    return projectName ? `Project: ${projectName}` : "Project: Global";
  },

  onMount() {
    this.ensureBindings();

    this.keydownHandler = (event) => this.handleKeydown(event);
    this.commandsUpdatedHandler = () => {
      this.commands = [];
      if (this.menuVisible) {
        void this.loadCommands(true);
      }
    };

    document.addEventListener("keydown", this.keydownHandler, true);
    window.addEventListener("commands:updated", this.commandsUpdatedHandler);
    this.handleInput();
  },

  cleanup() {
    this.removeBindings();
    if (this.keydownHandler) {
      document.removeEventListener("keydown", this.keydownHandler, true);
    }
    if (this.commandsUpdatedHandler) {
      window.removeEventListener("commands:updated", this.commandsUpdatedHandler);
    }
    this.keydownHandler = null;
    this.commandsUpdatedHandler = null;
    this.dismissed = false;
    this.active = false;
    this.query = "";
    this.rawArguments = "";
    this.rawMessage = "";
    this.selectedIndex = 0;
    this.applying = false;
  },

  ensureBindings() {
    const input = this.getInputElement();
    if (!input || input === this.boundInput) return;

    this.removeBindings();

    this.inputHandler = (event) => this.handleInput(event);
    this.focusHandler = () => this.handleInput();
    input.addEventListener("input", this.inputHandler);
    input.addEventListener("focus", this.focusHandler);
    this.boundInput = input;
  },

  removeBindings() {
    if (this.boundInput && this.inputHandler) {
      this.boundInput.removeEventListener("input", this.inputHandler);
    }
    if (this.boundInput && this.focusHandler) {
      this.boundInput.removeEventListener("focus", this.focusHandler);
    }
    this.boundInput = null;
    this.inputHandler = null;
    this.focusHandler = null;
  },

  getInputElement() {
    return document.getElementById("chat-input");
  },

  getContextId() {
    return chatsStore?.getSelectedChatId?.() || globalThis.getContext?.() || "";
  },

  async loadCommands(force = false) {
    const contextId = this.getContextId();

    if (!force && this.commands.length && contextId === this.lastContextId) {
      this.ensureSelection();
      return;
    }

    this.loading = true;
    try {
      const response = await callJsonApi(COMMANDS_API_PATH, {
        action: "list_effective",
        context_id: contextId,
      });
      this.commands = Array.isArray(response?.commands) ? response.commands : [];
      this.contextScope = response?.scope || {
        project_name: "",
      };
      this.lastContextId = contextId;
      this.ensureSelection();
    } catch (error) {
      console.error("Failed to load effective commands:", error);
      this.commands = [];
      this.contextScope = { project_name: "" };
    } finally {
      this.loading = false;
    }
  },

  handleInput(event = null) {
    this.ensureBindings();
    this.dismissed = false;

    const message =
      event?.target?.value ??
      this.getInputElement()?.value ??
      chatInputStore?.message ??
      "";
    const parsed = parseSlashInput(message);

    this.active = parsed.active;
    this.query = parsed.query;
    this.rawArguments = parsed.rawArguments;
    this.rawMessage = parsed.rawMessage;

    if (!this.active) {
      this.selectedIndex = 0;
      return;
    }

    this.ensureSelection();
    void this.loadCommands();
  },

  handleKeydown(event) {
    const input = this.getInputElement();
    if (!this.menuVisible || !input || document.activeElement !== input) return;
    if (event.isComposing || event.keyCode === 229) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      event.stopPropagation();
      this.moveSelection(1);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      event.stopPropagation();
      this.moveSelection(-1);
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this.dismissed = true;
      return;
    }

    if (event.key === "Enter" && this.selectedCommand) {
      event.preventDefault();
      event.stopPropagation();
      void this.applySelection(this.selectedCommand);
    }
  },

  ensureSelection() {
    const commands = this.filteredCommands;
    if (!commands.length) {
      this.selectedIndex = 0;
      return;
    }
    if (this.selectedIndex >= commands.length) {
      this.selectedIndex = 0;
    }
  },

  moveSelection(delta) {
    const commands = this.filteredCommands;
    if (!commands.length) return;
    const nextIndex =
      (this.selectedIndex + delta + commands.length) % commands.length;
    this.selectedIndex = nextIndex;
  },

  async applySelection(command) {
    if (!command || this.applying) return;
    const input = this.getInputElement();
    if (!input) return;

    this.applying = true;
    try {
      const contextId = this.getContextId();
      const fallbackSlash = this.rawMessage?.trim()
        ? this.rawMessage
        : this.rawArguments
          ? `/${command.name} ${this.rawArguments}`
          : `/${command.name}`;

      const response = await callJsonApi(COMMANDS_API_PATH, {
        action: "resolve",
        path: command.path,
        slash_text: fallbackSlash,
        project_name: this.contextScope?.project_name || "",
        context_id: contextId,
      });

      this.applyResolution(response?.resolution, input);
      notifySuccess(`Applied /${command.name}`);
    } catch (error) {
      console.error("Failed to apply slash command:", error);
      notifyError(error?.message || "Failed to apply slash command.");
    } finally {
      this.applying = false;
    }
  },

  applyResolution(resolution, input) {
    const result = resolution?.result || {};
    const hasText = typeof result.text === "string";
    let nextText = hasText ? result.text : input.value || "";
    const effects = Array.isArray(result.effects) ? result.effects : [];

    for (const effect of effects) {
      if (!effect || typeof effect !== "object") continue;
      const type = String(effect.type || "").trim().toLowerCase();
      if (type === "replace_input") {
        nextText = String(effect.text || "");
        continue;
      }
      if (type === "append_input") {
        const chunk = String(effect.text || "");
        nextText = nextText ? `${nextText}\n${chunk}` : chunk;
        continue;
      }
      if (type === "toast") {
        const level = String(effect.level || "info").toLowerCase();
        const message = String(effect.message || "");
        if (!message) continue;
        if (level === "error") {
          notifyError(message);
        } else {
          notifySuccess(message);
        }
      }
    }

    input.value = nextText;
    chatInputStore.message = nextText;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    chatInputStore.adjustTextareaHeight();
    input.focus();
    input.setSelectionRange(nextText.length, nextText.length);

    this.active = false;
    this.dismissed = false;
    this.query = "";
    this.rawArguments = "";
    this.rawMessage = nextText;
    this.selectedIndex = 0;
  },

  openCreateCommand() {
    commandsManagerStore.openManager({
      projectName: this.contextScope?.project_name || "",
      prefillName: sanitizeCommandName(this.query || ""),
      openEditor: true,
    });
    this.dismissed = true;
  },
};

export const store = createStore("commandsSlash", model);
