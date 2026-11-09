# NEXUS landing (static site)

Plain HTML/CSS/JS, no build, no external requests, no tracking. Serve the folder as-is.

```
python3 -m http.server 8000   # then open http://localhost:8000/
```

## Files

| Path | Purpose |
|---|---|
| `index.html` / `en/index.html` | Landing (ES default, EN), `hreflang` + language switch |
| `privacy.html`, `terms.html` (+ `en/`) | DRAFT legal pages, marked "not legal advice" |
| `404.html` | Not-found page (uses absolute `/assets/` paths; configure your host to serve it) |
| `assets/nexus.css`, `assets/nexus.js` | Styles (tokens, auto dark mode, `data-theme`) and theme toggle + waitlist form |
| `favicon.svg`, `og.svg`, `robots.txt`, `sitemap.xml` | Icon, social image, SEO |

## Replace before launch

1. **Domain**: `https://nexus.example` is a placeholder (canonical, hreflang, OG, JSON-LD, `robots.txt`, `sitemap.xml`). Search and replace it. `https://api.nexus.example/v1` in the code samples is also a placeholder for a gateway that does not exist yet.
2. **Waitlist endpoint**: see below. Until set, the form validates but sends nothing and says so.
3. **Legal pages**: fill every `[...]` placeholder with a lawyer; remove the DRAFT banner only after review.
4. **OG image**: many social networks ignore SVG in `og:image`. Export `og.svg` to a 1200x630 PNG, put it at `/og.png` and update the `og:image`/`twitter:image` tags.
5. **Brand**: "NEXUS" is a working name; trademark clearance is `[POR VERIFICAR]`.

## Connecting the waitlist form

The form has `data-endpoint=""` (in both `index.html` files). Set it to a URL that accepts a JSON `POST`:

```html
<form id="waitlist" data-endpoint="https://forms.example-provider.com/f/abc123" ...>
```

Body sent: `{"email": "...", "role": "dev|operator|author|other", "lang": "es|en", "source": "landing"}` with `Content-Type: application/json`. A 2xx response shows the success message; anything else shows the error message.

Options: a form-backend provider that accepts JSON and CORS (check its privacy terms and update `privacy.html`), or your own endpoint (it must return CORS headers for the site origin, validate input, rate-limit, and store consent). Do not put secrets in the page. Update the privacy draft with the real processor before enabling it.

## Honesty rules baked into the copy

No customers, logos, testimonials, usage metrics, benchmarks, prices or operator yields. Numbers come from `research/swarm-sim` and are labelled simulator estimates. Status is stated everywhere: closed alpha, testnet, no token, no real-money settlement. Editing copy: keep "no operator holds the whole model; a large enough coalition could rebuild it; whoever can query it can distill it".
