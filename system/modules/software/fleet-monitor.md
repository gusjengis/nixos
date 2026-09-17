# Fleet Monitor

Fleet Monitor is enabled on every managed NixOS host. Each machine records a
hardware/workload snapshot every five minutes and exposes its latest snapshot
only through port `9191` on `tailscale0`. Both endpoints ask Tailscale's local
identity API to allow only `gusjengis@gmail.com`, rejecting shared-in tailnet
users. Alpha polls those agents and serves the dashboard at:

```text
http://alpha:9190
```

The dashboard shows reachability and request latency, CPU, memory, network and
disk use, temperatures, SMART data, failed and running systemd units, processes,
tmux sessions/windows, recent high-priority journal messages, and machine roles
declared in `system/hosts/default.nix`. Raw snapshots remain available in each
machine card. Local history is bounded to 25 MB under
`/var/lib/fleet-monitor-agent/health.jsonl`.

## Alerts And AI Summaries

Create a dedicated mailbox with an SMTP-capable provider and an app password.
On alpha, create `/var/lib/fleet-monitor-secrets.env` owned by root and
mode `0600`:

```bash
sudo install -m 0600 /dev/null /var/lib/fleet-monitor-secrets.env
sudoedit /var/lib/fleet-monitor-secrets.env
sudo systemctl restart fleet-monitor-dashboard
```

Example file:

```ini
ALERT_SMTP_HOST=smtp.example.com
ALERT_SMTP_PORT=587
ALERT_SMTP_STARTTLS=true
ALERT_SMTP_USER=agents@example.com
ALERT_SMTP_PASSWORD=provider-app-password
ALERT_SMTP_FROM=agents@example.com
ALERT_EMAIL_TO=your-personal-address@example.com

AI_API_URL=https://api.openai.com/v1/chat/completions
AI_API_KEY=provider-api-key
AI_MODEL=gpt-5-mini
```

SMTP authentication is optional for a trusted local relay. AI configuration is
also optional. When configured, alpha sends only hardware, storage, failed-unit,
uptime, and detected-concern data to the model every six hours. Process lists,
tmux paths, commands, logs, and network details are excluded.

Email alerts trigger for SMART failure, critical temperatures, filesystems over
80%, failed services, Tailscale health warnings, and a host missing two polls.
Identical alerts are rate-limited to one every six hours.

## Operations

```bash
# Deploy collector to each machine through the normal repo update/rebuild flow.
rebuild

# Inspect services.
systemctl status fleet-monitor-agent
systemctl status fleet-monitor-dashboard   # alpha only
journalctl -u fleet-monitor-agent -f
journalctl -u fleet-monitor-dashboard -f

# Check an agent locally. Remote access requires the configured owner identity.
curl http://127.0.0.1:9191/snapshot | jq
```

Machine-specific roles displayed by the dashboard live in the `services` list
for each machine in `system/hosts/default.nix`. Add a systemd unit and readable
label there when assigning a new specialized workload.
