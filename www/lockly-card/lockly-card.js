const DEFAULT_TITLE = "Lockly";

class LocklyCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entry_id) {
      throw new Error("Lockly card requires an entry_id.");
    }
    this._config = config;
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

  getCardSize() {
    return 3;
  }

  _getSlots() {
    const states = Object.values(this._hass.states || {});
    const slotEntities = states.filter(
      (state) =>
        state.attributes &&
        state.attributes.lockly_entry_id === this._config.entry_id
    );
    const slots = {};
    for (const entity of slotEntities) {
      const slotId = entity.attributes.lockly_slot;
      if (!slots[slotId]) {
        slots[slotId] = {};
      }
      const type = entity.attributes.lockly_type;
      slots[slotId][type] = entity;
    }
    return Object.keys(slots)
      .map((slot) => ({
        id: Number(slot),
        name: slots[slot].name,
        pin: slots[slot].pin,
        enabled: slots[slot].enabled,
      }))
      .sort((a, b) => a.id - b.id);
  }

  _render() {
    if (!this._hass || !this._card) {
      return;
    }
    const title = this._config.title || DEFAULT_TITLE;
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
        .clickable {
          cursor: pointer;
          text-decoration: underline;
          text-decoration-color: transparent;
        }
        .clickable:hover {
          text-decoration-color: var(--primary-text-color);
        }
        .apply-button {
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
        <mwc-button id="add-slot" outlined>Add slot</mwc-button>
        <mwc-button id="apply-all" outlined>Apply all</mwc-button>
        <mwc-button id="wipe-all" outlined>Wipe</mwc-button>
      </div>
      ${
        slots.length
          ? `<table class="slot-table">
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Name</th>
                  <th>PIN</th>
                  <th>Enabled</th>
                  <th>Apply</th>
                </tr>
              </thead>
              <tbody>
                ${slots
                  .map(
                    (slot) => `
                  <tr class="slot-row ${slot.enabled?.attributes?.busy ? "busy" : ""}">
                    <td>${slot.id}</td>
                    <td class="clickable" data-more-info="${
                      slot.name?.entity_id || ""
                    }">${slot.name?.state || ""}</td>
                    <td class="clickable" data-more-info="${
                      slot.pin?.entity_id || ""
                    }">${slot.pin?.state || ""}</td>
                    <td>
                      <ha-switch data-entity="${
                        slot.enabled?.entity_id || ""
                      }" ${slot.enabled?.state === "on" ? "checked" : ""}></ha-switch>
                    </td>
                    <td>
                      <mwc-button class="apply-button" data-apply="${
                        slot.id
                      }" outlined>Apply</mwc-button>
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
    this._card.querySelectorAll("[data-more-info]").forEach((el) => {
      el.addEventListener("click", () => {
        const entityId = el.getAttribute("data-more-info");
        if (entityId) {
          this._fireEvent("hass-more-info", { entityId });
        }
      });
    });
    this._card.querySelectorAll("ha-switch").forEach((el) => {
      el.addEventListener("change", () => {
        const entityId = el.getAttribute("data-entity");
        if (!entityId) {
          return;
        }
        const stateObj = this._hass.states[entityId];
        const service = stateObj?.state === "on" ? "turn_off" : "turn_on";
        this._hass.callService("switch", service, { entity_id: entityId });
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
  }

  _fireEvent(type, detail) {
    const event = new Event(type, {
      bubbles: true,
      composed: true,
    });
    event.detail = detail;
    this.dispatchEvent(event);
  }
}

customElements.define("lockly-card", LocklyCard);
