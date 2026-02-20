const RESOURCE_URL = import.meta.url;
const CARD_VERSION = new URL(RESOURCE_URL).searchParams.get("v") || "0.0.0";
const WS_ACTIVITY_TYPE = "lockly/recent_activity";
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
console.info(`%c Lockly Activity Card ${CARD_VERSION} loaded`, BANNER_STYLE);

const ACTION_ICONS = {
  unlock: "mdi:lock-open",
  lock: "mdi:lock",
  key_lock: "mdi:key",
  key_unlock: "mdi:key",
  auto_lock: "mdi:lock-clock",
  manual_lock: "mdi:hand-back-left",
  manual_unlock: "mdi:hand-back-left",
  one_touch_lock: "mdi:gesture-tap",
  lock_failure_invalid_pin_or_id: "mdi:lock-alert",
  unlock_failure_invalid_pin_or_id: "mdi:lock-alert",
  lock_failure_invalid_schedule: "mdi:calendar-remove",
  unlock_failure_invalid_schedule: "mdi:calendar-remove",
  schedule_lock: "mdi:calendar-lock",
  schedule_unlock: "mdi:calendar-lock",
  pin_code_added: "mdi:plus-circle",
  pin_code_deleted: "mdi:minus-circle",
  non_access_user_operational_event: "mdi:account-alert",
  unknown: "mdi:help-circle",
};

const ACTION_LABELS = {
  unlock: "Unlocked",
  lock: "Locked",
  key_lock: "Key locked",
  key_unlock: "Key unlocked",
  auto_lock: "Auto locked",
  manual_lock: "Locked",
  manual_unlock: "Unlocked",
  one_touch_lock: "One-touch locked",
  lock_failure_invalid_pin_or_id: "Failed unlock (bad PIN)",
  unlock_failure_invalid_pin_or_id: "Failed unlock (bad PIN)",
  lock_failure_invalid_schedule: "Failed (schedule)",
  unlock_failure_invalid_schedule: "Failed (schedule)",
  schedule_lock: "Schedule locked",
  schedule_unlock: "Schedule unlocked",
  pin_code_added: "PIN added",
  pin_code_deleted: "PIN deleted",
  non_access_user_operational_event: "Non-access event",
  unknown: "Unknown",
};

const SOURCE_LABELS = {
  keypad: "Keypad",
  rfid: "RFID",
  manual: "Manual",
  rf: "Automation",
  remote: "Automation",
  automation: "Automation",
};

