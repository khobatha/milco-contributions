import os
import shutil

# Directories
src_dir = "outputs/aggregated"   # Source directory containing latest JSON files
dest_dir = "docs/data"           # Destination directory for the website data

# 1. Verify that source directory exists
if not os.path.isdir(src_dir):
    print(f"Source directory not found: {src_dir}")
    exit(1)

# Ensure destination directory exists (create it if it doesn't exist)
if not os.path.isdir(dest_dir):
    os.makedirs(dest_dir, exist_ok=True)

# 2. Filter for JSON files in the source directory (ignore CSV, logs, etc.)
all_files = os.listdir(src_dir)
json_files = [f for f in all_files if f.lower().endswith(".json")]

if not json_files:
    print("No JSON data files found in the source directory. No updates were made.")
    exit(0)

# 3. Copy each JSON file to the destination, overwriting if it exists
for filename in json_files:
    src_path = os.path.join(src_dir, filename)
    dest_path = os.path.join(dest_dir, filename)
    try:
        shutil.copy2(src_path, dest_path)  # copy2 preserves metadata (timestamps, permissions):contentReference[oaicite:0]{index=0}
    except Exception as e:
        print(f"Error copying {filename}: {e}")
        continue

# 4. Print a summary of the files that were updated
print("Updated data files in 'docs/data':")
for filename in json_files:
    print(f" - {filename}")
