import os
import shutil
import time
import stat
from datetime import datetime

# === CONFIGURATION ===
SOURCE_DIR = r"L:\mentor_test\fonctions_sites\05_RNTBCI"
DEST_DIR = r"C:\lcable_local"
SYNC_EXTENSIONS = ('.pdf', '.txt')
LOG_FILE = "sync_errors.log"
CHECK_INTERVAL = 30  # seconds

# === Utility: Wait until file is accessible ===
def wait_until_accessible(path, retries=3, delay=2):
    for _ in range(retries):
        try:
            with open(path, "rb"):
                return True
        except Exception:
            time.sleep(delay)
    return False

# === Copy Logic ===
def copy_file(src_path):
    if not src_path.lower().endswith(SYNC_EXTENSIONS):
        return

    if not os.path.exists(src_path):
        return  # File no longer exists

    if not wait_until_accessible(src_path):
        log_error(src_path, "File not accessible (locked or incomplete).")
        return

    try:
        rel_path = os.path.relpath(src_path, SOURCE_DIR)
        dest_path = os.path.join(DEST_DIR, rel_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        # Copy only if new or modified
        if not os.path.exists(dest_path) or os.path.getmtime(src_path) > os.path.getmtime(dest_path):
            if os.path.exists(dest_path):
                os.chmod(dest_path, stat.S_IWRITE)
            shutil.copy2(src_path, dest_path)
            print(f"✅ Synced: {rel_path}")
        else:
            print(f"⚠️ Skipped (unchanged): {rel_path}")
    except Exception as e:
        log_error(src_path, str(e))

# === Log Errors ===
def log_error(path, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] ❌ {path} - {message}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)
    print(log_entry.strip())

# === Sync Loop ===
def sync_loop():
    print("🔁 Watching for new/changed files every 30 seconds...\n")
    seen = {}

    while True:
        for root, _, files in os.walk(SOURCE_DIR):
            for file in files:
                if not file.lower().endswith(SYNC_EXTENSIONS):
                    continue

                src_path = os.path.join(root, file)

                if not os.path.exists(src_path):
                    continue

                mtime = os.path.getmtime(src_path)
                if src_path not in seen or seen[src_path] != mtime:
                    seen[src_path] = mtime
                    print(f"👀 Checking: {src_path}")
                    copy_file(src_path)

        time.sleep(CHECK_INTERVAL)

# === Entry Point ===
def main():
    print("🚀 Incremental Sync Tool is running...\n")
    sync_loop()

if __name__ == "__main__":
    main()
