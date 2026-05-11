# Boombox website

This folder contains the static GitHub Pages site for Boombox. It has no build
step: GitHub Pages publishes the contents of `site/` directly through
`.github/workflows/pages.yml`.

## Local preview

```bash
python3 -m http.server 8000 --directory site
```

Then open <http://localhost:8000>.

## Publishing

The workflow runs on pushes to `main` that touch `site/**` or the Pages workflow.
If Pages has not been enabled for the repository yet, set the repository's Pages
source to **GitHub Actions** in GitHub settings.
