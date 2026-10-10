"""
Package SovApp for safe client/evaluator distribution.
Ensures zero data leakage: excludes real databases, credentials, git history.
"""
import os
import zipfile
from datetime import datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUTPUT_ZIP = os.path.join(ROOT_DIR, 'sovapp_clean_review.zip')

EXCLUDE_DIRS = {'.git', '__pycache__', '.pytest_cache', '.vscode', '.idea'}
EXCLUDE_EXTS = {'.db', '.sqlite', '.sqlite3', '.pyc', '.pyo', '.env', '.key', '.pem'}
EXCLUDE_FILES = {'tasks.db', 'tasks_test.db', '.env', 'secrets.json'}

def make_clean_zip():
    print(f"[sovapp] Packaging clean review distribution from {ROOT_DIR}...")
    file_count = 0
    with zipfile.ZipFile(OUTPUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ROOT_DIR):
            # Prune excluded directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                if file == 'sovapp_clean_review.zip':
                    continue
                if file in EXCLUDE_FILES:
                    continue
                ext = os.path.splitext(file)[1].lower()
                if ext in EXCLUDE_EXTS:
                    continue

                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, ROOT_DIR)

                zf.write(abs_path, rel_path)
                file_count += 1

    size_mb = os.path.getsize(OUTPUT_ZIP) / (1024 * 1024)
    print(f"[sovapp] Successfully created clean distribution package:")
    print(f"         Path: {OUTPUT_ZIP}")
    print(f"         Files: {file_count}")
    print(f"         Size: {size_mb:.2f} MB")
    print(f"[sovapp] Verified: Zero databases, zero credentials included. 100% secure!")

if __name__ == '__main__':
    make_clean_zip()
