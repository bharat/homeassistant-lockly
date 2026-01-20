const DEFAULT_TITLE = "Lockly";
const RESOURCE_URL = import.meta.url;
const CARD_VERSION = new URL(RESOURCE_URL).searchParams.get("v") || "0.0.0";
// eslint-disable-next-line no-console
console.info(`Lockly card module loaded from ${RESOURCE_URL}`);
const WS_VERSION_TYPE = "lockly/version";
const WS_CONFIG_TYPE = "lockly/config";
const WS_ENTRIES_TYPE = "lockly/entries";
const RESOURCE_LOG_KEY = "lockly_resource_logged";

class LocklyCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this.appendChild(this._card);
    }
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._config) {
      this._render();
    }
    this._notifyResourceLoaded();
  }

  connectedCallback() {
    if (this._hass && !this._versionChecked) {
      this._versionChecked = true;
      this._checkVersion();
    }
    if (this._hass && !this._configChecked && this._config?.entry_id) {
      this._configChecked = true;
      this._fetchConfig();
    }
  }

  getCardSize() {
    return 3;
  }

  async _checkVersion() {
    if (!this._hass || !this._hass.connection) {
      return;
    }
    try {
      const response = await this._hass.connection.sendMessagePromise({
        type: WS_VERSION_TYPE,
      });
      const backendVersion = response?.version || "0.0.0";
      if (backendVersion !== CARD_VERSION) {
        this._showVersionMismatch(backendVersion);
      }
    } catch (err) {
      // Ignore version checks if the backend is not ready.
      // eslint-disable-next-line no-console
      console.debug("Lockly version check skipped", err);
    }
  }

  async _fetchConfig() {
    if (!this._config?.entry_id) {
      return;
    }
    if (!this._hass || !this._hass.connection) {
      return;
    }
    try {
      const response = await this._hass.connection.sendMessagePromise({
        type: WS_CONFIG_TYPE,
        entry_id: this._config.entry_id,
      });
      this._groupEntityId = response?.group_entity_id || null;
      this._groupName = response?.group_name || null;
      this._render();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.debug("Lockly config fetch skipped", err);
    }
  }

  _showVersionMismatch(backendVersion) {
    const message = `Lockly update detected. Backend: ${backendVersion}, frontend: ${CARD_VERSION}.`;
    this.dispatchEvent(
      new CustomEvent("hass-notification", {
        detail: {
          message,
          duration: -1,
          dismissable: true,
          action: {
            text: "Reload",
            action: () => this._handleReload(),
          },
        },
        bubbles: true,
        composed: true,
      })
    );
  }

  _notifyResourceLoaded() {
    if (!this._hass || !this._hass.connection) {
      return;
    }
    if (sessionStorage.getItem(RESOURCE_LOG_KEY)) {
      return;
    }
    sessionStorage.setItem(RESOURCE_LOG_KEY, "1");
    // eslint-disable-next-line no-console
    console.info(`Lockly card loaded (${CARD_VERSION}) from ${RESOURCE_URL}`);
  }

  async _handleReload() {
    if ("caches" in window) {
      const cacheNames = await caches.keys();
      await Promise.all(cacheNames.map((name) => caches.delete(name)));
    }
    window.location.reload();
  }

  _getSlots() {
    const states = Object.values(this._hass.states || {});
    const slotEntities = states.filter(
      (state) =>
        state.attributes &&
        state.attributes.lockly_entry_id === this._config.entry_id &&
        state.attributes.lockly_slot !== undefined
    );
    return slotEntities
      .map((entity) => ({
        id: Number(entity.attributes.lockly_slot),
        entity_id: entity.entity_id,
        name: entity.attributes.name || "",
        pin: entity.attributes.pin || "",
        enabled: Boolean(entity.attributes.enabled),
        busy: Boolean(entity.attributes.busy),
      }))
      .sort((a, b) => a.id - b.id);
  }

  _render() {
    if (!this._hass || !this._card) {
      return;
    }
    if (!this._config.entry_id) {
      this._card.innerHTML = `
        <div class="card-content">
          Lockly card requires an entry_id.
        </div>
      `;
      return;
    }
    const title =
      this._config.title || this._getDefaultTitle() || DEFAULT_TITLE;
    const slots = this._getSlots();
    this._card.innerHTML = `
      <style>
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 16px 0 16px;
        }
        .actions {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          padding: 0 16px 16px 16px;
        }
        .slot-table {
          width: 100%;
          border-collapse: collapse;
          padding: 0 16px 16px 16px;
        }
        .slot-table th,
        .slot-table td {
          padding: 10px 12px;
          text-align: left;
        }
        .slot-table th {
          font-weight: 600;
          font-size: 0.9rem;
          color: var(--secondary-text-color);
        }
        .slot-row {
          border-top: 1px solid var(--divider-color);
        }
        .apply-button,
        .edit-button,
        .remove-button {
          min-width: 86px;
        }
        .busy {
          opacity: 0.6;
          pointer-events: none;
        }
        .empty {
          padding: 0 16px 16px 16px;
          color: var(--secondary-text-color);
        }
      </style>
      <div class="header">
        <div class="card-header">
          <div class="name">${title}</div>
        </div>
      </div>
      <div class="actions">
        <mwc-button id="add-slot" outlined>+ Add Slot</mwc-button>
        <mwc-button id="apply-all" outlined>Apply all</mwc-button>
        <mwc-button id="wipe-all" outlined>Wipe</mwc-button>
      </div>
      ${slots.length
        ? `<table class="slot-table">
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Name</th>
                  <th>PIN</th>
                  <th>Enabled</th>
                  <th>Edit</th>
                  <th>Apply</th>
                  <th>Remove</th>
                </tr>
              </thead>
              <tbody>
                ${slots
          .map(
            (slot) => `
                  <tr class="slot-row ${slot.busy ? "busy" : ""}">
                    <td>${slot.id}</td>
                    <td>${slot.name}</td>
                    <td>${slot.pin ? "****" : ""}</td>
                    <td>${slot.enabled ? "Yes" : "No"}</td>
                    <td>
                      <mwc-button class="edit-button" data-edit="${slot.id
              }" outlined>Edit</mwc-button>
                    </td>
                    <td>
                      <mwc-button class="apply-button" data-apply="${slot.id
              }" outlined>Apply</mwc-button>
                    </td>
                    <td>
                      <mwc-button class="remove-button" data-remove="${slot.id
              }" outlined>Remove</mwc-button>
                    </td>
                  </tr>
                `
          )
          .join("")}
              </tbody>
            </table>`
        : `<div class="empty">No slots yet. Use “Add slot” to create one.</div>`
      }
    `;
    this._attachHandlers();
  }

  _attachHandlers() {
    this._card.querySelector("#add-slot")?.addEventListener("click", () => {
      this._hass.callService("lockly", "add_slot", {
        entry_id: this._config.entry_id,
      });
    });
    this._card.querySelector("#apply-all")?.addEventListener("click", () => {
      this._hass.callService("lockly", "apply_all", {
        entry_id: this._config.entry_id,
      });
    });
    this._card.querySelector("#wipe-all")?.addEventListener("click", () => {
      if (confirm("Remove all slots?")) {
        this._hass.callService("lockly", "wipe_slots", {
          entry_id: this._config.entry_id,
        });
      }
    });
    this._card.querySelectorAll("[data-edit]").forEach((el) => {
      el.addEventListener("click", () => {
        const slotId = Number(el.getAttribute("data-edit"));
        const slot = this._getSlots().find((item) => item.id === slotId);
        if (slot) {
          this._openEditor(slot);
        }
      });
    });
    this._card.querySelectorAll("[data-apply]").forEach((el) => {
      el.addEventListener("click", () => {
        const slotId = Number(el.getAttribute("data-apply"));
        this._hass.callService("lockly", "apply_slot", {
          entry_id: this._config.entry_id,
          slot: slotId,
        });
      });
    });
    this._card.querySelectorAll("[data-remove]").forEach((el) => {
      el.addEventListener("click", () => {
        const slotId = Number(el.getAttribute("data-remove"));
        if (confirm(`Remove slot ${slotId}?`)) {
          this._hass.callService("lockly", "remove_slot", {
            entry_id: this._config.entry_id,
            slot: slotId,
          });
        }
      });
    });
  }

  _ensureDialog() {
    if (this._dialog) {
      return;
    }
    this._dialog = document.createElement("ha-dialog");
    this._dialog.heading = "Edit Slot";
    this._dialog.innerHTML = `
      <style>
        .dialog-content {
          display: grid;
          gap: 16px;
          padding: 8px 0;
        }
        .switch-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
      </style>
      <div class="dialog-content">
        <ha-textfield id="lockly-slot-name" label="Name"></ha-textfield>
        <ha-textfield
          id="lockly-slot-pin"
          label="PIN"
          type="text"
          inputmode="numeric"
          pattern="[0-9]*"
        ></ha-textfield>
        <div class="switch-row">
          <span>Enabled</span>
          <ha-switch id="lockly-slot-enabled"></ha-switch>
        </div>
      </div>
      <mwc-button slot="secondaryAction" id="lockly-slot-cancel">Cancel</mwc-button>
      <mwc-button slot="primaryAction" id="lockly-slot-save" outlined>Save</mwc-button>
    `;
    this._dialog.addEventListener("closed", () => {
      this._editingSlotId = null;
    });
    document.body.appendChild(this._dialog);
    this._dialog
      .querySelector("#lockly-slot-cancel")
      ?.addEventListener("click", () => {
        this._dialog.open = false;
      });
    this._dialog
      .querySelector("#lockly-slot-save")
      ?.addEventListener("click", () => this._saveEditor());
  }

  _openEditor(slot) {
    this._ensureDialog();
    this._editingSlotId = slot.id;
    const nameField = this._dialog.querySelector("#lockly-slot-name");
    const pinField = this._dialog.querySelector("#lockly-slot-pin");
    const enabledField = this._dialog.querySelector("#lockly-slot-enabled");
    if (nameField) {
      nameField.value = slot.name || "";
    }
    if (pinField) {
      pinField.value = slot.pin || "";
    }
    if (enabledField) {
      enabledField.checked = Boolean(slot.enabled);
    }
    this._dialog.open = true;
  }

  _saveEditor() {
    if (!this._editingSlotId) {
      return;
    }
    const nameField = this._dialog.querySelector("#lockly-slot-name");
    const pinField = this._dialog.querySelector("#lockly-slot-pin");
    const enabledField = this._dialog.querySelector("#lockly-slot-enabled");
    const name = nameField ? nameField.value : "";
    const pin = pinField ? pinField.value : "";
    const enabled = enabledField ? enabledField.checked : false;
    this._hass.callService("lockly", "update_slot", {
      entry_id: this._config.entry_id,
      slot: this._editingSlotId,
      name,
      pin,
      enabled,
    });
    this._dialog.open = false;
  }

  _getDefaultTitle() {
    if (!this._hass) {
      return null;
    }
    if (this._groupEntityId) {
      const groupState = this._hass.states[this._groupEntityId];
      const groupName =
        groupState?.attributes?.friendly_name || this._groupEntityId;
      return `Managing ${groupName}`;
    }
    if (this._groupName) {
      return `Managing ${this._groupName}`;
    }
    const states = Object.values(this._hass.states || {});
    const slotEntity = states.find(
      (state) =>
        state.attributes &&
        state.attributes.lockly_entry_id === this._config.entry_id &&
        state.attributes.lockly_group_entity
    );
    const groupEntityId = slotEntity?.attributes?.lockly_group_entity;
    if (!groupEntityId) {
      return null;
    }
    const groupState = this._hass.states[groupEntityId];
    const groupName = groupState?.attributes?.friendly_name || groupEntityId;
    return `Managing ${groupName}`;
  }
}

