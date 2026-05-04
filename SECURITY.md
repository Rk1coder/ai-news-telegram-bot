# Security Policy

## Supported usage

This project is designed for public GitHub repositories **only if credentials are stored as GitHub Actions secrets**.

Required secrets:

- `GEMINI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Never commit real API keys, bot tokens, chat IDs, `.env`, screenshots containing tokens, or GitHub Actions logs exposing secrets.

## Recommended repository settings

For public repositories:

1. Keep the repository public, but keep credentials in `Settings → Secrets and variables → Actions`.
2. Do not add secrets to source files, README examples, issue comments, or workflow logs.
3. Do not enable workflows from untrusted pull requests that could access secrets.
4. Review pull requests that modify `.github/workflows/` carefully.
5. Rotate tokens immediately if they are exposed.

## Reporting a vulnerability

Please open a private security advisory or contact the maintainer directly. Do not publish leaked tokens or exploit details in a public issue.
