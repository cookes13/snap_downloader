#!/usr/bin/env python3

import os
import re
import json
import zipfile
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image

# ---------------------------
# CONFIG
# ---------------------------
MEDIA_DIR = "raw_media"
OUTPUT_DIR = "zipped_media"
JSON_INPUT = "memories_history.json"
JSON_OUTPUT = "snap_data.json"
BASE_URL = "http://127.0.0.1:8000"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------
# METADATA TIMESTAMP EXTRACTION
# ---------------------------
def extract_file_timestamp(path):
    """
    Use file modified time (UTC)
    """
    ts = os.path.getmtime(path)
    return datetime.utcfromtimestamp(ts)

def normalize_to_utc(dt):
    try:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except:
        return dt


# ---------------------------
# JSON HANDLING
# ---------------------------
def load_json_index():
    with open(JSON_INPUT, "r", encoding="utf-8") as f:
        data = json.load(f)["Saved Media"]

    index = []
    for entry in data:
        ts = entry.get("Date")
        if not ts:
            continue
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S UTC")
        index.append((dt, entry))

    return index


def match_entry(file_dt, index, tolerance=30):
    best = None
    best_diff = None

    for dt, entry in index:
        diff = abs((dt - file_dt).total_seconds())
        if diff <= tolerance:
            if best is None or diff < best_diff:
                best = entry
                best_diff = diff

    return best


# ---------------------------
# FILE GROUPING
# ---------------------------
def group_files():
    files = list(Path(MEDIA_DIR).glob("*"))
    grouped = {}

    for f in files:
        base = re.sub(r"-(main|overlay).*", "", f.name)
        grouped.setdefault(base, []).append(f)

    return grouped


# ---------------------------
# ZIP CREATION
# ---------------------------
def create_zip(base, files):
    zip_path = Path(OUTPUT_DIR) / f"{base}.zip"

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, arcname=f.name)

    return zip_path


# ---------------------------
# MAIN PROCESS
# ---------------------------
def rebuild():
    index = load_json_index()
    grouped = group_files()

    new_entries = []

    for base, files in grouped.items():

        main_file = None
        overlay_file = None

        for f in files:
            name = f.name.lower()
            if "-main" in name:
                main_file = f
            elif "-overlay" in name:
                overlay_file = f

        if not main_file:
            continue

        # ---------------------------
        # Decide output type
        # ---------------------------
        if overlay_file:
            zip_path = create_zip(base, files)
            served_filename = zip_path.name
            served_path = zip_path
        else:
            # Just copy main file
            clean_name = base + Path(main_file).suffix
            served_filename = clean_name
            served_path = Path(OUTPUT_DIR) / served_filename

            if not served_path.exists():
                shutil.copy(main_file, served_path)

        # ---------------------------
        # Extract timestamp
        # ---------------------------
        file_dt = extract_file_timestamp(main_file)

        if not file_dt:
            print("❌ No metadata timestamp:", main_file.name)
            continue

        file_dt = normalize_to_utc(file_dt)

        # ---------------------------
        # Match JSON entry
        # ---------------------------
        entry = match_entry(file_dt, index)

        if not entry:
            print("❌ No JSON match:", main_file.name, file_dt)
            continue

        # ---------------------------
        # Build new entry
        # ---------------------------
        new_entry = entry.copy()
        new_entry["Media Download Url"] = f"{BASE_URL}/{served_filename}"

        new_entries.append(new_entry)

        #print("✅ Matched:", main_file.name, "->", served_filename)

    # ---------------------------
    # Save JSON
    # ---------------------------
    with open(JSON_OUTPUT, "w", encoding="utf-8") as f:
        json.dump({"Saved Media": new_entries}, f, indent=2)

    print(f"\n🎉 Done. Created {JSON_OUTPUT}")


# ---------------------------
# RUN
# ---------------------------
if __name__ == "__main__":
    rebuild()