import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import {themes as prismThemes} from 'prism-react-renderer';

// GitHub Pages serves the production site under /ha-home-keeper/. PR previews are
// deployed under /ha-home-keeper/pr-preview/pr-<n>/, so the deploy workflows set
// DOCS_BASE_URL to keep asset paths correct for each deploy target.
const baseUrl = process.env.DOCS_BASE_URL ?? '/ha-home-keeper/';

const organizationName = 'prestomation';
const projectName = 'ha-home-keeper';
const repoUrl = `https://github.com/${organizationName}/${projectName}`;
const editUrl = `${repoUrl}/tree/main/website/`;

const config: Config = {
  title: 'Home Keeper',
  tagline: 'Track home maintenance and chores in Home Assistant',
  favicon: 'img/favicon.svg',

  url: `https://${organizationName}.github.io`,
  baseUrl,

  organizationName,
  projectName,
  trailingSlash: false,

  onBrokenLinks: 'throw',
  // Anchors are tracked separately from page links and default to 'warn', so a link
  // to a heading that doesn't exist on the target page (e.g. a README same-page
  // anchor whose section moved to its own guide page without being registered in
  // sync-docs.mjs) would slip through. Fail the build on those too.
  onBrokenAnchors: 'throw',

  markdown: {
    // Treat .md as CommonMark (and .mdx as MDX). The generated pages carry
    // literal { } and < > in prose/tables, which MDX would mis-parse as JSX.
    format: 'detect',
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        // User Guide is the default docs instance, served under /docs.
        docs: {
          path: 'docs',
          routeBasePath: 'docs',
          sidebarPath: './sidebars.ts',
          editUrl,
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  plugins: [
    [
      // Developer Guide — a second docs instance served under /developer.
      '@docusaurus/plugin-content-docs',
      {
        id: 'developer',
        path: 'developer',
        routeBasePath: 'developer',
        sidebarPath: './sidebarsDeveloper.ts',
        editUrl,
      },
    ],
  ],

  themeConfig: {
    image: 'img/logo.svg',
    colorMode: {
      defaultMode: 'light',
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Home Keeper',
      logo: {
        alt: 'Home Keeper',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'userSidebar',
          position: 'left',
          label: 'User Guide',
        },
        {
          type: 'docSidebar',
          docsPluginId: 'developer',
          sidebarId: 'developerSidebar',
          position: 'left',
          label: 'Developer Guide',
        },
        {
          to: '/docs/release-notes',
          label: 'Release Notes',
          position: 'left',
        },
        {
          href: repoUrl,
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {label: 'User Guide', to: '/docs/intro'},
            {label: 'Developer Guide', to: '/developer/integrating'},
          ],
        },
        {
          title: 'Community',
          items: [
            {label: 'Home Assistant', href: 'https://www.home-assistant.io/'},
            {label: 'HACS', href: 'https://hacs.xyz/'},
          ],
        },
        {
          title: 'More',
          items: [
            {label: 'GitHub', href: repoUrl},
            {label: 'Issues', href: `${repoUrl}/issues`},
          ],
        },
      ],
      copyright: `Home Keeper — a community Home Assistant integration. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'yaml', 'python', 'json'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
