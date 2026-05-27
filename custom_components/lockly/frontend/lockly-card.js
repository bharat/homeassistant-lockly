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

// localStorage may throw in private browsing or when over quota; the card
// must not break in either case, so reads return null and writes are silent.
function readPref(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (_) {
    return null;
  }
}

function writePref(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (_) {
    /* ignore */
  }
}

function showDisabledPrefKey(entryId) {
  return `lockly:lockly-card:${entryId || "default"}:showDisabled`;
}

class LocklyCard extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    if (!Object.prototype.hasOwnProperty.call(this._config, "show_bulk_actions")) {
      this._config = { ...this._config, show_bulk_actions: true };
    }
    if (this._showDisabled === undefined) {
      const stored = readPref(showDisabledPrefKey(this._config.entry_id));
      // Two valid strings: "all" (show every slot) and "enabled" (hide
      // disabled). Anything else (including null) falls back to the default
      // of true, which matches the pre-persistence behavior.
      this._showDisabled = stored === "enabled" ? false : true;
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
    // admin_users supports two formats so old configs keep working:
    //   - person entity IDs (the picker writes these now)
    //   - raw HA user IDs (the pre-picker format; resolved as-is)
    // Mixed lists are fine; both resolve to a set of user IDs to check.
    const extraAdminUserIds = new Set();
    for (const value of extraAdminUsers) {
      const str = String(value || "");
      if (!str) continue;
      if (str.startsWith("person.")) {
        const linked = this._hass?.states?.[str]?.attributes?.user_id;
        if (linked) {
          extraAdminUserIds.add(String(linked));
        }
      } else {
        extraAdminUserIds.add(str);
      }
    }
    const userId = String(this._hass?.user?.id || "");
    const isExtraAdmin = Boolean(userId) && extraAdminUserIds.has(userId);
    const canEdit = !adminOnly || isAdmin || isExtraAdmin;
    this._canEdit = canEdit;
    const showBulkActions = this._config?.show_bulk_actions !== false;
    const allSlots = this._getSlots();
    const hasDisabledSlots = allSlots.some((slot) => !slot.enabled);
    const showDisabled = this._showDisabled !== false;
    const slots = showDisabled
      ? allSlots
      : allSlots.filter(
          (slot) =>
            slot.enabled ||
            slot.status === "updating" ||
            slot.status === "queued",
        );
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
        .status-text {
          font-weight: 600;
        }
        .status-timeout {
          color: var(--error-color);
          font-weight: 700;
        }
        .status-updating,
        .status-queued,
        .status-working {
          color: var(--warning-color);
          font-weight: 700;
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
          justify-content: flex-end;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
          padding: 8px 16px 16px 16px;
        }
        .footer-actions-right {
          display: flex;
          gap: 8px;
        }
        .slot-filter-tabs {
          display: inline-flex;
          gap: 2px;
          font-size: 0.8rem;
        }
        .slot-filter-tabs button {
          cursor: pointer;
          border: none;
          background: none;
          padding: 2px 6px;
          color: var(--secondary-text-color);
          font-weight: 400;
          font-size: inherit;
          opacity: 0.7;
        }
        .slot-filter-tabs button:hover,
        .slot-filter-tabs button:focus-visible {
          opacity: 1;
          outline: none;
        }
        .slot-filter-tabs button.active {
          color: var(--primary-color);
          font-weight: 500;
          opacity: 1;
        }
        .slot-filter-tabs .sep {
          color: var(--divider-color, rgba(0,0,0,0.2));
          font-weight: 300;
          align-self: center;
          font-size: 0.75rem;
        }
      </style>
      ${(title || hasDisabledSlots)
        ? `<div class="header">
        <div class="card-header">
          ${title ? `<h1 class="card-header">${title}</h1>` : ""}
        </div>
        ${hasDisabledSlots
          ? `<div class="slot-filter-tabs">
              <button type="button" data-filter="all" class="${showDisabled ? "active" : ""}">All</button>
              <span class="sep">|</span>
              <button type="button" data-filter="enabled" class="${showDisabled ? "" : "active"}">Enabled only</button>
            </div>`
          : ""
        }
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
                  <th>Status</th>
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
                ? '<span class="busy-indicator status-text status-queued"><span class="busy-spinner"></span>Queued</span>'
                : slot.status === "updating"
                  ? '<span class="busy-indicator status-text status-updating"><span class="busy-spinner"></span>Updating</span>'
                  : slot.status === "timeout"
                    ? '<span class="status-text status-timeout">Timeout</span>'
                    : slot.busy
                      ? '<span class="busy-indicator status-text status-working"><span class="busy-spinner"></span>Working</span>'
                      : slot.enabled
                        ? "Enabled"
                        : "Disabled"
              }</td>
                  </tr>
                `
          )
          .join("")}
              </tbody>
            </table>`
        : allSlots.length
          ? `<div class="empty ${title ? "" : "no-title"}">No enabled slots. Switch to “All” to see disabled slots.</div>`
          : `<div class="empty ${title ? "" : "no-title"}">No slots yet. Use “Add slot” to create one.</div>`
      }
      ${canEdit
        ? `<div class="footer-actions">
        <div class="footer-actions-right">
          ${showBulkActions
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
    this._card.querySelectorAll(".slot-filter-tabs button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const showDisabled = btn.getAttribute("data-filter") === "all";
        if (this._showDisabled === showDisabled) {
          return;
        }
        this._showDisabled = showDisabled;
        writePref(
          showDisabledPrefKey(this._config?.entry_id),
          showDisabled ? "all" : "enabled"
        );
        this._render();
      });
    });
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
    this._dialog.headerTitle = "Edit Slot";
    this._dialog.innerHTML = `
      <style>
        .dialog-content {
          display: grid;
          gap: 16px;
          padding: 8px 0;
        }
        ha-input {
          display: block;
        }
        .switch-row {
          display: flex;
          justify-content: flex-end;
        }
        .switch-row ha-formfield {
          --mdc-typography-body2-font-size: 1rem;
        }
        .dialog-footer {
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 8px;
          width: 100%;
        }
        .dialog-footer ha-button {
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
        <ha-input
          id="lockly-slot-name"
          label="Name"
          autocomplete="off"
        ></ha-input>
        <ha-input
          id="lockly-slot-pin"
          label="PIN"
          inputmode="numeric"
          maxlength="8"
          autocomplete="off"
        ></ha-input>
        <div class="switch-row">
          <ha-formfield label="Enabled">
            <ha-switch id="lockly-slot-enabled"></ha-switch>
          </ha-formfield>
        </div>
      </div>
      <div slot="footer" class="dialog-footer">
        <ha-button
          id="lockly-slot-delete"
          class="danger"
          appearance="filled"
          variant="danger"
        >Delete</ha-button>
        <ha-button id="lockly-slot-cancel" appearance="outlined">Cancel</ha-button>
        <ha-button id="lockly-slot-save" appearance="filled">Apply</ha-button>
      </div>
    `;
    this._dialog.addEventListener("closed", () => {
      this._editingSlotId = null;
      this._originalSlot = null;
      this._dialog?.remove();
      this._dialog = null;
    });
    document.body.appendChild(this._dialog);
    this._dialog
      .querySelector("#lockly-slot-cancel")
      ?.addEventListener("click", () => {
        this._closeDialog();
      });
    this._dialog
      .querySelector("#lockly-slot-delete")
      ?.addEventListener("click", () => this._deleteSlot());
    this._dialog
      .querySelector("#lockly-slot-save")
      ?.addEventListener("click", () => this._saveEditor());
    const nameField = this._dialog.querySelector("#lockly-slot-name");
    const pinField = this._dialog.querySelector("#lockly-slot-pin");
    const enabledField = this._dialog.querySelector("#lockly-slot-enabled");
    const refresh = () => this._refreshButtonState();
    nameField?.addEventListener("input", refresh);
    if (pinField) {
      pinField.addEventListener("input", () => {
        const digits = pinField.value.replace(/\D+/g, "");
        if (pinField.value !== digits) {
          pinField.value = digits;
        }
        refresh();
      });
    }
    enabledField?.addEventListener("change", refresh);
  }

  _openEditor(slot) {
    if (!this._canEdit) {
      return;
    }
    this._ensureDialog();
    this._editingSlotId = slot.id;
    this._originalSlot = {
      name: slot.name || "",
      pin: slot.pin || "",
      enabled: Boolean(slot.enabled),
      // Track the slot's current sync status so the dialog can offer
      // a re-apply when the previous apply timed out (HA storage and
      // the lock fell out of sync — form values look "unchanged" but
      // the lock still needs the push).
      status: slot.status || "",
    };
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
    this._refreshButtonState();
    this._openDialog();
    if (nameField && !nameField.value) {
      requestAnimationFrame(() => nameField.focus?.());
    }
  }

  _computeFormState() {
    if (!this._dialog || !this._originalSlot) {
      return null;
    }
    const nameField = this._dialog.querySelector("#lockly-slot-name");
    const pinField = this._dialog.querySelector("#lockly-slot-pin");
    const enabledField = this._dialog.querySelector("#lockly-slot-enabled");
    const cur = {
      name: nameField?.value ?? "",
      pin: (pinField?.value ?? "").trim(),
      enabled: Boolean(enabledField?.checked),
    };
    const orig = this._originalSlot;
    const nameChanged = cur.name !== orig.name;
    const pinChanged = cur.pin !== orig.pin;
    const enabledChanged = cur.enabled !== orig.enabled;
    // If the previous apply timed out, HA-side state is current but
    // the lock didn't get the push. The dialog should let the user
    // re-apply even though the form looks unchanged.
    const needsReapply = orig.status === "timeout";
    return {
      cur,
      changed: nameChanged || pinChanged || enabledChanged,
      needsReapply,
      // Push to the lock when its state will materially differ: the
      // enabled flag flipped, or the user is rotating a pin on a slot
      // that is/will be active. Pure name edits and "draft" pin edits
      // on a disabled slot are HA-side only. Also push when the
      // previous attempt timed out, regardless of form changes.
      shouldApply: enabledChanged || (cur.enabled && pinChanged) || needsReapply,
    };
  }

  _refreshButtonState() {
    const state = this._computeFormState();
    const saveBtn = this._dialog?.querySelector("#lockly-slot-save");
    if (!state || !saveBtn) {
      return;
    }
    saveBtn.textContent = state.shouldApply ? "Apply" : "Save";
    saveBtn.disabled = !(state.changed || state.needsReapply);
  }

  _openDialog() {
    if (!this._dialog) {
      return;
    }
    if (typeof this._dialog.show === "function") {
      this._dialog.show();
      return;
    }
    this._dialog.open = true;
  }

  _closeDialog() {
    if (!this._dialog) {
      return;
    }
    if (typeof this._dialog.hide === "function") {
      this._dialog.hide();
      return;
    }
    this._dialog.open = false;
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
    const formState = this._computeFormState();
    const shouldApply = formState ? formState.shouldApply : true;
    const changed = formState ? formState.changed : true;
    // Only push HA-side updates when the form actually changed.  When
    // the user is retrying after a timeout (status="timeout") with no
    // edits, HA already has the right values and update_slot would be
    // a no-op; skipping it avoids a spurious round trip.
    if (changed) {
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
    }
    if (shouldApply) {
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
    }
    this._closeDialog();
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
      this._closeDialog();
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

  _handleTitleChange(ev) {
    const title = ev.target?.value ?? "";
    this._config = { ...this._config, title };
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
          <label class="field field-stack">
            <span class="field-label">Lockly instance</span>
            <select id="lockly-entry-select" class="native-select">
              ${selected ? "" : `<option value="" selected disabled>Select an instance…</option>`}
              ${entries
                .map((entry) => {
                  const label = entry.title || entry.entry_id;
                  const isSelected = entry.entry_id === selected ? "selected" : "";
                  return `<option value="${entry.entry_id}" ${isSelected}>${label}</option>`;
                })
                .join("")}
            </select>
          </label>
        `
        : "";
    const activeTab = this._activeTab || "locks";
    this.innerHTML = `
      <style>
        .container {
          padding: 16px;
        }
        .field {
          margin-bottom: 16px;
          width: 100%;
        }
        .section-desc {
          color: var(--secondary-text-color);
          margin: 0 0 16px 0;
        }
        .field-stack {
          display: flex;
          flex-direction: column;
          gap: 4px;
          margin-bottom: 8px;
        }
        .field-label {
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .native-select {
          font: inherit;
          font-size: 16px;
          padding: 10px 12px;
          border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
          border-radius: 4px;
          background: var(--card-background-color, var(--primary-background-color));
          color: var(--primary-text-color);
          outline: none;
          width: 100%;
        }
        .native-select:focus {
          border-color: var(--primary-color);
        }
        .tab-bar {
          display: flex;
          border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.12));
          margin-bottom: 16px;
        }
        .tab-bar button {
          flex: 1;
          cursor: pointer;
          border: none;
          background: none;
          padding: 12px 8px;
          color: var(--secondary-text-color);
          font: inherit;
          font-weight: 500;
          border-bottom: 2px solid transparent;
          margin-bottom: -1px;
        }
        .tab-bar button:hover,
        .tab-bar button:focus-visible {
          color: var(--primary-text-color);
          outline: none;
        }
        .tab-bar button.active {
          color: var(--primary-color);
          border-bottom-color: var(--primary-color);
        }
        .tab-content[hidden] {
          display: none;
        }
        .admin-warning {
          margin-top: 12px;
          padding: 8px 12px;
          background: var(--warning-color, #ff9800);
          color: var(--text-primary-color, #fff);
          border-radius: 4px;
          font-size: 0.9rem;
        }
        .toggle-stack {
          display: flex;
          flex-direction: column;
          gap: 12px;
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
        <ha-input id="lockly-title" class="field" label="Title (optional)"></ha-input>
        ${entrySelect}
        <div class="tab-bar" role="tablist">
          <button type="button" role="tab" data-tab="locks" class="${activeTab === "locks" ? "active" : ""}">Locks</button>
          <button type="button" role="tab" data-tab="settings" class="${activeTab === "settings" ? "active" : ""}">Settings</button>
          <button type="button" role="tab" data-tab="admins" class="${activeTab === "admins" ? "active" : ""}">Admins</button>
        </div>
        <div class="tab-content" data-tab="locks" ${activeTab === "locks" ? "" : "hidden"}>
          <p class="section-desc">
            Locks or lock groups managed by this card.
          </p>
          <ha-form id="lockly-entities-form"></ha-form>
        </div>
        <div class="tab-content" data-tab="settings" ${activeTab === "settings" ? "" : "hidden"}>
          <div class="toggle-stack">
            <ha-formfield label="Only admins can see PINs and edit">
              <ha-switch id="lockly-admin-only"></ha-switch>
            </ha-formfield>
            <ha-formfield label="Simulation mode (no MQTT)">
              <ha-switch id="lockly-dry-run"></ha-switch>
            </ha-formfield>
            <ha-formfield label="Show Apply all button">
              <ha-switch id="lockly-show-bulk-actions"></ha-switch>
            </ha-formfield>
          </div>
        </div>
        <div class="tab-content" data-tab="admins" ${activeTab === "admins" ? "" : "hidden"}>
          <p class="section-desc">
            Non-admin users who can see PINs and edit slots. Pick the person entity for each user.
          </p>
          <ha-form id="lockly-admin-users-form"></ha-form>
          <p class="admin-warning" id="lockly-admin-legacy-warning" hidden></p>
        </div>
      </div>
    `;
    const titleField = this.querySelector("#lockly-title");
    if (titleField) {
      titleField.value = title;
      titleField.addEventListener("change", (ev) => this._handleTitleChange(ev));
    }
    const adminUsersForm = this.querySelector("#lockly-admin-users-form");
    if (adminUsersForm) {
      const adminUsers = Array.isArray(this._config?.admin_users)
        ? this._config.admin_users
        : [];
      // Split admin_users into picker-friendly entries (person entity IDs)
      // and "legacy" entries (raw user IDs with no linked person on this
      // install). Picker only edits the former; the latter are carried
      // through saves unchanged so we don't lose data, with a warning
      // surfaced so the user knows they exist.
      const states = this._hass?.states || {};
      const pickerValue = [];
      const legacyEntries = [];
      for (const value of adminUsers) {
        const str = String(value || "");
        if (!str) continue;
        if (str.startsWith("person.")) {
          pickerValue.push(str);
          continue;
        }
        let resolved = null;
        for (const stateId in states) {
          if (
            stateId.startsWith("person.") &&
            states[stateId]?.attributes?.user_id === str
          ) {
            resolved = stateId;
            break;
          }
        }
        if (resolved) {
          pickerValue.push(resolved);
        } else {
          legacyEntries.push(str);
        }
      }
      const warning = this.querySelector("#lockly-admin-legacy-warning");
      if (warning) {
        if (legacyEntries.length) {
          warning.hidden = false;
          warning.textContent = `${legacyEntries.length} legacy user ID${legacyEntries.length === 1 ? "" : "s"} kept as-is (no linked person on this install). Create a Person and link it to migrate via the picker.`;
        } else {
          warning.hidden = true;
        }
      }
      adminUsersForm.hass = this._hass;
      adminUsersForm.schema = [
        {
          name: "admin_users",
          selector: { entity: { multiple: true, domain: "person" } },
        },
      ];
      adminUsersForm.data = { admin_users: pickerValue };
      adminUsersForm.computeLabel = () => "Users";
      adminUsersForm.addEventListener("value-changed", (ev) => {
        const value = ev.detail?.value || {};
        const fromPicker = Array.isArray(value.admin_users)
          ? value.admin_users
          : [];
        this._config = {
          ...this._config,
          admin_users: [...fromPicker, ...legacyEntries],
        };
        this._emitConfigChanged();
      });
    }
    this.querySelectorAll(".tab-bar button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.getAttribute("data-tab");
        if (!tab || tab === this._activeTab) {
          return;
        }
        this._activeTab = tab;
        this.querySelectorAll(".tab-bar button").forEach((b) => {
          b.classList.toggle("active", b.getAttribute("data-tab") === tab);
        });
        this.querySelectorAll(".tab-content").forEach((c) => {
          c.hidden = c.getAttribute("data-tab") !== tab;
        });
      });
    });
    const select = this.querySelector("#lockly-entry-select");
    if (select) {
      if (selected) {
        select.value = selected;
      }
      select.addEventListener("change", (ev) => {
        const val = ev.target?.value ?? "";
        if (val) {
          this._config = { ...this._config, entry_id: val };
          this._emitConfigChanged();
        }
      });
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
