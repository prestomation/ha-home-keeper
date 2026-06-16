import { CARD_DESCRIPTION, CARD_NAME, HomeKeeperCard, HomeKeeperCardEditor } from './card';

if (!customElements.get('home-keeper-card')) {
  customElements.define('home-keeper-card', HomeKeeperCard);
}
if (!customElements.get('home-keeper-card-editor')) {
  customElements.define('home-keeper-card-editor', HomeKeeperCardEditor);
}

// Advertise the card in the dashboard "Add card" picker.
interface CustomCard {
  type: string;
  name: string;
  description: string;
  preview?: boolean;
  documentationURL?: string;
}
const w = window as unknown as { customCards?: CustomCard[] };
w.customCards = w.customCards || [];
if (!w.customCards.some((c) => c.type === 'home-keeper-card')) {
  w.customCards.push({
    type: 'home-keeper-card',
    name: CARD_NAME,
    description: CARD_DESCRIPTION,
    preview: true,
    documentationURL: 'https://github.com/prestomation/ha-home-keeper',
  });
}

export { HomeKeeperCard, HomeKeeperCardEditor };
