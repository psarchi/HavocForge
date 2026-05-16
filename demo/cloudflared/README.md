# Cloudflare Tunnel — `havoc.archils.dev`

Routes inbound traffic from the internet → through the Cloudflare edge → through
an outbound-only persistent connection → to your local docker container on
`localhost:8080`. No port-forwarding, no firewall changes, free TLS, free DDoS
protection. Costs $0 if you already own a domain on Cloudflare.

## One-time setup

You need: the `cloudflared` daemon installed locally, a Cloudflare account, and
a domain (or subdomain) already on Cloudflare DNS. `archils.dev` is on Cloudflare
already — confirm by checking the domain's nameservers in the Cloudflare
dashboard.

```bash
# 1. install (Linux, x86_64 — see https://github.com/cloudflare/cloudflared/releases for other platforms)
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

# 2. authenticate — opens a browser, picks the zone (archils.dev)
cloudflared tunnel login

# 3. create a named tunnel — generates a UUID + credentials JSON in ~/.cloudflared/
cloudflared tunnel create havocforge-demo

# 4. point the DNS — adds a CNAME record havoc.archils.dev → <UUID>.cfargotunnel.com
cloudflared tunnel route dns havocforge-demo havoc.archils.dev

# 5. config — copy the example, then edit the UUID + credentials path at the top
cp demo/cloudflared/config.yml.example ~/.cloudflared/config.yml
${EDITOR:-nano} ~/.cloudflared/config.yml

# 6. test in foreground — Ctrl-C to stop
cloudflared tunnel --config ~/.cloudflared/config.yml run

# 7. install as a systemd service so it auto-starts on boot
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

After step 7, `havoc.archils.dev` is live. Visiting it routes to whatever is
listening on `localhost:8080` (the demo).

## Day-to-day

- **Demo up:** `scripts/demo-up.sh` (or `docker compose -f docker-compose.demo.yaml up -d`)
- **Tunnel up:** `sudo systemctl start cloudflared` (already enabled = auto on boot)
- **Tunnel down:** `sudo systemctl stop cloudflared` — the URL goes dark, the docker stays up
- **Both down:** `sudo systemctl stop cloudflared && scripts/demo-down.sh`

## Sanity checks

```bash
cloudflared tunnel info havocforge-demo          # connection status
sudo systemctl status cloudflared                # service health
journalctl -u cloudflared -n 50 --no-pager       # recent logs
curl -I https://havoc.archils.dev/healthz        # end-to-end: should return 200
```

## What to put behind it

The demo container exposes `:8080` via docker-compose. The tunnel routes
`havoc.archils.dev` → `localhost:8080`. **Nothing else on your machine is
exposed** — Cloudflare can only reach what you list in `ingress:` in the
config. The catch-all `http_status:404` at the bottom of the rules is the
safety net for anything that doesn't match.

## Optional hardening

Put the demo behind Cloudflare Access if you only want specific people (e.g.
recruiters with a magic link) to reach it:

1. Cloudflare dashboard → Zero Trust → Access → Applications → Add an
   application → Self-hosted
2. Application domain: `havoc.archils.dev`
3. Policy: "Email" → list specific addresses, or "Email domain" → e.g. company
   emails only
4. Save. The page will now require email-link auth before loading.

This adds zero work to the demo itself and lets you pre-share the URL without
worrying about random scraping or abuse.
