// API utility for Savant Energy Scenes Card
// Handles all REST API calls to the Home Assistant backend

class SavantEnergyApi {
  constructor(hass) {
    this._hass = hass;
  }

  async fetchScenes() {
    const resp = await this._hass.callApi("GET", "savant_energy/scenes");
    if (resp && resp.scenes) {
      return resp.scenes.map(s => ({ id: s.scene_id, name: s.name }));
    }
    return [];
  }

  async fetchBreakers(sceneId) {
    if (!sceneId) return { entities: [], relayStates: {} };
    const result = await this._hass.callApi("GET", `savant_energy/scene_breakers/${sceneId}`);
    if (result && result.breakers && typeof result.breakers === 'object') {
      return {
        relayStates: { ...result.breakers },
        entities: Object.keys(result.breakers).map(entity_id => ({ entity_id }))
      };
    }
    return { entities: [], relayStates: {} };
  }

  async createScene(name, relayStates) {
    return await this._hass.callApi("POST", "savant_energy/scenes", {
      name,
      relay_states: relayStates || {},
    });
  }

  async updateScene(sceneId, name, relayStates) {
    return await this._hass.callApi("POST", `savant_energy/scenes/${sceneId}`,
      { name, relay_states: relayStates || {} }
    );
  }

  async deleteScene(sceneId) {
    return await this._hass.callApi("DELETE", `savant_energy/scenes/${sceneId}`);
  }
}

// CSS for Savant Energy Scenes Card
// Export as a string for easy import

const cardStyle = `
  <style>
    .card {
      font-family: var(--primary-font-family);
      background: var(--card-background-color, #fff);
      border-radius: 12px;
      box-shadow: var(--ha-card-box-shadow);
      padding: 12px;
    }
    .header {
      font-size: 1.1em;
      font-weight: bold;
      margin-bottom: 6px;
    }
    .pill-toggle {
      display: flex;
      width: 100%;
      margin: 0 0 10px 0;
      background: var(--secondary-background-color, #f0f0f0);
      border-radius: 999px;
      padding: 2px;
      border: 1px solid var(--divider-color, #ddd);
    }
    .pill {
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 0.95em;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.2s, color 0.2s;
      text-align: center;
      flex: 1;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    .pill.selected {
      background: var(--primary-color, #03a9f4);
      color: var(--primary-text-color-on-primary, #fff);
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .breaker-columns {
      display: flex;
      gap: 8px;
      width: 100%;
      max-width: 100%;
    }
    .breaker-col {
      flex: 1 1 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }
    .breaker-switch-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
    }
    .breaker-label {
      font-size: 0.73em;
      color: var(--primary-text-color, #222);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 120px;
    }
    .breaker-switch {
      width: 36px;
      height: 18px;
      border-radius: 9px;
      background: var(--disabled-color, #e0e0e0);
      border: 1px solid var(--divider-color, #bbb);
      position: relative;
      cursor: pointer;
      transition: background 0.2s, border-color 0.2s;
      display: flex;
      align-items: center;
      outline: none;
    }
    .breaker-switch.on {
      background: var(--primary-color, #03a9f4);
      border-color: var(--primary-color, #03a9f4);
    }
    .breaker-switch.off {
      background: var(--disabled-color, #e0e0e0);
      border-color: var(--divider-color, #bbb);
    }
    .breaker-switch-thumb {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 1px 2px rgba(0,0,0,0.08);
      position: absolute;
      left: 2px;
      top: 1px;
      transition: left 0.2s;
    }
    .breaker-switch.on .breaker-switch-thumb {
      left: 20px;
    }
    .breaker-switch.off .breaker-switch-thumb {
      left: 2px;
    }
    .breaker-switch:focus {
      box-shadow: 0 0 0 2px var(--primary-color, #03a9f4, 0.2);
    }
    .switch-list {
      display: none;
    }
    .scene-controls {
      display: flex;
      gap: 6px;
      align-items: center;
      margin-bottom: 8px;
    }
    .scene-name-input {
      flex: 1 1 0%;
      min-width: 0;
      width: 100%;
    }
    .scene-select {
      flex: 1 1 30%;
      min-width: 130px;
    }
    .scene-name-editor-input {
      flex: 1 1 50%;
    }
    .input {
      padding: 3px 7px;
      border-radius: 6px;
      border: 1px solid var(--divider-color, #ccc);
      height: 24px;
    }
    button {
      background: var(--primary-color, #03a9f4);
      color: var(--primary-text-color-on-primary, #fff);
      border: none;
      border-radius: 6px;
      padding: 4px 10px;
      font-size: 0.95em;
      cursor: pointer;
      height: 24px;
      display: flex;
      align-items: center;
      white-space: nowrap;
    }
    button[disabled] {
      background: var(--disabled-color, #ccc);
      cursor: not-allowed;
    }
    .delete-btn {
      background: #e53935;
    }
    .scene-items {
      list-style: none;
      padding: 0;
      margin: 0;
    }
    .scene-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 5px;
      border-bottom: 1px solid var(--divider-color, #eee);
      font-size: 0.95em;
    }
    .trash-icon {
      color: #e53935;
      cursor: pointer;
      display: flex;
    }
  </style>
`;