function relativeTime(isoString) {
  const then = new Date(isoString);
  const now = new Date();
  const diffMs = now - then;
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

class LocklyActivityCard extends HTMLElement {
  setConfig(config) {
    this._config = { view: "recent", max_events: 5, ...config };
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this.appendChild(this._card);
    }
    this._events = this._events || [];
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._config && !this._fetched) {
      this._fetched = true;
      this._fetchEvents();
    }
  }

  connectedCallback() {
    if (this._hass && this._config) {
      this._fetchEvents();
    }
    this._pollTimer = setInterval(() => this._fetchEvents(), 5000);
  }

  disconnectedCallback() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  }

  getCardSize() {
    const count = this._events ? this._events.length : 0;
    return Math.max(2, Math.min(count + 1, 8));
  }

  async _fetchEvents() {
    if (!this._hass?.connection || !this._config?.entry_id) return;
    try {
      const events = await this._hass.connection.sendMessagePromise({
        type: WS_ACTIVITY_TYPE,
        entry_id: this._config.entry_id,
        max_events: this._config.max_events || 5,
      });
      this._events = events || [];
      this._render();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.debug("Lockly activity fetch failed", err);
    }
  }

  _getViewEvents() {
    if (this._config.view === "per_lock") {
      const seen = new Map();
      for (const evt of this._events) {
        if (!seen.has(evt.lock)) {
          seen.set(evt.lock, evt);
        }
      }
      return Array.from(seen.values());
    }
    return this._events;
  }

  _lastUnlockFor(lockName) {
    const isUnlock = (e) =>
      e.lock === lockName &&
      e.action.endsWith("unlock") &&
      !e.action.includes("failure");
    return (
      this._events.find((e) => isUnlock(e) && e.user_name) ||
      this._events.find(isUnlock)
    );
  }

  _findLockEntityId(lockName) {
    if (!this._hass) return null;
    const slug = lockName.toLowerCase().replace(/\s+/g, "_").replace(/-/g, "_");
    const candidates = [`lock.${slug}`, `lock.${slug}_lock`];
    for (const eid of candidates) {
      if (this._hass.states[eid]) return eid;
    }
    return null;
  }

  _navigateToHistory(lockName) {
    const entityId = this._findLockEntityId(lockName);
    if (entityId) {
      const path = `/history?entity_id=${entityId}`;
      history.pushState(null, "", path);
      window.dispatchEvent(new CustomEvent("location-changed"));
    }
  }

  _render() {
    if (!this._hass || !this._card) return;

    if (!this._config?.entry_id) {
      this._card.innerHTML = `
        <div class="card-content" style="padding: 16px; color: var(--secondary-text-color);">
          Lockly Activity Card requires an entry_id. Open the card editor to configure.
        </div>`;
      return;
    }

    const title = this._config.title || "Lock Activity";
    const isPerLock = this._config.view === "per_lock";
    const events = this._getViewEvents();

    this._card.innerHTML = `
      <style>
        .la-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 16px 8px 16px;
        }
        .la-title {
          font-size: 1.1rem;
          font-weight: 500;
          color: var(--primary-text-color);
        }
        .la-tabs {
          display: inline-flex;
          gap: 2px;
          font-size: 0.8rem;
        }
        .la-tabs button {
          cursor: pointer;
          border: none;
          background: none;
          padding: 2px 6px;
          color: var(--secondary-text-color);
          font-weight: 400;
          font-size: inherit;
          opacity: 0.7;
        }
        .la-tabs button:hover {
          opacity: 1;
        }
        .la-tabs button.active {
          color: var(--primary-color);
          font-weight: 500;
          opacity: 1;
        }
        .la-tabs .la-sep {
          color: var(--divider-color, rgba(0,0,0,0.2));
          font-weight: 300;
          align-self: center;
          font-size: 0.75rem;
        }
        .la-list {
          padding: 0 16px 16px;
        }
        .la-row {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 0;
          border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.08));
        }
        .la-row:last-child {
          border-bottom: none;
        }
        .la-icon {
          flex-shrink: 0;
          width: 36px;
          height: 36px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
          --mdc-icon-size: 20px;
        }
        .la-icon.la-unlock {
          background: var(--success-color, #4caf50);
        }
        .la-icon.la-lock {
          background: var(--info-color, #2196f3);
        }
        .la-icon.la-fail {
          background: var(--error-color, #f44336);
        }
        .la-icon.la-other {
          background: var(--secondary-text-color, #888);
        }
        .la-details {
          flex: 1;
          min-width: 0;
        }
        .la-action-line {
          font-size: 0.95rem;
          font-weight: 500;
          color: var(--primary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .la-meta {
          font-size: 0.8rem;
          color: var(--secondary-text-color);
          margin-top: 2px;
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
        }
        .la-source {
          display: inline-block;
          font-size: 0.7rem;
          padding: 1px 6px;
          border-radius: 8px;
          background: var(--divider-color, rgba(0,0,0,0.08));
          color: var(--secondary-text-color);
          font-weight: 500;
          text-transform: uppercase;
          letter-spacing: 0.3px;
        }
        .la-time {
          flex-shrink: 0;
          font-size: 0.8rem;
          color: var(--secondary-text-color);
          text-align: right;
          white-space: nowrap;
        }
        .la-empty {
          padding: 24px 16px;
          color: var(--secondary-text-color);
          text-align: center;
        }
        .la-row {
          cursor: pointer;
        }
        .la-row:hover {
          background: var(--divider-color, rgba(0,0,0,0.04));
          border-radius: 8px;
        }
      </style>
      <div class="la-header">
        <span class="la-title">${escapeHtml(title)}</span>
        <div class="la-tabs">
          <button data-view="recent" class="${isPerLock ? "" : "active"}">Recent</button>
          <span class="la-sep">|</span>
          <button data-view="per_lock" class="${isPerLock ? "active" : ""}">Per Lock</button>
        </div>
      </div>
      ${
        events.length
          ? `<div class="la-list">${events.map((evt) => this._renderRow(evt)).join("")}</div>`
          : '<div class="la-empty">No lock activity yet</div>'
      }`;

    this._card.querySelectorAll(".la-tabs button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const view = btn.getAttribute("data-view");
        if (view && view !== this._config.view) {
          this._config = { ...this._config, view };
          this._render();
        }
      });
    });

    this._card.querySelectorAll(".la-row[data-lock]").forEach((row) => {
      row.addEventListener("click", () => {
        const lockName = row.getAttribute("data-lock");
        if (lockName) this._navigateToHistory(lockName);
      });
    });
  }

  _isLockAction(action) {
    return (
      action === "lock" ||
      action === "auto_lock" ||
      action === "key_lock" ||
      action === "manual_lock" ||
      action === "one_touch_lock" ||
      action === "schedule_lock"
    );
  }

  _renderRow(evt) {
    const action = evt.action || "unknown";
    const icon = ACTION_ICONS[action] || "mdi:help-circle";
    const label = ACTION_LABELS[action] || action;
    const lockName = escapeHtml(evt.lock || "Unknown lock");
    const rawLock = evt.lock || "";
    const userName = evt.user_name ? escapeHtml(evt.user_name) : null;
    const slotId = evt.slot_id != null ? `Slot ${evt.slot_id}` : null;
    const who = userName || slotId || "";
    const source = evt.source ? SOURCE_LABELS[evt.source] || evt.source : "";
    const time = evt.timestamp ? relativeTime(evt.timestamp) : "";

    let iconClass = "la-other";
    if (action.includes("unlock") || action === "key_unlock") {
      iconClass = "la-unlock";
    } else if (
      action.includes("lock") &&
      !action.includes("fail") &&
      !action.includes("failure")
    ) {
      iconClass = "la-lock";
    } else if (action.includes("fail") || action.includes("failure")) {
      iconClass = "la-fail";
    }

    const metaParts = [];
    if (who) metaParts.push(escapeHtml(who));
    if (source)
      metaParts.push(`<span class="la-source">${escapeHtml(source)}</span>`);

    const isAnonymousUnlock =
      !who &&
      action.endsWith("unlock") &&
      !action.includes("failure");
    if (this._isLockAction(action) || isAnonymousUnlock) {
      const lastUnlock = this._lastUnlockFor(rawLock);
      if (lastUnlock) {
        const unlockWho =
          lastUnlock.user_name ||
          (lastUnlock.slot_id != null ? `Slot ${lastUnlock.slot_id}` : null);
        if (unlockWho) {
          const unlockTime = lastUnlock.timestamp
            ? relativeTime(lastUnlock.timestamp)
            : "";
          const timeSuffix = unlockTime ? ` (${unlockTime})` : "";
          metaParts.push(
            `Last unlocked by ${escapeHtml(unlockWho)}${timeSuffix}`
          );
        }
      }
    }

    return `
      <div class="la-row" data-lock="${escapeHtml(rawLock)}">
        <div class="la-icon ${iconClass}">
          <ha-icon icon="${icon}"></ha-icon>
        </div>
        <div class="la-details">
          <div class="la-action-line">${lockName} &middot; ${escapeHtml(label)}</div>
          ${metaParts.length ? `<div class="la-meta">${metaParts.join(" ")}</div>` : ""}
        </div>
        <div class="la-time">${time}</div>
      </div>`;
  }
}

