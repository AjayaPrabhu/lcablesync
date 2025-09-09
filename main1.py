import os
import shutil
import time

# ==== CONFIG ====
REMOTE_PATH = r"L:\mentor_test\fonctions_sites\05_RNTBCI"
LOCAL_PATH = r"C:\LCableserver"
SYNC_LOG = os.path.join(LOCAL_PATH, "sync_log.csv")     # log of synced files
AUDIT_LOG = os.path.join(LOCAL_PATH, "audit_log.csv")   # full audit (all files scanned)
SYNC_INTERVAL = 30   # check every 30 seconds
# ===============

def ensure_local_dir(local_path):
    if not os.path.exists(local_path):
        os.makedirs(local_path)

def log_sync(remote_file, remote_mtime):
    """Log only the files that were actually synced"""
    sync_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    orig_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(remote_mtime))
    with open(SYNC_LOG, "a", encoding="utf-8") as f:
        f.write(f"{remote_file},{orig_time},{sync_time}\n")

def log_audit(remote_file, status):
    """Log every scanned file with its sync status"""
    scan_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(f"{remote_file},{status},{scan_time}\n")

def safe_path(path):
    """Enable long path support for Windows"""
    if os.name == "nt":
        path = os.path.abspath(path)
        if not path.startswith("\\\\?\\"):
            path = "\\\\?\\" + path
    return path

def sync_once():
    ensure_local_dir(LOCAL_PATH)

    # Init logs if missing
    if not os.path.exists(SYNC_LOG):
        with open(SYNC_LOG, "w", encoding="utf-8") as f:
            f.write("Remote Path,Original Modified Date,Sync Time\n")
    if not os.path.exists(AUDIT_LOG):
        with open(AUDIT_LOG, "w", encoding="utf-8") as f:
            f.write("Remote Path,Status,Scan Time\n")

    for root, _, files in os.walk(REMOTE_PATH):
        root_safe = safe_path(root)
        for file in files:
            name = file.strip().lower()
            if name.endswith(".pdf") or name.endswith(".txt"):
                remote_file_normal = os.path.join(root, file)
                remote_file_safe = os.path.join(root_safe, file)
                relative_path = os.path.relpath(remote_file_normal, REMOTE_PATH)
                local_file_normal = os.path.join(LOCAL_PATH, relative_path)
                local_file_safe = safe_path(local_file_normal)

                ensure_local_dir(os.path.dirname(local_file_normal))

                try:
                    remote_mtime = os.path.getmtime(remote_file_safe)
                except FileNotFoundError:
                    log_audit(remote_file_normal, "Missing on remote")
                    continue

                if not os.path.exists(local_file_safe):
                    print(f"New file -> {remote_file_normal}")
                    shutil.copy2(remote_file_safe, local_file_safe)
                    log_sync(remote_file_normal, remote_mtime)
                    log_audit(remote_file_normal, "Synced (new)")
                elif os.path.getmtime(local_file_safe) != remote_mtime:
                    print(f"Updated file -> {remote_file_normal}")
                    shutil.copy2(remote_file_safe, local_file_safe)
                    log_sync(remote_file_normal, remote_mtime)
                    log_audit(remote_file_normal, "Synced (updated)")
                else:
                    log_audit(remote_file_normal, "Already up-to-date")

def auto_sync():
    print("Starting auto-sync service with audit logging...")
    while True:
        sync_once()
        print(f"Waiting {SYNC_INTERVAL} seconds before next scan...")
        time.sleep(SYNC_INTERVAL)

if __name__ == "__main__":
    auto_sync()
