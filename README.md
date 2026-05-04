# AI Intel Telegram Bot

A public, template-ready GitHub Actions project that sends a Turkish AI intelligence bulletin to Telegram.

Focus areas:

- AI and LLM developments
- Defense AI / military AI
- UAV, drone autonomy, counter-UAS
- Robotics, humanoids, embodied AI
- Computer vision, YOLO, object tracking
- Edge AI, Jetson, Hailo, on-device inference
- arXiv research signals
- Turkey-focused defense technology monitoring

The repository is safe to publish publicly because credentials are not stored in source code. Each user runs the bot with their own GitHub Actions secrets.

---

## What it does

```text
GitHub Actions schedule
      ↓
Collect RSS + Google News RSS + arXiv items
      ↓
Deduplicate and score by relevance
      ↓
Generate a Turkish bulletin with Gemini
      ↓
Send the bulletin to Telegram
```

Included workflows:

| Workflow | Time | Purpose |
|---|---:|---|
| Daily AI Defense Robotics Intel Bulletin | 09:00 Turkey time | Daily news bulletin |
| Weekly AI Defense Robotics Trend Report | Sunday 17:00 Turkey time | Weekly trend analysis |

---

## Repository structure

```text
main.py
sources.json
requirements.txt
.env.example
.gitignore
LICENSE
SECURITY.md
CONTRIBUTING.md
CHANGELOG.md
.github/workflows/daily-ai-intel.yml
.github/workflows/weekly-ai-intel.yml
.github/ISSUE_TEMPLATE/bug_report.md
.github/ISSUE_TEMPLATE/feature_request.md
.github/dependabot.yml
```

---

## Use as a public template

If you are the maintainer and want others to reuse this project:

1. Create a public GitHub repository.
2. Upload all files in this project.
3. Go to `Settings → General`.
4. Enable `Template repository`.
5. Users can then click `Use this template` and create their own copy.

Users must add their own credentials to their own repository secrets. Secrets are not shared through templates or forks.

---

## Required credentials

Create these three values before running the workflow:

### 1. Gemini API key

Add it as:

```text
GEMINI_API_KEY
```

### 2. Telegram bot token

Create a Telegram bot with `@BotFather`, then add the token as:

```text
TELEGRAM_BOT_TOKEN
```

### 3. Telegram chat ID

Send a message to your bot, then open:

```text
https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
```

Find the `chat.id` value and add it as:

```text
TELEGRAM_CHAT_ID
```

---

## Add GitHub Actions secrets

In your repository:

```text
Settings → Secrets and variables → Actions → New repository secret
```

Add:

```text
GEMINI_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Do not put real credentials into `.env`, README, workflow YAML files, screenshots, logs, or issue comments.

---

## Optional GitHub variables

In:

```text
Settings → Secrets and variables → Actions → Variables
```

You may add:

```text
GEMINI_MODEL=gemini-2.5-flash
MAX_AGE_HOURS=48
MAX_CANDIDATES=45
BULLETIN_ITEMS=8
```

Recommended values:

| Variable | Suggested | Meaning |
|---|---:|---|
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model name |
| `MAX_AGE_HOURS` | `48` | How far back daily bulletin searches |
| `MAX_CANDIDATES` | `45` | Number of candidate items sent to Gemini |
| `BULLETIN_ITEMS` | `8` | Number of highlighted items in the bulletin |

---

## Run manually

Go to:

```text
Actions → Daily AI Defense Robotics Intel Bulletin → Run workflow
```

or:

```text
Actions → Weekly AI Defense Robotics Trend Report → Run workflow
```

If the workflow succeeds, you should receive a Telegram message.

---

## Scheduled runs

Daily bulletin:

```yaml
- cron: "0 6 * * *"
```

This corresponds to 09:00 Turkey time.

Weekly report:

```yaml
- cron: "0 14 * * 0"
```

This corresponds to Sunday 17:00 Turkey time.

---

## Source configuration

All monitored sources are managed in `sources.json`.

Add an RSS source:

```json
{
  "name": "New Robotics Source",
  "url": "https://example.com/feed.xml",
  "category": "robotics",
  "trust_score": 7
}
```

Add a Google News RSS query:

```json
{
  "query": "autonomous drone AI OR UAV computer vision",
  "category": "uav_ai",
  "language": "en",
  "region": "US",
  "trust_score": 6
}
```

Add an arXiv query:

```json
{
  "query": "all:\"multi-agent UAV\" OR all:\"swarm robotics\"",
  "category": "research_swarm",
  "trust_score": 8
}
```

Supported categories:

```text
general_ai
defense_ai
counter_uas
uav_ai
robotics
edge_ai
turkey_defense
research_swarm
research_uav
research_cv
research_robotics
research_edge_ai
```

---

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally:

```env
GEMINI_API_KEY=your_key
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

Run:

```bash
python main.py
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python main.py
```

---

## Security notice

This project can be public, but your credentials must remain private.

Never commit:

```text
.env
Gemini API keys
Telegram bot tokens
Telegram chat IDs
workflow logs containing secrets
```

The included `.gitignore` blocks `.env` files by default.

If a token is leaked:

1. Delete the exposed value from GitHub immediately.
2. Revoke/regenerate the token from the provider.
3. Replace the GitHub Actions secret.
4. Review recent Actions logs.

---

## License

MIT License.