LocklyActivityCard.getConfigElement = () =>
  document.createElement("lockly-activity-card-editor");
LocklyActivityCard.getStubConfig = () => ({
  title: "Lock Activity",
  entry_id: "",
  view: "recent",
  max_events: 5,
});
LocklyActivityCard.prototype.getConfigElement =
  LocklyActivityCard.getConfigElement;

if (!customElements.get("lockly-activity-card")) {
  customElements.define("lockly-activity-card", LocklyActivityCard);
}

// --- Card Editor ---

class LocklyActivityCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = {
      title: "Lock Activity",
      view: "recent",
      max_events: 5,
      ...config,
    };
    this._needsRender = true;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._entriesLoaded) {
      this._entriesLoaded = true;
      this._loadEntries();
    }
    if (this._needsRender || !this._rendered) {
      this._render();
    }
  }

  get value() {
    return this._config;
  }

  async _loadEntries() {
    if (!this._hass?.connection) return;
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
    if (!this._hass) return;
    this._needsRender = false;
    this._rendered = true;

    const entries = this._entries || [];
    const selected = this._config?.entry_id || "";
    const title = this._config?.title || "";
    const view = this._config?.view || "recent";
    const maxEvents = this._config?.max_events || 5;

    const entrySelect =
      entries.length > 1
        ? `<ha-select id="la-entry" class="field" label="Lockly instance">
            ${entries
              .map((entry) => {
                const label = entry.title || entry.entry_id;
                const isSelected =
                  entry.entry_id === selected ? "selected" : "";
                return `<mwc-list-item value="${entry.entry_id}" ${isSelected}>${label}</mwc-list-item>`;
              })
              .join("")}
          </ha-select>`
        : "";

    this.innerHTML = `
      <style>
        .container { padding: 16px; }
        .field { margin-bottom: 16px; width: 100%; }
        .toggle-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 16px;
        }
      </style>
      <div class="container">
        <ha-textfield id="la-title" class="field" label="Title"></ha-textfield>
        ${entrySelect}
        <ha-select id="la-view" class="field" label="Default view">
          <mwc-list-item value="recent" ${view === "recent" ? "selected" : ""}>Recent Activity</mwc-list-item>
          <mwc-list-item value="per_lock" ${view === "per_lock" ? "selected" : ""}>Per Lock</mwc-list-item>
        </ha-select>
        <ha-textfield
          id="la-max"
          class="field"
          label="Max events"
          type="number"
          min="1"
          max="100"
        ></ha-textfield>
      </div>`;

    const titleField = this.querySelector("#la-title");
    if (titleField) {
      titleField.value = title;
      titleField.addEventListener("change", (ev) => {
        this._config = { ...this._config, title: ev.target.value };
        this._emitConfigChanged();
      });
    }

    const entryField = this.querySelector("#la-entry");
    if (entryField) {
      if (selected) entryField.value = selected;
      const handler = (ev) => {
        const val = ev.detail?.value ?? ev.target?.value ?? "";
        if (val && val !== this._config?.entry_id) {
          this._config = { ...this._config, entry_id: val };
          this._emitConfigChanged();
        }
      };
      entryField.addEventListener("value-changed", handler);
      entryField.addEventListener("selected", handler);
      entryField.addEventListener("change", handler);
    }

    const viewField = this.querySelector("#la-view");
    if (viewField) {
      viewField.value = view;
      const handler = (ev) => {
        const val = ev.detail?.value ?? ev.target?.value ?? "";
        if (val) {
          this._config = { ...this._config, view: val };
          this._emitConfigChanged();
        }
      };
      viewField.addEventListener("value-changed", handler);
      viewField.addEventListener("selected", handler);
      viewField.addEventListener("change", handler);
    }

    const maxField = this.querySelector("#la-max");
    if (maxField) {
      maxField.value = String(maxEvents);
      maxField.addEventListener("change", (ev) => {
        const val = parseInt(ev.target.value, 10);
        if (val >= 1 && val <= 100) {
          this._config = { ...this._config, max_events: val };
          this._emitConfigChanged();
        }
      });
    }
  }
}

if (!customElements.get("lockly-activity-card-editor")) {
  customElements.define("lockly-activity-card-editor", LocklyActivityCardEditor);
}

window.customCards = window.customCards || [];
if (
  !window.customCards.find((card) => card.type === "lockly-activity-card")
) {
  window.customCards.push({
    type: "lockly-activity-card",
    name: "Lockly Activity Card",
    description: "Show recent lock activity: who unlocked, when, and how",
  });
}
