import { defineConfig } from 'vite'

// A GitHub Pages project site is served from /<repo>/, which is not known at
// authoring time. The Pages workflow passes the correct prefix in via
// BASE_PATH (from actions/configure-pages, which also covers custom domains
// and user/org sites). The fallback keeps `npm run dev` and local builds
// working without any environment set up.
const raw = process.env.BASE_PATH || '/cpacs-saturn-v/'
const base = raw.endsWith('/') ? raw : `${raw}/`

export default defineConfig({ base })