LocklyCard.getConfigElement = () => document.createElement("lockly-card-editor");
LocklyCard.getStubConfig = () => ({});
LocklyCard.prototype.getConfigElement = LocklyCard.getConfigElement;

if (!customElements.get("lockly-card")) {
  customElements.define("lockly-card", LocklyCard);
}
// eslint-disable-next-line no-console
console.info("Lockly card custom element registered");

class LocklyCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._entriesLoaded) {
      this._entriesLoaded = true;
      this._loadEntries();
    }
    this._render();
  }

  get value() {
    return this._config;
  }

  async _loadEntries() {
    if (!this._hass?.connection) {
      return;
    }
    try {
      this._entries = await this._hass.connection.sendMessagePromise({
        type: WS_ENTRIES_TYPE,
      });
      this._render();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.debug("Lockly entries load skipped", err);
    }
  }

  _handleEntryChange(ev) {
    // eslint-disable-next-line no-console
    console.info("Lockly editor change event", ev.type, ev.detail, ev.target);
    const entryId =
      ev.detail?.value ??
      ev.target?.value ??
      ev.target?._value ??
      ev.target?.selected;
    if (!entryId || entryId === this._config?.entry_id) {
      return;
    }
    this._config = { ...this._config, entry_id: entryId };
    // eslint-disable-next-line no-console
    console.info("Lockly editor selected entry", entryId);
    this._emitConfigChanged();
    this._render();
  }

  _emitConfigChanged() {
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      })
    );
  }

  _render() {
    if (!this._hass) {
      return;
    }
    const entries = this._entries || [];
    const selected = this._config?.entry_id || "";
    this.innerHTML = `
      <style>
        .container {
          padding: 16px;
        }
        .field {
          margin-bottom: 16px;
        }
      </style>
      <div class="container">
        <ha-select class="field" label="Lock group">
          ${entries
        .map((entry) => {
          const label =
            entry.group_name ||
            entry.title ||
            entry.group_entity_id ||
            entry.entry_id;
          const isSelected = entry.entry_id === selected ? "selected" : "";
          return `<mwc-list-item value="${entry.entry_id}" ${isSelected}>
                ${label}
              </mwc-list-item>`;
        })
        .join("")}
        </ha-select>
        <p class="secondary">
          Select the lock group created by the Lockly integration.
        </p>
      </div>
    `;
    const select = this.querySelector("ha-select");
    if (select) {
      if (selected) {
        select.value = selected;
      }
      select.addEventListener("value-changed", (ev) =>
        this._handleEntryChange(ev)
      );
      select.addEventListener("selected", (ev) =>
        this._handleEntryChange(ev)
      );
      select.addEventListener("change", (ev) => this._handleEntryChange(ev));
    }
  }
}

if (!customElements.get("lockly-card-editor")) {
  customElements.define("lockly-card-editor", LocklyCardEditor);
}
// eslint-disable-next-line no-console
console.info("Lockly card editor custom element registered");

LocklyCard.getConfigElement = () => document.createElement("lockly-card-editor");
LocklyCard.getStubConfig = () => ({});

window.customCards = window.customCards || [];
if (!window.customCards.find((card) => card.type === "lockly-card")) {
  window.customCards.push({
    type: "lockly-card",
    name: "Lockly Card",
    description: "Manage Zigbee2MQTT lock slots",
  });
}
