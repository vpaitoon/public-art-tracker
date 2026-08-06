# Public Art Tracker

Daily scanner for public art commission / call-for-artist opportunities in North Carolina and neighboring states (VA, SC, TN, GA), built for Jen. New opportunities are posted to a Discord channel via webhook.

## How it works

`art_commission_scanner.py` scrapes a handful of public art / call-for-artist listing pages:

- City of Raleigh Arts
- Durham Calls for Artists
- Triangle ArtWorks
- North Carolina Arts Council

It tracks previously-seen listings in `seen_commissions.json` and only posts new ones to Discord.

## Automation

A GitHub Actions workflow (`.github/workflows/daily-scan.yml`) runs the scanner once a day (13:00 UTC) and commits the updated `seen_commissions.json` back to the repo so duplicates aren't re-posted. It can also be triggered manually from the Actions tab ("Run workflow").

## Setup

1. In the repo's **Settings → Secrets and variables → Actions**, add a repository secret named `DISCORD_WEBHOOK_URL` with your Discord channel's incoming webhook URL.
2. That's it — the workflow will run automatically on schedule, or you can trigger it manually.

## Running locally

```bash
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL="your-webhook-url"
python art_commission_scanner.py
```
