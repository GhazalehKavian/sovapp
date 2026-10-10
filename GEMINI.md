# Antigravity Rules for sovapp

## 1. Remote & Branching Guidelines
- Remote: `https://github.com/GhazalehKavian/sovapp`
- Customer/Production environment: `main` branch.
- Test/Development environment: `develop` branch.
- Never commit test data to `main`.
- Always verify tests pass (`python -m unittest discover -s tests`) before promoting to `main`.

## 2. Automated Git Push & Self-Healing Retries
- Whenever code changes or features are added, the agent must automatically commit and push to GitHub using `python scripts/auto_push.py` or `scripts/auto_push.ps1`.
- Do not ask the user to manually run `git push`.
- If an error occurs during push, retry up to 3 times with exponential backoff, handle auto-rebase if remote has new commits, diagnose errors, and fix them automatically.

## 3. Security Guidelines
- SQLite files (`data/*.db`, `*.sqlite`, `*.db`) must NEVER be committed to Git.
- Passwords, OAuth tokens, `.env` files, and credentials must strictly remain local and ignored via `.gitignore`.
- HTTP server must prevent path traversal and enforce secure response headers.

## 4. UI & Aesthetics Integrity
- Preserve the exact look and feel, RTL alignment, Persian terminology, Lucide icons, Jalali calendar, and Tailwind design tokens in `tasks.html`.
- Any environment indicators must be sleek and non-disruptive (e.g. subtle `#envBadge`).
