const DEFAULT_TITLE = "Lockly";
const RESOURCE_URL = import.meta.url;
const CARD_VERSION = new URL(RESOURCE_URL).searchParams.get("v") || "0.0.0";
const WS_VERSION_TYPE = "lockly/version";
const WS_CONFIG_TYPE = "lockly/config";
const WS_ENTRIES_TYPE = "lockly/entries";
const BANNER_STYLE = [
  "background: linear-gradient(90deg, #00c853, #2962ff)",
  "color: #fff",
  "padding: 2px 8px",
  "border-radius: 4px",
  "font-weight: 600",
  "letter-spacing: 0.2px",
].join(";");
// eslint-disable-next-line no-console
console.info(`%c Lockly Card ${CARD_VERSION} loaded`, BANNER_STYLE);

class LocklyCard extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    if (!Object.prototype.hasOwnProperty.call(this._config, "show_bulk_actions")) {
      this._config = { ...this._config, show_bulk_actions: true };
    }
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
      this._entryTitle = response?.title || null;
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
        status: entity.attributes.status || "",
      }))
      .sort((a, b) => a.id - b.id);
  }

  _render() {
    if (!this._hass || !this._card) {
      return;
    }

    const extraAdminUsers = Array.isArray(this._config?.admin_users)
      ? this._config.admin_users
      : [];
    if (!this._config.entry_id) {
      this._card.innerHTML = `
        <div class="card-content">
          Lockly card requires an entry_id.
        </div>
      `;
      return;
    }
    const hasTitle = Object.prototype.hasOwnProperty.call(this._config, "title");
    const title = hasTitle
      ? this._config.title || ""
      : this._getDefaultTitle() || DEFAULT_TITLE;
    const adminOnly = Boolean(this._config?.admin_only);
    const isAdmin = Boolean(this._hass?.user?.is_admin);
    const extraAdminTokens = new Set(
      extraAdminUsers
        .map((value) => String(value || "").trim().toLowerCase())
        .filter(Boolean)
    );
    const userId = String(this._hass?.user?.id || "").toLowerCase();
    const userName = String(this._hass?.user?.name || "").toLowerCase();
    const userNameParts = userName
      .split(/\\s+/)
      .map((part) => part.trim())
      .filter(Boolean);
    const isExtraAdmin =
      (userId && extraAdminTokens.has(userId)) ||
      (userName && extraAdminTokens.has(userName)) ||
      userNameParts.some((part) => extraAdminTokens.has(part));
    const canEdit = !adminOnly || isAdmin || isExtraAdmin;
    this._canEdit = canEdit;
    const showBulkActions = this._config?.show_bulk_actions !== false;
    const slots = this._getSlots();
    this._card.innerHTML = `
      <style>
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 16px 0 16px;
        }
        .slot-table {
          width: calc(100% - 32px);
          margin: 0 auto 8px;
          border-collapse: separate;
          border-spacing: 0 2px;
          font-size: 1rem;
          line-height: 1.4;
        }
        .slot-table th,
        .slot-table td {
          padding: 12px 16px;
          text-align: left;
        }
        .slot-table th {
          font-weight: 600;
          font-size: 1rem;
          color: var(--primary-text-color);
        }
        .slot-row td {
          transition: background-color 0.2s ease;
        }
        .slot-row td:first-child {
          border-top-left-radius: 0;
          border-bottom-left-radius: 0;
        }
        .slot-row td:last-child {
          border-top-right-radius: 0;
          border-bottom-right-radius: 0;
        }
        .slot-row:first-child td:first-child {
          border-top-left-radius: 10px;
        }
        .slot-row:first-child td:last-child {
          border-top-right-radius: 10px;
        }
        .slot-row:last-child td:first-child {
          border-bottom-left-radius: 10px;
        }
        .slot-row:last-child td:last-child {
          border-bottom-right-radius: 10px;
        }
        .slot-row.enabled td {
          background: rgba(0, 200, 83, 0.12);
        }
        .slot-row.disabled td {
          background: rgba(255, 82, 82, 0.1);
        }
        .slot-row:nth-child(even) td {
          background-image: linear-gradient(
            rgba(0, 0, 0, 0.04),
            rgba(0, 0, 0, 0.04)
          );
        }
        .slot-row:hover td {
          box-shadow: inset 0 0 0 9999px rgba(0, 0, 0, 0.04);
          cursor: pointer;
        }
        .slot-table.readonly .slot-row:hover td {
          box-shadow: none;
          cursor: default;
        }
        .busy {
          opacity: 0.6;
          pointer-events: none;
        }
        .busy-indicator {
          display: inline-flex;
          align-items: center;
          gap: 8px;
        }
        .busy-spinner {
          width: 14px;
          height: 14px;
          border: 2px solid rgba(0, 0, 0, 0.2);
          border-top-color: rgba(0, 0, 0, 0.6);
          border-radius: 50%;
          animation: lockly-spin 0.8s linear infinite;
        }
        @keyframes lockly-spin {
          0% {
            transform: rotate(0);
          }
          100% {
            transform: rotate(360deg);
          }
        }
        .empty {
          padding: 24px 16px 12px 16px;
          color: var(--secondary-text-color);
        }
        .empty.no-title {
          margin-top: 12px;
        }
        .footer-actions {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
          padding: 8px 16px 16px 16px;
        }
        .footer-actions-left,
        .footer-actions-right {
          display: flex;
          gap: 8px;
        }
      </style>
      ${title
        ? `<div class="header">
        <div class="card-header">
          <h1 class="card-header">${title}</h1>
        </div>
      </div>`
        : ""
      }
      ${slots.length
        ? `<table class="slot-table ${canEdit ? "" : "readonly"}">
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Name</th>
                  <th>PIN</th>
                  <th>Enabled</th>
                </tr>
              </thead>
              <tbody>
                ${slots
          .map(
            (slot) => `
                  <tr class="slot-row ${slot.enabled ? "enabled" : "disabled"
              } ${slot.busy ? "busy" : ""}" data-slot="${slot.id}">
                    <td>${slot.id}</td>
                    <td>${slot.name}</td>
                    <td>${slot.pin ? "****" : ""}</td>
                    <td>${slot.status === "queued"
                ? "Queued"
                : slot.status === "updating"
                  ? '<span class="busy-indicator"><span class="busy-spinner"></span>Updating</span>'
                  : slot.status === "timeout"
                    ? "Timeout"
                    : slot.busy
                      ? '<span class="busy-indicator"><span class="busy-spinner"></span>Working</span>'
                      : slot.enabled
                        ? "Yes"
                        : "No"
              }</td>
                  </tr>
                `
          )
          .join("")}
              </tbody>
            </table>`
        : `<div class="empty ${title ? "" : "no-title"}">No slots yet. Use “Add slot” to create one.</div>`
      }
      ${canEdit
        ? `<div class="footer-actions">
        <div class="footer-actions-left">
          ${
            showBulkActions
              ? `<ha-button id="wipe-all" class="danger" appearance="filled" variant="danger">Wipe all</ha-button>`
              : ""
          }
        </div>
        <div class="footer-actions-right">
          ${
            showBulkActions
              ? `<ha-button id="apply-all" appearance="filled">Apply all</ha-button>`
              : ""
          }
          <ha-button id="add-slot" appearance="filled" variant="brand">+ Add Slot</ha-button>
        </div>
      </div>`
        : ""
      }
    `;
    this._attachHandlers();
  }

  _attachHandlers() {
    const canEdit = Boolean(this._canEdit);
    const dryRun = Boolean(this._config?.dry_run);
    this._card.querySelector("#add-slot")?.addEventListener("click", async () => {
      await this._hass.callService("lockly", "add_slot", {
        entry_id: this._config.entry_id,
        dry_run: dryRun,
      });
      this._openNewestSlotAfterAdd();
    });
    this._card.querySelector("#apply-all")?.addEventListener("click", () => {
      if (
        confirm(
          "Apply all enabled slots to the selected locks? Disabled slots are skipped."
        )
      ) {
        const data = { entry_id: this._config.entry_id, dry_run: dryRun };
        const lockEntities = this._getLockEntityOverrides();
        if (lockEntities) {
          data.lock_entities = lockEntities;
        }
        this._hass.callService("lockly", "apply_all", data);
      }
    });
    this._card.querySelector("#wipe-all")?.addEventListener("click", () => {
      if (
        confirm(
          "Remove all slots and clear their PINs from the selected locks? This cannot be undone."
        )
      ) {
        const data = { entry_id: this._config.entry_id, dry_run: dryRun };
        const lockEntities = this._getLockEntityOverrides();
        if (lockEntities) {
          data.lock_entities = lockEntities;
        }
        this._hass.callService("lockly", "wipe_slots", data);
      }
    });
    if (canEdit) {
      this._card.querySelectorAll("tbody tr[data-slot]").forEach((row) => {
        row.addEventListener("click", () => {
          const slotId = Number(row.getAttribute("data-slot"));
          const slot = this._getSlots().find((item) => item.id === slotId);
          if (slot) {
            this._openEditor(slot);
          }
        });
      });
    }
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
          gap: 20px;
          padding: 16px 0;
        }
        .switch-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
        ha-button[slot="secondaryAction"],
        ha-button[slot="primaryAction"] {
          margin-inline-start: 8px;
          min-width: 92px;
        }
        .danger {
          --ha-button-primary-color: var(--ha-color-fill-danger-loud-resting);
          --ha-button-border-color: var(--ha-color-fill-danger-loud-resting);
          --ha-button-background-color: var(--ha-color-fill-danger-loud-resting);
          --ha-button-text-color: var(--ha-color-on-danger-loud, #fff);
          --mdc-theme-primary: var(--ha-color-fill-danger-loud-resting);
          --mdc-theme-on-primary: var(--ha-color-on-danger-loud, #fff);
          --md-sys-color-primary: var(--ha-color-fill-danger-loud-resting);
          --md-sys-color-on-primary: var(--ha-color-on-danger-loud, #fff);
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
          maxlength="8"
        ></ha-textfield>
        <div class="switch-row">
          <span>Enabled</span>
          <ha-switch id="lockly-slot-enabled"></ha-switch>
        </div>
      </div>
      <ha-button
        slot="secondaryAction"
        id="lockly-slot-delete"
        class="danger"
        appearance="filled"
        variant="danger"
      >Delete</ha-button>
      <ha-button slot="secondaryAction" id="lockly-slot-cancel" appearance="outlined"
        >Cancel</ha-button
      >
      <ha-button slot="primaryAction" id="lockly-slot-save" appearance="filled"
        >Apply</ha-button
      >
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
      .querySelector("#lockly-slot-delete")
      ?.addEventListener("click", () => this._deleteSlot());
    this._dialog
      .querySelector("#lockly-slot-save")
      ?.addEventListener("click", () => this._saveEditor());
  }

  _openEditor(slot) {
    if (!this._canEdit) {
      return;
    }
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
      this._setPinError(pinField, "");
    }
    if (enabledField) {
      enabledField.checked = Boolean(slot.enabled);
    }
    this._dialog.open = true;
    if (nameField && !nameField.value) {
      requestAnimationFrame(() => nameField.focus?.());
    }
  }

  _openNewestSlotAfterAdd() {
    const attempts = 6;
    const delayMs = 250;
    let tries = 0;

    const attemptOpen = () => {
      const slots = this._getSlots();
      if (!slots.length) {
        return;
      }
      const newest = slots[slots.length - 1];
      if (newest) {
        this._openEditor(newest);
        return;
      }
      if (tries < attempts) {
        tries += 1;
        setTimeout(attemptOpen, delayMs);
      }
    };

    setTimeout(attemptOpen, delayMs);
  }

  async _saveEditor() {
    if (!this._editingSlotId) {
      return;
    }
    const nameField = this._dialog.querySelector("#lockly-slot-name");
    const pinField = this._dialog.querySelector("#lockly-slot-pin");
    const enabledField = this._dialog.querySelector("#lockly-slot-enabled");
    const name = nameField ? nameField.value : "";
    const pin = pinField ? pinField.value.trim() : "";
    if (!pin || !/^\d{4,8}$/.test(pin)) {
      if (pinField) {
        this._setPinError(pinField, "Error: PIN must be 4-8 digits.");
        pinField.reportValidity?.();
        pinField.focus?.();
      }
      return;
    }
    if (pinField) {
      this._setPinError(pinField, "");
    }
    const enabled = enabledField ? enabledField.checked : false;
    try {
      await this._hass.callService("lockly", "update_slot", {
        entry_id: this._config.entry_id,
        slot: this._editingSlotId,
        name,
        pin,
        enabled,
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("Lockly update failed", err);
      return;
    }
    const applyData = {
      entry_id: this._config.entry_id,
      slot: this._editingSlotId,
      dry_run: Boolean(this._config?.dry_run),
    };
    const lockEntities = this._getLockEntityOverrides();
    if (lockEntities) {
      applyData.lock_entities = lockEntities;
    }
    try {
      await this._hass.callService("lockly", "apply_slot", applyData);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("Lockly apply failed", err);
      return;
    }
    this._dialog.open = false;
  }

  _deleteSlot() {
    if (!this._editingSlotId) {
      return;
    }
    if (confirm(`Remove slot ${this._editingSlotId}?`)) {
      const data = {
        entry_id: this._config.entry_id,
        slot: this._editingSlotId,
        dry_run: Boolean(this._config?.dry_run),
      };
      const lockEntities = this._getLockEntityOverrides();
      if (lockEntities) {
        data.lock_entities = lockEntities;
      }
      this._hass.callService("lockly", "remove_slot", data);
      this._dialog.open = false;
    }
  }

  _getLockEntityOverrides() {
    const lockEntities = this._config?.lock_entities;
    if (!Array.isArray(lockEntities)) {
      return null;
    }
    const filtered = lockEntities.filter(Boolean);
    return filtered.length ? filtered : null;
  }

  _getDefaultTitle() {
    if (!this._hass) {
      return null;
    }
    if (this._entryTitle) {
      return this._entryTitle;
    }
    return DEFAULT_TITLE;
  }

  _setPinError(pinField, message) {
    pinField.invalid = Boolean(message);
    pinField.errorMessage = message || "";
  }
}

LocklyCard.getConfigElement = () => document.createElement("lockly-card-editor");
LocklyCard.getStubConfig = () => ({
  title: "",
  entry_id: "",
  lock_entities: [],
  admin_only: false,
  dry_run: false,
  show_bulk_actions: true,
});
LocklyCard.prototype.getConfigElement = LocklyCard.getConfigElement;

if (!customElements.get("lockly-card")) {
  customElements.define("lockly-card", LocklyCard);
}

class LocklyCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    if (!Object.prototype.hasOwnProperty.call(this._config, "title")) {
      this._config = { ...this._config, title: "" };
    }
    if (!Object.prototype.hasOwnProperty.call(this._config, "admin_only")) {
      this._config = { ...this._config, admin_only: false };
    }
    if (!Object.prototype.hasOwnProperty.call(this._config, "dry_run")) {
      this._config = { ...this._config, dry_run: false };
    }
    if (!Object.prototype.hasOwnProperty.call(this._config, "show_bulk_actions")) {
      this._config = { ...this._config, show_bulk_actions: true };
    }
    if (!Object.prototype.hasOwnProperty.call(this._config, "admin_users")) {
      this._config = { ...this._config, admin_users: [] };
    }
    this._needsRender = true;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._entriesLoaded) {
      this._entriesLoaded = true;
      this._loadEntries();
    }
    const form = this.querySelector("#lockly-entities-form");
    if (form) {
      form.hass = this._hass;
    }
    if (this._needsRender || !this._rendered) {
      this._render();
    }
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
      if (!this._config?.entry_id && this._entries?.length === 1) {
        this._config = {
          ...this._config,
          entry_id: this._entries[0].entry_id,
        };
        this._emitConfigChanged();
      }
      this._needsRender = true;
      this._render();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.debug("Lockly entries load skipped", err);
    }
  }

  _handleEntryChange(ev) {
    const entryId = ev.detail?.value ?? ev.target?.value ?? "";
    if (!entryId || entryId === this._config?.entry_id) {
      return;
    }
    this._config = { ...this._config, entry_id: entryId };
    this._emitConfigChanged();
  }



  _handleTitleChange(ev) {
    const title = ev.target?.value ?? "";
    this._config = { ...this._config, title };
    this._emitConfigChanged();
  }

  _handleAdminUsersChange(ev) {
    const value = ev.target?.value ?? "";
    const users = value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    this._config = { ...this._config, admin_users: users };
    this._emitConfigChanged();
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
    this._needsRender = false;
    this._rendered = true;
    const entries = this._entries || [];
    const selected = this._config?.entry_id || "";
    const title = this._config?.title || "";
    const adminOnly = Boolean(this._config?.admin_only);
    const dryRun = Boolean(this._config?.dry_run);
    const showBulkActions = this._config?.show_bulk_actions !== false;
    const lockEntities = Array.isArray(this._config?.lock_entities)
      ? this._config.lock_entities
      : [];
    const entrySelect =
      entries.length > 1
        ? `
          <ha-select class="field" label="Lockly instance">
            ${entries
          .map((entry) => {
            const label = entry.title || entry.entry_id;
            const isSelected = entry.entry_id === selected ? "selected" : "";
            return `<mwc-list-item value="${entry.entry_id}" ${isSelected}>
                    ${label}
                  </mwc-list-item>`;
          })
          .join("")}
          </ha-select>
          <p class="section-desc">Select which Lockly instance to use.</p>
        `
        : "";
    this.innerHTML = `
      <style>
        .container {
          padding: 16px;
        }
        .field {
          margin-bottom: 16px;
          width: 100%;
        }
        .section-title {
          font-weight: 600;
          margin: 8px 0 8px;
        }
        .section-desc {
          color: var(--secondary-text-color);
          margin: 0 0 16px 0;
        }
        .toggle-stack {
          display: flex;
          flex-direction: column;
          gap: 12px;
          margin-bottom: 24px;
        }
        .toggle-stack ha-formfield {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        ha-form {
          display: block;
        }
      </style>
      <div class="container">
        <ha-textfield id="lockly-title" class="field" label="Title (optional)"></ha-textfield>
        ${entrySelect}
        <div class="toggle-stack">
          <ha-formfield label="Only admins can see PINs and edit">
            <ha-switch id="lockly-admin-only"></ha-switch>
          </ha-formfield>
          <ha-formfield label="Simulation mode (no MQTT)">
            <ha-switch id="lockly-dry-run"></ha-switch>
          </ha-formfield>
          <ha-formfield label="Show bulk actions (Apply all/Wipe all)">
            <ha-switch id="lockly-show-bulk-actions"></ha-switch>
          </ha-formfield>
        </div>
        <ha-textfield
          class="field"
          label="Additional admin users (comma separated)"
          id="lockly-admin-users"
          helper-text="Enter user IDs or display names (e.g., user_123, Bettina)."
        ></ha-textfield>
        <div class="section-title">Locks</div>
        <p class="section-desc">
          Add locks or lock groups that this card will manage.
        </p>
        <ha-form id="lockly-entities-form"></ha-form>
      </div>
    `;
    const titleField = this.querySelector("#lockly-title");
    if (titleField) {
      titleField.value = title;
      titleField.addEventListener("change", (ev) => this._handleTitleChange(ev));
    }
    const adminUsersField = this.querySelector("#lockly-admin-users");
    if (adminUsersField) {
      const adminUsers = Array.isArray(this._config?.admin_users)
        ? this._config.admin_users
        : [];
      adminUsersField.value = adminUsers.join(", ");
      adminUsersField.addEventListener("change", (ev) =>
        this._handleAdminUsersChange(ev)
      );
    }
    const select = this.querySelector("ha-select");
    if (select) {
      if (selected) {
        select.value = selected;
      }
      select.addEventListener("value-changed", (ev) =>
        this._handleEntryChange(ev)
      );
      select.addEventListener("selected", (ev) => this._handleEntryChange(ev));
      select.addEventListener("change", (ev) => this._handleEntryChange(ev));
    }
    const adminSwitch = this.querySelector("#lockly-admin-only");
    if (adminSwitch) {
      adminSwitch.checked = adminOnly;
      adminSwitch.addEventListener("change", (ev) => {
        this._config = { ...this._config, admin_only: ev.target?.checked };
        this._emitConfigChanged();
      });
    }
    const dryRunSwitch = this.querySelector("#lockly-dry-run");
    if (dryRunSwitch) {
      dryRunSwitch.checked = dryRun;
      dryRunSwitch.addEventListener("change", (ev) => {
        this._config = { ...this._config, dry_run: ev.target?.checked };
        this._emitConfigChanged();
      });
    }
    const bulkActionsSwitch = this.querySelector("#lockly-show-bulk-actions");
    if (bulkActionsSwitch) {
      bulkActionsSwitch.checked = showBulkActions;
      bulkActionsSwitch.addEventListener("change", (ev) => {
        this._config = {
          ...this._config,
          show_bulk_actions: ev.target?.checked,
        };
        this._emitConfigChanged();
      });
    }
    const form = this.querySelector("#lockly-entities-form");
    if (form) {
      form.hass = this._hass;
      form.schema = [
        {
          name: "lock_entities",
          selector: {
            entity: {
              multiple: true,
              domain: ["lock", "group"],
            },
          },
        },
      ];
      form.data = { lock_entities: lockEntities };
      form.computeLabel = () => "Locks";
      form.addEventListener("value-changed", (ev) => {
        const value = ev.detail?.value || {};
        this._config = {
          ...this._config,
          lock_entities: value.lock_entities || [],
        };
        this._emitConfigChanged();
      });
    }
  }
}

if (!customElements.get("lockly-card-editor")) {
  customElements.define("lockly-card-editor", LocklyCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.find((card) => card.type === "lockly-card")) {
  window.customCards.push({
    type: "lockly-card",
    name: "Lockly Card",
    description: "Manage Zigbee2MQTT lock slots",
  });
}