// Savant Energy Scenes Card Editor (card, for modular build)
class SavantEnergyScenesCardEditor extends HTMLElement {
  setConfig(config) {
    this.__config = config || {};
  }

  get _config() {
    return this.__config;
  }

  render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    this.shadowRoot.innerHTML = `
      <style>
        ha-switch { padding: 16px 0; }
        .side-by-side { display: flex; }
        .side-by-side > * { flex: 1; padding-right: 4px; }
      </style>
      <div>
        <p>Savant Energy Scenes Card has no configuration options.</p>
        <p>This card provides an interface for managing Savant Energy scenes.</p>
      </div>
    `;
  }

  connectedCallback() {
    this.render();
  }
}

// Register the card in the customCards array - important for Home Assistant to discover the card
console.info(
  "%c SAVANT-ENERGY-SCENES-STANDALONE-CARD %c v2.0.0 ",
  "color: white; background: #4CAF50; font-weight: 700;",
  "color: #4CAF50; background: white; font-weight: 700;"
);

class SavantEnergyScenesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._entities = [];
    this._scenes = [];
    this._selectedScene = null;
    this._sceneName = "";
    this._relayStates = {};
    this._view = "scenes"; // 'scenes' or 'editor'
    this._isRendering = false;
    this._pendingRender = false;
    this._hasInitialRender = false;
    this._errorMessage = "";
    this._currentView = "";
    this.api = null;
    this.shadowRoot.innerHTML = `
      <ha-card header="Savant Energy Scenes">
        <div class="card-content">Loading...</div>
      </ha-card>
    `;
  }

  setConfig(config) {
    this._config = config;
    // If the card needs to react to config changes immediately after being set up
    // and hass is already available, you might trigger a render.
    // For now, just storing the config is the primary requirement.
    if (this._hass) {
      // this._safeRender(); // Uncomment if initial render depends on this config
    }
  }

  static getConfigElement() {
    return document.createElement("savant-energy-scenes-card-editor");
  }

  static getStubConfig() {
    return {};
  }

  set hass(hass) {
    const firstUpdate = this._hass === null;
    this._hass = hass;
    if (!this.api) {
      this.api = new SavantEnergyApi(hass);
    }
    if (firstUpdate || !this._hasInitialRender) {
      this._initializeScenes();
    }
  }

  async _initializeScenes() {
    await this._fetchScenesFromBackend();
  }

  async _fetchScenesFromBackend(triggerRender = true) {
    try {
      const scenes = await this.api.fetchScenes();
      this._scenes = scenes;
    } catch (e) {
      this._scenes = [];
      this._errorMessage = "Error fetching scenes: " + (e.message || "Unknown error");
    }
    if (triggerRender) {
      this._safeRender();
    }
  }

  async _fetchBreakersForEditor(sceneId) {
    if (!sceneId) {
      this._entities = [];
      this._relayStates = {};
      return;
    }
    try {
      const { entities, relayStates } = await this.api.fetchBreakers(sceneId);
      this._entities = entities;
      this._relayStates = relayStates;
    } catch (e) {
      this._entities = [];
      this._relayStates = {};
    }
  }

  async _setView(view) {
    this._currentView = view;
    this._errorMessage = "";
    if (view === 'editor') {
      await this._fetchScenesFromBackend(false);
      const selectedSceneStillExists = this._selectedScene && this._scenes.find(s => s.id === this._selectedScene);
      if (selectedSceneStillExists) {
        const sceneInfo = this._scenes.find(s => s.id === this._selectedScene);
        this._sceneName = sceneInfo?.name || "";
        await this._fetchBreakersForEditor(this._selectedScene);
      } else {
        this._selectedScene = '';
        this._sceneName = "";
        this._entities = [];
        this._relayStates = {};
      }
    }
    this._safeRender();
  }

  async _onSceneSelect(e) {
    const sceneId = e.target.value;
    this._selectedScene = sceneId;
    if (sceneId) {
      const sceneInfo = this._scenes.find(s => s.id === sceneId);
      this._sceneName = sceneInfo?.name || "";
      await this._fetchBreakersForEditor(sceneId);
    } else {
      this._sceneName = "";
      this._entities = [];
      this._relayStates = {};
    }
    this._safeRender();
  }

  _onSceneNameChange(e) {
    this._sceneName = e.target.value;
    if (this._currentView === 'editor') {
      this._safeRender();
    }
  }

  _showToast(message, type = 'error') {
    const oldToast = this.shadowRoot.querySelector('.toast');
    if (oldToast) oldToast.remove();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    this.shadowRoot.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('show');
    }, 10);
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  async _onCreateScene() {
    const newSceneName = this._sceneName.trim();
    if (!newSceneName) return;
    try {
      await this.api.createScene(newSceneName, this._relayStates);
      await this._fetchScenesFromBackend(false);
      const newScene = this._scenes.find(s => s.name === newSceneName);
      this._selectedScene = newScene ? newScene.id : '';
      this._sceneName = '';
      await this._fetchBreakersForEditor(this._selectedScene);
      this._safeRender();
      this._showToast('Scene created successfully!', 'success');
    } catch (e) {
      const detailMessage = this._parseApiErrorMessage(e);
      this._errorMessage = "Error creating scene: " + detailMessage;
      this._safeRender();
      this._showToast(this._errorMessage, 'error');
    }
  }

  async _onSaveEditor() {
    if (!this._selectedScene || !this._sceneName.trim()) {
      this._errorMessage = "Please select a scene and provide a valid name.";
      this._safeRender();
      this._showToast(this._errorMessage, 'error');
      return;
    }
    const newName = this._sceneName.trim();
    try {
      await this.api.updateScene(this._selectedScene, newName, this._relayStates);
      await this._fetchScenesFromBackend(false);
      // Ensure the current scene name reflects the saved name
      const updatedScene = this._scenes.find(s => s.id === this._selectedScene);
      this._sceneName = updatedScene ? updatedScene.name : newName;
      this._safeRender();
      this._showToast('Scene updated successfully!', 'success');
    } catch (e) {
      const detailMessage = this._parseApiErrorMessage(e);
      this._errorMessage = "Error updating scene: " + detailMessage;
      this._safeRender();
      this._showToast(this._errorMessage, 'error');
    }
  }

  async _onDeleteScene(sceneId) {
    try {
      await this.api.deleteScene(sceneId);
      await this._fetchScenesFromBackend(false);
      if (this._selectedScene === sceneId) {
        this._selectedScene = null;
        this._sceneName = "";
        this._entities = [];
        this._relayStates = {};
      }
      this._safeRender();
      this._showToast('Scene deleted successfully!', 'success');
    } catch (e) {
      const detailMessage = this._parseApiErrorMessage(e);
      this._errorMessage = "Error deleting scene: " + detailMessage;
      this._safeRender();
      this._showToast(this._errorMessage, 'error');
    }
  }

  _onRelayToggle(entityId) {
    this._relayStates[entityId] = !this._relayStates[entityId];
    this._safeRender();
  }

  _parseApiErrorMessage(e) {
    let detailMessage = "Unknown error";
    // Check for a response or body property containing the error JSON
    let errorPayload = null;
    if (e && typeof e === 'object') {
      if (e.response) {
        errorPayload = e.response;
      } else if (e.body) {
        errorPayload = e.body;
      }
    }
    // Try to parse errorPayload if present
    if (errorPayload) {
      try {
        const parsed = typeof errorPayload === 'string' ? JSON.parse(errorPayload) : errorPayload;
        if (parsed && parsed.message) {
          return parsed.message;
        }
      } catch {}
    }
    // Fallback to previous logic
    if (typeof e === 'string') {
      try {
        const parsed = JSON.parse(e);
        if (parsed && parsed.message) {
          detailMessage = parsed.message;
        } else {
          detailMessage = e;
        }
      } catch {
        detailMessage = e;
      }
    } else if (e && typeof e === 'object') {
      if (typeof e.message === 'string') {
        try {
          const parsed = JSON.parse(e.message);
          if (parsed && parsed.message) {
            detailMessage = parsed.message;
          } else {
            detailMessage = e.message;
          }
        } catch {
          detailMessage = e.message;
        }
      } else if (e.message) {
        detailMessage = e.message;
      } else if (e.error && typeof e.error === 'string') {
        detailMessage = e.error;
      }
    }
    return detailMessage;
  }

  _safeRender() {
    if (this._isRendering) {
      this._pendingRender = true;
      return;
    }
    this._isRendering = true;
    try {
      this.render();
      this._hasInitialRender = true;
    } catch (error) {
      this.shadowRoot.innerHTML = `
        <ha-card header="Savant Energy Scenes">
          <div class="card-content">
            <p>Error rendering card. Check the browser console for details.</p>
          </div>
        </ha-card>
      `;
    }
    this._isRendering = false;
    if (this._pendingRender) {
      this._pendingRender = false;
      setTimeout(() => this._safeRender(), 10);
    }
  }

  render() {
    if (!this._hass) return;
    const pillToggle = `
      <div class="pill-toggle">
        <div class="pill${this._view === 'scenes' ? ' selected' : ''}" data-view="scenes">Scenes</div>
        <div class="pill${this._view === 'editor' ? ' selected' : ''}" data-view="editor">Editor</div>
      </div>
    `;
    let content = "";
    // Sort scenes alphabetically by name for all usages
    const sortedScenes = [...this._scenes].sort((a, b) => a.name.localeCompare(b.name, undefined, {sensitivity: 'base'}));
    if (this._view === "scenes") {
      content = `
        <div class="scene-controls">
          <input class="input scene-name-input" type="text" placeholder="New scene name" value="${this._sceneName}">
          <button${this._sceneName.trim() === "" ? " disabled" : ""}>Create</button>
        </div>
        <div class="scene-list">
          ${sortedScenes.length === 0 ?
            '<p>No scenes created yet. Enter a name above and click Create.</p>' :
            `<ul class="scene-items">
              ${sortedScenes.map(s => `<li class="scene-item">
                <span>${s.name}</span>
                <span class="trash-icon" data-id="${s.id}">
                  <svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M9,3V4H4V6H5V19A2,2 0 0,0 7,21H17A2,2 0 0,0 19,19V6H20V4H15V3H9M7,6H17V19H7V6M9,8V17H11V8H9M13,8V17H15V8H13Z" /></svg>
                </span>
              </li>`).join("")}
            </ul>`
          }
        </div>
      `;
    } else if (this._view === "editor") {
      // Sort entities alphabetically by display name for breaker list
      let entitiesWithNames = this._entities.map(ent => {
        let displayName = ent.entity_id;
        let logReason = '';
        if (this._hass && this._hass.states && this._hass.states[ent.entity_id]) {
          const stateObj = this._hass.states[ent.entity_id];
          if (stateObj && stateObj.attributes) {
            if (stateObj.attributes.friendly_name) {
              displayName = stateObj.attributes.friendly_name;
              logReason = 'Used friendly_name';
            } else if (stateObj.attributes.name) {
              displayName = stateObj.attributes.name;
              logReason = 'Used name';
            } else {
              logReason = 'No friendly_name or name attribute found, using entity_id';
            }
          } else {
            logReason = 'No attributes found on state object, using entity_id';
          }
        } else {
          logReason = 'No state object found for entity_id';
        }
        return { ...ent, displayName };
      });
      entitiesWithNames.sort((a, b) => a.displayName.localeCompare(b.displayName, undefined, {sensitivity: 'base'}));
      const breakerColumns = [[], []];
      entitiesWithNames.forEach((ent, idx) => {
        const col = idx % 2;
        breakerColumns[col].push(`
          <div class="breaker-switch-row">
            <span class="breaker-label" title="${ent.displayName}">${ent.displayName}</span>
            <div class="breaker-switch${this._relayStates[ent.entity_id] !== false ? ' on' : ' off'}" data-entity="${ent.entity_id}" tabindex="0" role="switch" aria-checked="${this._relayStates[ent.entity_id] !== false}">
              <div class="breaker-switch-thumb"></div>
            </div>
          </div>
        `);
      });
      content = `
        <div class="scene-controls">
          <select class="scene-select input">
            <option value="" ${!this._selectedScene ? "selected" : ""}>Select a scene</option>
            ${sortedScenes.map(s => `<option value="${s.id}" ${this._selectedScene === s.id ? "selected" : ""}>${s.name}</option>`).join("")}
          </select>
          <input class="input scene-name-editor-input" type="text" placeholder="Scene name" value="${this._sceneName}" ${!this._selectedScene ? "disabled" : ""}>
          <button class="save-scene-button" ${(!this._selectedScene || !this._sceneName.trim()) ? " disabled" : ""}>Save</button>
        </div>
        <div class="breaker-columns">
          <div class="breaker-col">${breakerColumns[0].join("")}</div>
          <div class="breaker-col">${breakerColumns[1].join("")}</div>
        </div>
      `;
    }
    this.shadowRoot.innerHTML = `
      <ha-card>
        ${cardStyle}
        <div class="card">
          <div class="header">Savant Energy Scenes</div>
          ${pillToggle}
          ${content || '<div class="card-content">No content available</div>'}
        </div>
        <style>
          .toast {
            position: fixed;
            left: 50%;
            bottom: 32px;
            transform: translateX(-50%) translateY(40px);
            background: #323232;
            color: #fff;
            padding: 10px 24px;
            border-radius: 6px;
            font-size: 1em;
            opacity: 0;
            pointer-events: none;
            z-index: 9999;
            transition: opacity 0.3s, transform 0.3s;
          }
          .toast.show {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
            pointer-events: auto;
          }
          .toast-success {
            background: #4caf50;
          }
          .toast-error {
            background: #e53935;
          }
        </style>
      </ha-card>
    `;
    this.shadowRoot.querySelectorAll('.pill').forEach(pill => {
      pill.addEventListener('click', e => {
        const view = pill.getAttribute('data-view');
        this._view = view;
        this._setView(view);
      });
    });
    if (this._view === 'scenes') {
      const inputEl = this.shadowRoot.querySelector('.scene-name-input');
      const buttonEl = this.shadowRoot.querySelector('button:not(.save-scene-button)');
      if (inputEl && buttonEl) {
        inputEl.addEventListener('input', e => {
          this._onSceneNameChange(e);
          buttonEl.disabled = e.target.value.trim() === "";
        });
        buttonEl.addEventListener('click', async () => {
          if (buttonEl.disabled) return;
          await this._onCreateScene();
        });
      }
      this.shadowRoot.querySelectorAll('.trash-icon').forEach(btn => {
        btn.addEventListener('click', e => {
          const id = btn.getAttribute('data-id');
          this._onDeleteScene(id);
        });
      });
    }
    if (this._view === 'editor') {
      this.shadowRoot.querySelector('.scene-select').addEventListener('change', e => this._onSceneSelect(e));
      const editorSceneNameInput = this.shadowRoot.querySelector('.scene-name-editor-input');
      const saveButton = this.shadowRoot.querySelector('.save-scene-button');
      if (editorSceneNameInput && saveButton) {
        editorSceneNameInput.addEventListener('input', e => this._onSceneNameChange(e));
        saveButton.addEventListener('click', async () => {
          await this._onSaveEditor();
        });
      }
      this.shadowRoot.querySelectorAll('.breaker-switch').forEach(switchEl => {
        switchEl.addEventListener('click', e => {
          const entityId = switchEl.getAttribute('data-entity');
          this._onRelayToggle(entityId);
        });
      });
    }
  }

  getCardSize() {
    return 1;
  }
}

customElements.define("savant-energy-scenes-card", SavantEnergyScenesCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "savant-energy-scenes-card",
  name: "Savant Energy Scenes Card",
  description: "A custom card card for Savant Energy scenes."
});

customElements.define("savant-energy-scenes-card-editor", SavantEnergyScenesCardEditor);


