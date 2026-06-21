import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// User Guide sidebar. Pages are added as the README content is ported over in a
// follow-up step; for now this carries the introduction.
const sidebars: SidebarsConfig = {
  userSidebar: [
    'intro',
    {
      type: 'category',
      label: 'Getting started',
      collapsed: false,
      items: ['installation', 'concepts'],
    },
  ],
};

export default sidebars;
