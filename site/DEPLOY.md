# Deploying the SEO Health site to Cloudflare Pages

Static site: `index.html`, `privacy.html`, `terms.html`, `refund.html`, `contact.html`,
`styles.css`, `favicon.svg`.
No build step — these files are the deploy output. Goal: live at `https://seohealth.in`
with `https://seohealth.in/privacy` working (needed for Meta verification + app review).

> Cloudflare Pages custom domains require the domain's DNS to be **on Cloudflare**. So this
> guide moves `seohealth.in`'s nameservers from BigRock to Cloudflare. That's the "better
> long-term DNS" path. ⚠️ The one thing to get right is **preserving your Zoho email records**
> so `hello@seohealth.in` keeps working.

## 0. Before you touch anything — snapshot current DNS
Captured from BigRock on 28 Jun 2026. These **7 records (all Zoho email)** must survive the
move to Cloudflare. A/AAAA are intentionally empty (no website yet — Cloudflare Pages creates
those when you attach the custom domain in step 4). No CNAME records exist.

| Type | Name/Host | Value | Priority |
|---|---|---|---|
| MX | `@` (seohealth.in) | `mx.zoho.in` | 10 |
| MX | `@` | `mx2.zoho.in` | 20 |
| MX | `@` | `mx3.zoho.in` | 50 |
| TXT | `@` | `zoho-verification=zb00509134.zmverify.zoho.in` | — |
| TXT | `@` | `v=spf1 include:zoho.in ~all` | — |
| TXT | `zmail._domainkey` | `v=DKIM1; k=rsa; p=MIGfMA0...` (full value below) | — |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:hello@seohealth.in` | — |

Full DKIM value — `zmail._domainkey.seohealth.in` TXT, copy exactly:

```
v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC29+ciMZdTFT8OWYpzMOuWx400YSmh/eWzvaqsUESvXfvMjLmDS+Zd2NsjoRAp92dUbE9ALjnIoFtUm3/AmZsek5mrZ5mGiBJY0/WGscyEgoOA0s08ouVRLVtd3GeyEyhI9hfKF+bLGsFWRqgFucNl0px7dtEGHcPJ7GFq/dNbJQIDAQAB
```

TTL: BigRock has these at 4h (its minimum). **TTL does not need to be matched** — Cloudflare's
default **Auto** TTL is fine. After adding the zone to Cloudflare (step 2), confirm all 7 records
reappear and values match **character-for-character** before switching nameservers.

## 1. Create the Pages project (direct upload)
1. Sign in at **dash.cloudflare.com** → **Workers & Pages** → **Create** → **Pages** →
   **Upload assets**.
2. Project name: `seohealth`. Drag the entire **`site/`** folder contents in → **Deploy**.
3. You get a live preview at `https://seohealth.pages.dev` — open it and check the landing,
   `/privacy`, and `/terms` all render. (Pages serves `/privacy` from `privacy.html`
   automatically — clean URLs work out of the box.)

## 2. Add seohealth.in to Cloudflare as a zone
1. Cloudflare dashboard → **Add a site** → enter `seohealth.in` → pick the **Free** plan.
2. Cloudflare scans your existing DNS. **Review the imported records carefully** against your
   step-0 snapshot — make sure all three Zoho `MX` records and every `TXT` (SPF/DKIM/
   verification) are present. Add any that didn't import.
3. Cloudflare shows you **two nameservers** (e.g. `xxx.ns.cloudflare.com`). Copy them.

## 3. Point the domain at Cloudflare (at BigRock)
1. In BigRock → domain → **Nameservers** → replace BigRock's with the two Cloudflare ones.
2. Save. Propagation is usually quick but can take a few hours (up to 24h). Cloudflare emails
   you when the zone is **Active**.

## 4. Attach the custom domain to Pages
1. Back in **Workers & Pages → seohealth → Custom domains** → **Set up a custom domain**.
2. Add `seohealth.in` (apex) and also `www.seohealth.in`. Cloudflare auto-creates the records
   and provisions an HTTPS certificate (a few minutes).

## 5. Verify
- `https://seohealth.in` loads the landing page (no more "Server Not Found").
- `https://seohealth.in/privacy`, `/terms`, `/refund`, and `/contact` all load.
  **All four are checked by Razorpay during merchant KYC review** — if any 404s, the
  activation gets queried. `/#pricing` must also show the plans and prices.
- Send a test email to `hello@seohealth.in` and confirm it still arrives in Zoho — proves the
  MX records survived the nameserver change.

## 6. Updating the site later
Re-drag the `site/` folder in **Workers & Pages → seohealth → Create deployment**, or connect
this repo's `site/` folder to Pages for auto-deploys. The content here is intentionally minimal
— expand `index.html` and the styles when the product is ready for a fuller marketing site.

> ⚠️ Editing the repo files is **not** enough — the live site is this separate Cloudflare Pages
> deployment. Any change (copy, styles, legal pages) must be **re-deployed** here to go live.

## 7. Pending before real launch
- ✅ **Policy pages done (2026-08-29)** — `privacy.html` and `terms.html` rewritten for Razorpay
  merchant review + DPDP (payments/Razorpay disclosure, grievance officer, consent basis, honest
  cookie section); `refund.html` and `contact.html` added; `index.html` now carries a real pricing
  section. Not lawyer-reviewed — a ₹1–3k CA/legal pass is still worth doing before public launch.
- ⚠️ **Pricing is duplicated here.** `index.html#pricing` and `terms.html` §3 restate the plan
  limits that `backend/app/services/subscriptions.py` (`TIER_LIMITS`) actually enforces. If those
  limits change, these pages become a live misrepresentation on a page Razorpay reviewed —
  update both sides together.
- Build out a fuller landing page (still a "private beta" brochure).
- **Any change: re-deploy to Cloudflare Pages** (see section 6) — repo edits don't ship
  themselves. Consider wiring git-connected auto-deploy so future edits publish automatically.

## What this unblocks
- **Meta Business Verification (Phase 4)** — `seohealth.in` now resolves and shows a real
  registered business.
- **Meta App Review (Phase 6)** — Privacy Policy URL = `https://seohealth.in/privacy`.
