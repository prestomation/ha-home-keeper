import { HomeKeeperPanel } from './panel';

if (!customElements.get('home-keeper-panel')) {
  customElements.define('home-keeper-panel', HomeKeeperPanel);
}

export { HomeKeeperPanel };
