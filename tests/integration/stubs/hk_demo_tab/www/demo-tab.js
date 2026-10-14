// Test-only panel tab for the Home Keeper e2e suite. It shows the route path that
// the panel gives it, a button that moves the panel to /sub through the host, and 2
// plain links to Home Keeper pages, which the panel opens with no page load.
class HomeKeeperDemoTab extends HTMLElement {
  set hass(value) {
    this._hass = value;
  }
  set narrow(value) {
    this._narrow = value;
    this._render();
  }
  set route(value) {
    this._route = value;
    this._render();
  }
  set host(value) {
    this._host = value;
    this._render();
  }
  get host() {
    return this._host;
  }
  get route() {
    return this._route;
  }
  connectedCallback() {
    this._render();
  }
  _render() {
    if (!this.shadowRoot) {
      const root = this.attachShadow({ mode: 'open' });
      root.innerHTML = `
        <style>
          :host { display: block; }
          ha-card { padding: 16px; }
          .row { margin: 8px 0; }
        </style>
        <ha-card header="Demo library">
          <div class="row">Path: <code id="demo-path"></code></div>
          <div class="row">Host API: <span id="demo-api"></span></div>
          <div class="row"><button id="demo-go" type="button">Open /sub</button></div>
          <div class="row"><a id="demo-link" href="/home-keeper/demo-tab/linked">Open /linked</a></div>
          <div class="row"><a id="demo-appliances" href="/home-keeper/appliances">Appliances</a></div>
        </ha-card>`;
      root.getElementById('demo-go').addEventListener('click', () => {
        if (this._host) this._host.navigate('/sub');
      });
    }
    const path = (this._route && this._route.path) || '/';
    this.shadowRoot.getElementById('demo-path').textContent = path;
    this.shadowRoot.getElementById('demo-api').textContent = this._host
      ? String(this._host.apiVersion)
      : '';
  }
}

if (!customElements.get('home-keeper-demo-tab')) {
  customElements.define('home-keeper-demo-tab', HomeKeeperDemoTab);
}
