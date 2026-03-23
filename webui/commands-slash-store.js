import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";
import { store as chatInputStore } from "/components/chat/input/input-store.js";
import { store as commandsManagerStore } from "/plugins/commands/webui/commands-store.js";

const COMMANDS_API_PATH = "/plugins/commands/commands";

function replaceAllLiteral(text, needle, replacement) {
  return String(text || "").split(needle).join(replacement);
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

function splitArguments(rawArguments) {
  const matches = String(rawArguments || "").match(/"[^"]*"|'[^']*'|\S+/g) || [];
  return matches.map((token) => token.replace(/^['"]|['"]$/g, ""));
}

function renderCommandTemplate(body, rawArguments) {
  const template = body || "";
  const argumentsText = String(rawArguments || "").trim();
  let rendered = template;
  const tokens = splitArguments(argumentsText);

  for (let index = 0; index < 10; index += 1) {
    rendered = replaceAllLiteral(rendered, `$${index}`, tokens[index] || "");
  }

  rendered = replaceAllLiteral(rendered, "$ARGUMENTS", argumentsText);

  rendered = rendered.trim();
  if (argumentsText && !template.includes("$ARGUMENTS")) {
    const suffix = `Arguments:\n${argumentsText}`;
    rendered = rendered ? `${rendered}\n\n${suffix}` : suffix;
  }

  return rendered.trim();
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

const model = {
  loading: false,
  commands: [],
  contextScope: { project_name: "", agent_profile: "" },
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

  async loadCommands(force = false) {
    const contextId =
      chatsStore?.getSelectedChatId?.() || globalThis.getContext?.() || "";

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
        agent_profile: "",
      };
      this.lastContextId = contextId;
      this.ensureSelection();
    } catch (error) {
      console.error("Failed to load effective commands:", error);
      this.commands = [];
      this.contextScope = { project_name: "", agent_profile: "" };
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
      this.applySelection(this.selectedCommand);
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

  applySelection(command) {
    if (!command) return;

    const rendered = renderCommandTemplate(command.body || "", this.rawArguments || "");
    const input = this.getInputElement();
    if (!input) return;

    input.value = rendered;
    chatInputStore.message = rendered;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    chatInputStore.adjustTextareaHeight();
    input.focus();
    input.setSelectionRange(rendered.length, rendered.length);

    this.active = false;
    this.dismissed = false;
    this.query = "";
    this.rawArguments = "";
    this.rawMessage = rendered;
    this.selectedIndex = 0;
  },

  openCreateCommand() {
    commandsManagerStore.openManager({
      projectName: this.contextScope?.project_name || "",
      agentProfile: this.contextScope?.agent_profile || "",
      prefillName: sanitizeCommandName(this.query || ""),
      openEditor: true,
    });
    this.dismissed = true;
  },
};

export const store = createStore("commandsSlash", model);
