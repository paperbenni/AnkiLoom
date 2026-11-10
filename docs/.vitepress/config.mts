import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'AnkiLoom',
  description: 'Markdown flashcards to Anki. Keep your format, keep your review history.',
  base: '/AnkiLoom/',
  lastUpdated: true,
  srcExclude: ['public/**'],
  sitemap: { hostname: 'https://paperbenni.xyz/AnkiLoom/' },
  themeConfig: {
    nav: [
      { text: 'Guide', link: '/guide/getting-started' },
      { text: 'CLI reference', link: '/reference/cli' },
      { text: 'Releases', link: 'https://github.com/paperbenni/AnkiLoom/releases' }
    ],
    sidebar: [
      {
        text: 'Start here',
        items: [
          { text: 'Getting started', link: '/guide/getting-started' },
          { text: 'Migrate from Yanki', link: '/guide/migration' },
          { text: 'Card format', link: '/guide/card-format' }
        ]
      },
      {
        text: 'Using AnkiLoom',
        items: [
          { text: 'Sync and recovery', link: '/guide/sync' },
          { text: 'Watch a folder', link: '/guide/watch' },
          { text: 'Configuration', link: '/guide/configuration' },
          { text: 'CLI and agents', link: '/guide/agents' }
        ]
      },
      {
        text: 'Reference',
        items: [
          { text: 'CLI commands', link: '/reference/cli' },
          { text: 'Agent skill', link: '/reference/skill' },
          { text: 'Development', link: '/guide/development' }
        ]
      }
    ],
    search: { provider: 'local' },
    outline: { level: [2, 3] },
    socialLinks: [{ icon: 'github', link: 'https://github.com/paperbenni/AnkiLoom' }],
    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2026 paperbenni'
    }
  }
})
