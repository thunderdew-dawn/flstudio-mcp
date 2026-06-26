# fls-pilot v3.0 Landing Page

This package contains a complete English landing page for fls-pilot v3.0 Founder Edition:

- `landing.html`
- `landing.css`
- `landing.js`

## Placement

Put these files into the `site/` directory of the `thunderdew-dawn/fls-pilot` repository so the page can use the existing asset paths:

```text
site/landing.html
site/landing.css
site/landing.js
site/assets/...
```

The HTML also includes remote fallbacks to the `v3/alpha` GitHub raw asset URLs, so it can be previewed outside the repository as long as the browser has internet access.

## Before Launch

Replace the CTA mail link in the pricing section with your real checkout URL:

```html
<a class="button button-primary button-large" href="YOUR_CHECKOUT_URL">Get Founder Edition — 49.99 €</a>
```

Also replace support/legal links and confirm the exact Founder Edition terms before publishing.

## Required Independent Notice

The landing page now states this clearly in the hero area, FAQ and footer:

```text
fls-pilot is an independent local workflow assistant for FL Studio. Not affiliated with or endorsed by Image-Line.
```

Keep this notice visible before launch.
