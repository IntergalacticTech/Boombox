import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      // React Compiler is not enabled for this kiosk app. These compiler-era
      // rules reject common async data-loading patterns we intentionally use.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/purity': 'off',
      // shared.tsx intentionally exports demo constants and small helpers used
      // by both runtime skins and design-derived components.
      'react-refresh/only-export-components': 'off',
    },
  },
])
