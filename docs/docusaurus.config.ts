import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'Styrmin',
  tagline: 'Lifecycle management for your infrastructure automation stack',
  favicon: 'img/favicon.ico',

  future: {
    v4: true,
  },

  url: 'https://styrmin.pages.dev',
  baseUrl: '/',

  onBrokenLinks: 'throw',

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/opsmill/styrmin/tree/develop/docs/',
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
      '@docusaurus/plugin-client-redirects',
      {
        // Old `/docs/how-it-works/*` URLs now live under
        // `/docs/concepts-and-architecture/*`. Generated as client-side
        // redirects so deep links from blog posts, slack, etc. keep working.
        redirects: [
          {from: '/docs/how-it-works', to: '/docs/concepts-and-architecture'},
          {
            from: '/docs/how-it-works/architecture',
            to: '/docs/concepts-and-architecture/architecture',
          },
          {
            from: '/docs/how-it-works/reconciliation',
            to: '/docs/concepts-and-architecture/reconciliation',
          },
          {
            from: '/docs/how-it-works/operator-and-crds',
            to: '/docs/concepts-and-architecture/operator-and-crds',
          },
          {
            from: '/docs/how-it-works/ingress-and-networking',
            to: '/docs/concepts-and-architecture/ingress-and-networking',
          },
          {
            from: '/docs/how-it-works/backups-and-restores',
            to: '/docs/concepts-and-architecture/backups-and-restores',
          },
          {
            from: '/docs/how-it-works/hooks-and-actions',
            to: '/docs/concepts-and-architecture/hooks-and-actions',
          },
          {
            from: '/docs/how-it-works/status-reporting',
            to: '/docs/concepts-and-architecture/status-reporting',
          },
        ],
      },
    ],
  ],

  themes: [
    [
      '@easyops-cn/docusaurus-search-local',
      {
        hashed: true,
        indexBlog: false,
        docsRouteBasePath: '/docs',
        highlightSearchTermsOnTargetPage: true,
      },
    ],
  ],

  themeConfig: {
    image: 'img/docusaurus-social-card.jpg',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Styrmin',
      logo: {
        alt: 'Styrmin Logo',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docs',
          position: 'left',
          label: 'Getting Started',
        },
        {
          to: '/docs/installation',
          label: 'Installation',
          position: 'left',
        },
        {
          to: '/docs/drivers/what-is-a-driver',
          label: 'Drivers',
          position: 'left',
        },
        {
          href: 'https://github.com/opsmill/styrmin',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Documentation',
          items: [
            {
              label: 'Getting Started',
              to: '/docs/getting-started/overview',
            },
            {
              label: 'Installation',
              to: '/docs/installation',
            },
            {
              label: 'Application Drivers',
              to: '/docs/drivers/what-is-a-driver',
            },
          ],
        },
        {
          title: 'Community',
          items: [
            {
              label: 'GitHub',
              href: 'https://github.com/opsmill/styrmin',
            },
            {
              label: 'OpsMill',
              href: 'https://www.opsmill.com',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} OpsMill. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'yaml', 'python', 'json'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
