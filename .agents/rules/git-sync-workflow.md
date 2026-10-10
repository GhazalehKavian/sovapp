# Git Synchronization, Dual Environment & Push Automation Rule

## Repository Context
- **GitHub Repository**: https://github.com/GhazalehKavian/sovapp
- **Production Branch**: `main` (customer-facing, stable, protected)
- **Development/Test Branch**: `develop` (staging, feature development, testing)

## Automated Push Policy
Whenever modifications, new features, bug fixes, or configurations are completed in pair programming:
1. **Never wait for manual push by the user**. The assistant must automatically synchronize and push the changes.
2. **Pre-push Validation**:
   - Run Python syntax checks (`python -m py_compile server.py`).
   - Run automated unit tests (`python -m unittest discover -s tests`).
   - Verify security: Ensure no SQLite databases (`*.db`), secrets, `.env` files, or access tokens are tracked.
3. **Execution**:
   - Run `python scripts/auto_push.py "<descriptive commit message>"` or `scripts/auto_push.ps1`.
4. **Retry & Error Self-Healing**:
   - If `git push` fails (due to remote divergence, lock, network, or branch mismatch):
     - Attempt up to 3 automatic retries with exponential backoff.
     - On non-fast-forward divergence, fetch and rebase automatically (`git pull --rebase origin <branch>`).
     - Catch and parse any error output.
     - If the error requires code or merge resolution, resolve it autonomously and complete the push.

## Environment Separation
- When implementing or testing changes:
  - Work on `develop` branch.
  - Run with `SOVAPP_ENV=test` (port 8080, `tasks_test.db`).
- Only merge and push to `main` when features are fully tested, validated, and ready for client delivery.
- Customer data in `data/tasks.db` must never be touched or altered by test runs.
