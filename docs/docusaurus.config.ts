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

  url: 'https://docs.styrmin.app',
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
          // The alpha status page was replaced by the beta status page.
          {from: '/docs/alpha-status', to: '/docs/beta-status'},
          {from: '/docs/how-it-works', to: '/docs/concepts-and-architecture'},
          // `/docs/getting-started/*` was dissolved per audit: Why Styrmin?
          // and Platform Overview moved under Introduction, Quickstart moved
          // under Installation.
          {
            from: '/docs/getting-started/why-styrmin',
            to: '/docs/introduction/why-styrmin',
          },
          {
            from: '/docs/getting-started/overview',
            to: '/docs/introduction/platform-overview',
          },
          {
            from: '/docs/getting-started/quickstart',
            to: '/docs/installation/quickstart',
          },
          // What is an Application Driver? moved from Drivers to
          // Concepts and Architecture — it's a conceptual page that was
          // mixed in with task-oriented driver guides.
          {
            from: '/docs/drivers/what-is-a-driver',
            to: '/docs/concepts-and-architecture/what-is-a-driver',
          },
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
    image: 'img/styrmin-social-card.png',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    announcementBar: {
      id: 'beta-status-v1',
      content:
        'Styrmin is in <strong>beta</strong>. Read what changed since the alpha and ' +
        'what to do before you upgrade: <a href="/docs/beta-status">Beta status</a>',
      backgroundColor: '#fef3c7',
      textColor: '#78350f',
      isCloseable: true,
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
          label: 'Introduction',
        },
        {
          to: '/docs/installation',
          label: 'Installation',
          position: 'left',
        },
        {
          to: '/docs/drivers/loading-drivers',
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
              label: 'Introduction',
              to: '/docs/introduction/why-styrmin',
            },
            {
              label: 'Installation',
              to: '/docs/installation',
            },
            {
              label: 'Application drivers',
              to: '/docs/drivers/loading-drivers',
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
