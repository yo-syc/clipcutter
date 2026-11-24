# Deploy the ClipCutter website

One server runs everything: **Caddy** (free HTTPS), the **website**, and one or more **workers**.
Design and costs: [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md).

| option | cost | notes |
|---|---|---|
| **Oracle Cloud Always Free** (Ampere A1: 4 ARM cores, 24 GB RAM) | **₹0** | needs a card for verification. Free-tier ARM capacity is sometimes "out of stock", so retry or pick another region |
| **Hetzner** CAX21 (4 ARM cores, 8 GB) | ~€7/month (~₹650) | simplest, includes 20 TB traffic |
| any Ubuntu VPS with 2+ cores, 4 GB RAM | varies | same steps |

You also need a **domain** (~₹100–900/year), or a free subdomain from [DuckDNS](https://www.duckdns.org).

---

## 1. Create the server

- **Oracle:** Console → Compute → Instances → Create → Image: *Ubuntu 22.04/24.04*, Shape: *VM.Standard.A1.Flex* (4 OCPU, 24 GB) →
  add your SSH key → Create. Then *Networking → your VCN → Security List → Add ingress rules* for TCP **80** and **443**.
- **Hetzner:** Cloud Console → Add Server → Ubuntu 24.04 → CAX21 → add your SSH key → Create.

## 2. Point your domain at it

At your domain provider, add an **A record**: `clips.yourdomain.com → <server IP>`.

## 3. Install and start (on the server)

```bash
ssh ubuntu@<server-ip>              # Hetzner: root@<server-ip>
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
# Oracle's Ubuntu image also blocks ports in its own firewall:
sudo iptables -I INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT && sudo netfilter-persistent save || true

git clone https://github.com/pandeymynk/clipcutter.git && cd clipcutter
echo "DOMAIN=clips.yourdomain.com" > .env
# optional, for AI-written hooks (else built-in Gen Z hooks are used):
# echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
docker compose up -d --build
```

Open `https://clips.yourdomain.com`. Caddy gets the HTTPS certificate automatically within a minute.

## 4. Day-to-day

```bash
docker compose logs -f worker                       # watch jobs
docker compose up -d --scale worker=3               # more parallel clips (each worker ≈ 1 CPU core)
docker compose exec web clipcutter site-plan you@x.com creator --days 30   # give a plan (until payments go live)
git pull && docker compose up -d --build            # update
```

Back up `./data/clipcutter.db` (users and plans). Videos and clips in `./data` are temporary and clean themselves up.

## 5. Scaling later (no code changes)

- More users: add workers (`--scale worker=N`) or more servers running only `worker` against shared storage.
- Database: SQLite is fine for thousands of users. The plan is to move to Postgres (Supabase/Neon free) when you run several servers.
- Storage: move `./data/clips` to Cloudflare R2 (free downloads) when traffic grows.

## If YouTube blocks the server

If the logs show "Sign in to confirm you're not a bot", YouTube is blocking the server's IP. Options, in order:
wait and retry, rely on the shared cache, move to another region or provider, or use a proxy for paid plans only.
See SYSTEM_DESIGN.md §5.
