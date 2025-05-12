// filepath: c:\Users\bball\OneDrive\Documents\hass-savant-pbc\hass-savant-pbc\custom_components\savant_energy\savant-energy-scenes-card.js
// Savant Energy Scenes Card v1.0.0

// Register the card in the customCards array - important for Home Assistant to discover the card
console.info(
  "%c SAVANT-ENERGY-SCENES-CARD %c v1.0.0 ",
  "color: white; background: #4CAF50; font-weight: 700;",
  "color: #4CAF50; background: white; font-weight: 700;"
);

class SavantEnergyScenesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._entities = [];
    this._scenes = [];
    this._selectedScene = null;
    this._sceneName = "";
    this._relayStates = {};
    this._mode = "create"; // or "edit"
  }

  set hass(hass) {
    this._hass = hass;
    this._entities = Object.values(hass.states)
      .filter(e => e.entity_id.startsWith("switch.") && e.attributes.device_class === "switch");
    this._fetchScenes();
    this.render();
  }

  async _fetchScenes() {
    // Fetch scenes from Home Assistant state (button entities)
    this._scenes = Object.values(this._hass.states)
      .filter(e => e.entity_id.startsWith("button.savant_energy_scene_"))
      .map(e => ({
        id: e.entity_id.replace("button.savant_energy_scene_", "scene_"),
        name: e.attributes.friendly_name,
      }));
    this.render();
  }

  _onToggle(entity_id) {
    this._relayStates[entity_id] = !this._relayStates[entity_id];
    this.render();
  }

  _onSceneSelect(e) {
    const sceneId = e.target.value;
    if (!sceneId) {
      this._selectedScene = null;
      this._sceneName = "";
      this._mode = "create";
      this._relayStates = {};
      this._entities.forEach(ent => this._relayStates[ent.entity_id] = true);
      this.render();
      return;
    }
    this._selectedScene = sceneId;
    this._mode = "edit";
    // Fetch relay states for the selected scene via a service call
    this._hass.callWS({
      type: "config/entity_registry/get",
      entity_id: `button.savant_energy_scene_${sceneId.replace("scene_", "")}`
    }).then(entity => {
      // Not all info is available, so just set all to true for now
      this._sceneName = this._scenes.find(s => s.id === sceneId)?.name || "";
      this._entities.forEach(ent => this._relayStates[ent.entity_id] = true);
      this.render();
    });
  }

  _onNameChange(e) {
    this._sceneName = e.target.value;
  }

  _onCreateOrUpdate() {
    const relayStates = {};
    this._entities.forEach(ent => {
      relayStates[ent.attributes.friendly_name] = !!this._relayStates[ent.entity_id];
    });
    if (this._mode === "create") {
      this._hass.callService("savant_energy", "create_scene", {
        name: this._sceneName || "New Scene",
        relay_states: relayStates
      });
    } else if (this._mode === "edit" && this._selectedScene) {
      this._hass.callService("savant_energy", "update_scene", {
        scene_id: this._selectedScene,
        name: this._sceneName,
        relay_states: relayStates
      });
    }
    this._selectedScene = null;
    this._sceneName = "";
    this._mode = "create";
    this._relayStates = {};
    this._entities.forEach(ent => this._relayStates[ent.entity_id] = true);
    setTimeout(() => this._fetchScenes(), 1000);
  }

  _onDelete() {
    if (this._selectedScene) {
      this._hass.callService("savant_energy", "delete_scene", {
        scene_id: this._selectedScene
      });
      this._selectedScene = null;
      this._sceneName = "";
      this._mode = "create";
      this._relayStates = {};
      this._entities.forEach(ent => this._relayStates[ent.entity_id] = true);
      setTimeout(() => this._fetchScenes(), 1000);
    }
  }

  render() {
    if (!this._hass) return;
    const style = `
      <style>
        .card { font-family: var(--primary-font-family); background: var(--card-background-color, #fff); border-radius: 12px; box-shadow: var(--ha-card-box-shadow); padding: 20px; }
        .header { font-size: 1.3em; font-weight: bold; margin-bottom: 12px; }
        .switch-list { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
        .switch-item { display: flex; align-items: center; background: #f5f5f5; border-radius: 8px; padding: 6px 12px; }
        .switch-label { margin-left: 8px; }
        .scene-controls { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
        .scene-select { flex: 1; }
        .scene-actions { display: flex; gap: 8px; }
        .input { padding: 4px 8px; border-radius: 6px; border: 1px solid #ccc; }
        button { background: var(--primary-color, #03a9f4); color: #fff; border: none; border-radius: 6px; padding: 6px 16px; font-size: 1em; cursor: pointer; }
        button[disabled] { background: #ccc; cursor: not-allowed; }
        .delete-btn { background: #e53935; }
      </style>
    `;
    const switches = this._entities.map(ent => `
      <div class="switch-item">
        <input type="checkbox" id="${ent.entity_id}" ${this._relayStates[ent.entity_id] !== false ? "checked" : ""}>
        <label class="switch-label" for="${ent.entity_id}">${ent.attributes.friendly_name || ent.entity_id}</label>
      </div>
    `).join("");
    const sceneOptions = `<option value="">New Scene</option>` + this._scenes.map(s => `
      <option value="${s.id}" ${this._selectedScene === s.id ? "selected" : ""}>${s.name}</option>
    `).join("");
    this.shadowRoot.innerHTML = `
      ${style}
      <div class="card">
        <div class="header">Savant Energy Scenes</div>
        <div class="scene-controls">
          <select class="scene-select input">
            ${sceneOptions}
          </select>
          <input class="input" type="text" placeholder="Scene name" value="${this._sceneName}">
          <div class="scene-actions">
            <button ${!this._sceneName ? "disabled" : ""}>
              ${this._mode === "edit" ? "Update" : "Create"}
            </button>
            ${this._mode === "edit" ? `<button class="delete-btn">Delete</button>` : ""}
          </div>
        </div>
        <div class="switch-list">
          ${switches}
        </div>
      </div>
    `;
    // Attach event listeners (since lit-html is not used)
    this.shadowRoot.querySelectorAll("input[type=checkbox]").forEach(cb => {
      cb.addEventListener("change", e => this._onToggle(e.target.id));
    });
    this.shadowRoot.querySelector(".scene-select").addEventListener("change", e => this._onSceneSelect(e));
    this.shadowRoot.querySelectorAll("input[type=text]").forEach(inp => {
      inp.addEventListener("input", e => this._onNameChange(e));
    });
    this.shadowRoot.querySelectorAll("button").forEach(btn => {
      if (btn.textContent === "Create" || btn.textContent === "Update") {
        btn.addEventListener("click", () => this._onCreateOrUpdate());
      }
      if (btn.textContent === "Delete") {
        btn.addEventListener("click", () => this._onDelete());
      }
    });
  }

  setConfig(config) {
    if (!config) {
      throw new Error("No configuration provided");
    }
    this._config = config;
  }

  getCardSize() { return 3; }
}

// Add card to the custom cards list for discovery
window.customCards = window.customCards || [];
window.customCards.push({
  type: "savant-energy-scenes-card",
  name: "Savant Energy Scenes Card",
  description: "A custom card for Savant Energy scenes."
});

// Register the custom element with the browser
customElements.define("savant-energy-scenes-card", SavantEnergyScenesCard);
