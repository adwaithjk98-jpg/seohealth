# Deploying SEO Health to a VPS

A step-by-step guide for a first real deploy. It assumes **zero prior Docker
knowledge** — every command is copy-paste. The app ships as pre-built images, so
the server only ever *pulls and runs*; it never builds (which can run a small
box out of memory).

**How it fits together:** CI (GitHub Actions) builds the `backend` + `frontend`
images and pushes them to GHCR → the VPS pulls them → `deploy.sh` starts the 7
containers (postgres, redis, api, worker, competitor-worker, scheduler,
frontend) behind Caddy, which handles HTTPS.

---

## 0. One-time, before you touch the server

1. **Buy the VPS** — Ubuntu 24.04 LTS, **2 vCPU / 8 GB RAM**, NVMe, India region
   (Mumbai/Bangalore/Delhi). 8 GB (not 4) buys headroom; we still don't build on it.
2. **DNS** — add an **A record** for the app pointing at the VPS IP. Recommended:
   put the app on **`app.seohealth.in`** and leave `seohealth.in` (landing +
   policies on Cloudflare Pages) as-is.
   - If the domain is on **Cloudflare**, set the app record to **DNS only (grey
     cloud)**, not proxied — otherwise Cloudflare's proxy fights Caddy's TLS.
3. **Push your code + trigger a build.** From your Mac:
   ```bash
   git push origin frontend-redesign      # (or merge to main first)
   ```
   Then watch **GitHub → Actions → "Build & push images"** go green. That
   publishes `ghcr.io/adwaithjk98-jpg/seohealth-backend` +
   `…-frontend`. (First run also *creates* the GHCR packages — they're private.)

---

## 1. Prepare the box (once per server)

SSH in as root, then:

```bash
# --- a non-root user with sudo (don't run the app as root) ---
adduser deploy && usermod -aG sudo deploy
# copy your SSH key to the new user, then log back in as `deploy`.

# --- firewall: only SSH + web ---
sudo ufw allow 22 && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
sudo apt update && sudo apt install -y fail2ban

# --- Docker (official convenience script) ---
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy        # run docker without sudo (re-login after)
```

Log out and back in so the `docker` group applies.

---

## 2. Log in to GHCR (once per server)

The images are **private**, so the box needs read access. On GitHub create a
**classic Personal Access Token** with just the **`read:packages`** scope, then:

```bash
echo 'YOUR_TOKEN' | docker login ghcr.io -u adwaithjk98-jpg --password-stdin
```

---

## 3. Get the code + secrets

```bash
git clone https://github.com/adwaithjk98-jpg/seohealth.git
cd seohealth

cp .env.prod.example .env.prod
nano .env.prod          # fill in the blanks (below), then save
chmod 600 .env.prod     # secrets — lock the file down
```

**What to fill in `.env.prod`:**
- `POSTGRES_PASSWORD` — generate one: `openssl rand -base64 24`
- `FRONTEND_BASE_URL` — `https://app.seohealth.in`
- `PLACES_API_KEY`, `IG_GRAPH_ACCESS_TOKEN`, `META_APP_SECRET`, `PAGESPEED_API_KEY`
  — from `credentials.md`
- `RESEND_API_KEY` / `FROM_EMAIL` — once Resend is set up (empty is allowed; mail
  just won't send until then)
- `VAPID_*` — generate on the box:
  `docker run --rm ghcr.io/adwaithjk98-jpg/seohealth-backend:latest python scripts/gen_vapid_keys.py`
- Leave all `RAZORPAY_*` empty → checkout stays in mock mode (correct for beta).

Also set the domain in the **Caddyfile** if you used a subdomain: change
`seohealth.in {` to `app.seohealth.in {`.

---

## 4. Deploy

```bash
./deploy.sh
```

That pulls the images and starts everything. First boot: the API runs DB
migrations, and **Caddy takes ~30s to obtain the Let's Encrypt certificate**
(needs step 0's DNS live + ports 80/443 open).

---

## 5. First-boot verification (do not skip)

```bash
curl -s https://app.seohealth.in/api/health        # status:ok, database:connected, scheduler heartbeat
docker compose ... ps                               # all 7 services "running" (deploy.sh prints the full cmd)
```

Then, logged into the app:
1. Run **one real audit** end-to-end (watch the live SSE progress stream).
2. Run **one discovery scan**.
3. **Check the Google Cloud SKU report** — Text Search ≈ pages fetched, and
   **zero** Place Details attributable to discovery. **This is the hard launch
   gate** (the Places cost guardrail). Set the **$10/day billing cap** + restrict
   the Places key to the **server IP** while you're in the console.

---

## 6. Backups + snapshots (turn on now, not later)

```bash
# nightly Postgres dump inside the container's network:
crontab -e
# add:
30 2 * * * cd /home/deploy/seohealth && DATABASE_URL="postgresql://audithealth:$(grep POSTGRES_PASSWORD .env.prod|cut -d= -f2-)@localhost:5432/audithealth" BACKUP_DIR=/home/deploy/backups backend/scripts/backup_db.sh >> /home/deploy/backup.log 2>&1
```
(Postgres isn't published to the host by default — either run the dump *inside*
the compose network, or temporarily expose 5432 to localhost. See
`backend/scripts/backup_db.sh` for the restore drill.)

Also enable **provider snapshots** in the VPS dashboard — that's your whole-box
safety net on top of the DB dumps.

---

## 7. Updating later (redeploy)

```bash
git pull
# (a new push already rebuilt images in CI)
./deploy.sh          # pulls the new `latest` and restarts changed services
```

**Rollback** to a known-good build: find its tag in GHCR (e.g. `sha-abc1234`) and
```bash
IMAGE_TAG=sha-abc1234 ./deploy.sh
```

---

## Troubleshooting

`project_notes.md` has the full incident runbook (audits stuck, Redis down, cron
dead, SSE, etc.). Quick hits:
- **Something's wrong:** `curl -s https://app.seohealth.in/api/health` → shows DB,
  queue depth, and scheduler `stale` in one shot.
- **Caddy won't get a cert:** DNS not pointing at the box yet, port 80/443 blocked,
  or Cloudflare proxying (must be grey-cloud). Check `docker compose ... logs caddy`.
- **A container keeps restarting:** `docker compose ... logs <service>`.
- **Never run `docker compose ... up --build` in prod** — the box pulls images; it
  must not build them.
