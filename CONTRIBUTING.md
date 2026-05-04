# Contributing

Contributions are welcome.

## Good first contributions

- Add reliable RSS sources to `sources.json`
- Improve category scoring in `main.py`
- Add better Turkish prompt formatting
- Add new arXiv queries for robotics, UAVs, computer vision, and edge AI
- Improve README installation steps

## Rules

- Do not commit API keys or tokens.
- Do not add noisy/low-quality news sources without a reason.
- Keep the project usable with GitHub Actions free-style scheduled execution.
- Prefer small, focused pull requests.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Before submitting a PR:

```bash
python -m py_compile main.py
```
