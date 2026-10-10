#!/usr/bin/env python3
"""
Automated Git Sync & Push Script with Retry Mechanism for sovapp
Features:
- Pre-push validation (py_compile, security hygiene)
- Automatic commit generation
- Up to 3 retries on push failure with smart rebase/pull
- Detailed error logging and diagnostics
"""

import os
import sys
import subprocess
import time
import shutil

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def find_git_cmd():
    for candidate in ['git', r'C:\Program Files\Git\cmd\git.exe', r'C:\Program Files\Git\bin\git.exe']:
        cmd = shutil.which(candidate) or (candidate if os.path.exists(candidate) else None)
        if cmd:
            return cmd
    return 'git'

GIT = find_git_cmd()

def run_cmd(args, cwd=REPO_DIR):
    cmd = [GIT] + args if isinstance(args, list) else f'"{GIT}" {args}'
    res = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=isinstance(args, str))
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def get_current_branch():
    code, out, _ = run_cmd(['rev-parse', '--abbrev-ref', 'HEAD'])
    return out if code == 0 else 'main'

def security_and_lint_check():
    print('[1/4] Running security & sanity checks...')
    # Check server.py compilation
    server_path = os.path.join(REPO_DIR, 'server.py')
    if os.path.exists(server_path):
        res = subprocess.run([sys.executable, '-m', 'py_compile', server_path], cwd=REPO_DIR)
        if res.returncode != 0:
            print('[-] Syntax error in server.py! Aborting push.')
            return False

    # Check for tracked DB or secret files
    code, out, _ = run_cmd(['ls-files'])
    tracked = out.splitlines()
    for f in tracked:
        lower = f.lower()
        if lower.endswith(('.db', '.sqlite', '.sqlite3')) or lower.startswith(('.env', 'credentials', 'secrets')):
            print(f'[-] Security Alert: Sensitive file is tracked: {f}! Aborting.')
            return False

    print('[+] Security and syntax checks passed.')
    return True

def auto_commit_and_push(commit_msg=None, max_retries=3):
    if not security_and_lint_check():
        return False

    branch = get_current_branch()
    print(f'[2/4] Active branch: {branch}')

    # Check status
    _, status_out, _ = run_cmd(['status', '--porcelain'])
    if status_out:
        print('[3/4] Staging and committing changes...')
        run_cmd(['add', '.'])
        msg = commit_msg or f'Auto-sync [{branch}]: updates and improvements at {time.strftime("%Y-%m-%d %H:%M:%S")}'
        run_cmd(['commit', '-m', msg])
    else:
        print('[3/4] No local modifications to commit.')

    # Push with Retries
    print(f'[4/4] Pushing to remote origin/{branch} (Max {max_retries} attempts)...')
    for attempt in range(1, max_retries + 1):
        print(f'  -> Attempt {attempt}/{max_retries}...')
        code, out, err = run_cmd(['push', 'origin', branch])
        if code == 0:
            print(f'[+] Successfully pushed to GitHub origin/{branch}!')
            return True

        print(f'  [!] Push attempt {attempt} failed:')
        if err:
            print(f'      Stderr: {err}')
        if out:
            print(f'      Stdout: {out}')

        if attempt < max_retries:
            # Check if remote has newer commits (non-fast-forward)
            if 'fetch first' in err or 'non-fast-forward' in err or 'Updates were rejected' in err:
                print('      [*] Remote is ahead. Fetching and rebasing...')
                run_cmd(['fetch', 'origin', branch])
                pull_code, pull_out, pull_err = run_cmd(['pull', '--rebase', 'origin', branch])
                if pull_code != 0:
                    print(f'      [-] Rebase conflict detected: {pull_err}')
            sleep_time = attempt * 2
            print(f'      [*] Waiting {sleep_time} seconds before retry...')
            time.sleep(sleep_time)

    print('[-] All push attempts failed. Please review error messages above.')
    return False

if __name__ == '__main__':
    msg = sys.argv[1] if len(sys.argv) > 1 else None
    success = auto_commit_and_push(msg)
    sys.exit(0 if success else 1)
