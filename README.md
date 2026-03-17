# GitHub Weekly Growth Repos

A Python CLI tool to find public GitHub repositories with:
- Total stars above a threshold (default: `500`)
- Fast weekly star growth

## Features
- Searches public repositories by star threshold
- Computes `weekly_stars`, `previous_week_stars`, `delta`, and `growth_rate`
- Sorts by `delta`, `weekly_stars`, or `growth_rate`
- Supports direct top-repository ranking by total stars
- Supports filtering and ranking by forks, watchers, and network count
- Outputs as table or JSON
- Includes retry/backoff for transient API errors
- Supports weekly, monthly, or custom-day analysis windows

## Requirements
- Python 3.9+
- GitHub token (read-only is enough for running the scanner)

## Create a GitHub Token (Safe Setup)
1. Go to `https://github.com/settings/tokens`
2. Create a new token
3. Grant minimum required read permissions for public data
4. Store it locally (never commit it to the repository)

## Installation
```bash
git clone https://github.com/<username>/<repo-name>.git
cd <repo-name>
```

Create `.env` from the template:
```bash
cp .env.example .env
# then edit .env and set your real token
```

Or set an environment variable directly:
```bash
export GITHUB_TOKEN="<your_token>"
```

## Quick Start
```bash
python3 github_growth_app.py
```

## Usage Examples
Top 20 repos with stars >= 500, analyzing up to 50 repos:
```bash
python3 github_growth_app.py \
  --min-stars 500 \
  --max-repos 50 \
  --min-weekly-stars 1 \
  --sort-by delta \
  --top 20
```

Export JSON:
```bash
python3 github_growth_app.py --json --top 20 > result.json
```

Top repositories by total stars:
```bash
python3 github_growth_app.py --mode top --min-stars 500 --top 20
```

Top repositories by forks:
```bash
python3 github_growth_app.py --mode top --sort-by forks --min-forks 1000 --top 20
```

Top repositories by watchers:
```bash
python3 github_growth_app.py --mode top --sort-by watchers --min-watchers 200 --top 20
```

Top repositories by network:
```bash
python3 github_growth_app.py --mode top --sort-by network --min-network 1000 --top 20
```

Monthly window (30 days):
```bash
python3 github_growth_app.py --period month --min-weekly-stars 20 --top 20
```

Custom window (for example 14 days):
```bash
python3 github_growth_app.py --window-days 14 --min-weekly-stars 10 --top 20
```

## Arguments
- `--mode`: `growth` (default) or `top` (rank by total stars)
- `--token`: GitHub token (if omitted, read from `GITHUB_TOKEN` or `.env`)
- `--min-stars`: minimum total stars (default: `500`)
- `--min-forks`: minimum fork count (default: `0`)
- `--min-watchers`: minimum watcher count (default: `0`)
- `--min-network`: minimum network count (default: `0`)
- `--max-repos`: maximum repositories to analyze (default: `30`)
- `--min-weekly-stars`: minimum stars in the selected analysis window (default: `20`)
- `--period`: analysis window preset (`week` or `month`, default: `week`)
- `--window-days`: custom window length in days (overrides `--period`)
- `--sort-by`: sorting metric (`delta`, `weekly_stars`, `growth_rate`, `stars`, `forks`, `watchers`, `network`)
- `--top`: number of results to display (default: `15`)
- `--max-star-pages`: max stargazer pages per repo, 100 records/page (default: `20`)
- `--json`: output in JSON format

## Metrics
- `weekly_stars`: stars gained in the last 7 days
- `previous_week_stars`: stars gained in the previous 7-day window
- `delta = weekly_stars - previous_week_stars`
- `growth_rate = weekly_stars / previous_week_stars` (`inf` if denominator is 0)

## Security Notes
- Never paste tokens into source code or README
- Never commit `.env`
- Revoke tokens immediately if you suspect exposure

## Troubleshooting
- `Missing GitHub token`: set `GITHUB_TOKEN` or create `.env`
- `No repositories matched the criteria`: lower `--min-weekly-stars` (for example `0` or `1`)
- Temporary API failures: rerun the command (the script already retries)
