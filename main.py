#!/usr/bin/env python3
"""
Process Snapchat-style JSON:
- Download "Media Download Url"
- If file is a ZIP, extract and merge *-main.* with *-overlay.png
- Use ffmpeg (in PATH) to overlay the PNG onto the image/video (overlay at 0:0)
- Embed GPS EXIF into resulting JPGs (if Location contains lat,lon)
"""
# Check for required imports
try:
    import json
    import os
    import re
    import zipfile
    import shutil
    import subprocess
    import sys
    from pathlib import Path
    from PIL import Image
    from datetime import datetime
    import wget
    import piexif
except ImportError as e:
    import_errors.append(str(e))
    print("Import Error, Missing modules. Please run 'pip install -r requirements.txt'")
    exit(1)

print("All required modules imported.")

# Set ffmpeg binary location
global ffmpeg_path
ffmpeg_path = "bin/ffmpeg.exe"

# Check ffmpeg availability
try:
    subprocess.run([ffmpeg_path, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print("ffmpeg is accessable, continuing...")
except FileNotFoundError:
    print(f"ffmpeg is not accesable from the specified path. ffmpeg is required, please ensure ffmpeg.exe is located in '{ffmpeg_path}' or modify the path in the script.")
    exit(1)
except Exception as e:
    print("Error checking ffmpeg:", e)
    print("ffmpeg is required, please ensure ffmpeg.exe is located in 'bin/ffmpeg.exe' or modify the path in the script.")


def parse_latlon(location_str):
    """Return (lat, lon) floats or (None, None)."""
    if not location_str:
        return None, None
    m = re.search(r"(-?\d+\.\d+),\s*(-?\d+\.\d+)", location_str)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None

def deg_to_dms_rational(deg_float):
    deg = int(abs(deg_float))
    minutes_f = (abs(deg_float) - deg) * 60
    minutes = int(minutes_f)
    seconds = int(round((minutes_f - minutes) * 60 * 100))
    return ((deg, 1), (minutes, 1), (seconds, 100))



def embed_gps_jpg(jpg_path, lat, lon, timestamp=None):
    """
    Embed GPS tags and optional timestamp into a JPG using piexif.
    """
    if lat is None or lon is None:
        return

    # --- Conversion for timestamp ---
    if isinstance(timestamp, str):
        from datetime import datetime
        timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S %Z")
    # --------------------------------

    try:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}}

        # GPS
        lat_ref = "N" if lat >= 0 else "S"
        lon_ref = "E" if lon >= 0 else "W"
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = deg_to_dms_rational(lat)
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = deg_to_dms_rational(lon)

        # Timestamp
        if timestamp is not None:
            formatted_time = timestamp.strftime("%Y:%m:%d %H:%M:%S")
            exif_dict["0th"][piexif.ImageIFD.DateTime] = formatted_time
            exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = formatted_time
            exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = formatted_time

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, jpg_path)

        print(f"Embedded GPS into {jpg_path}: {lat},{lon}, timestamp={timestamp}")

    except Exception as e:
        print("Warning: could not embed EXIF GPS:", e)



def embed_gps_mp4(mp4_path, lat, lon, timestamp=None):
    """
    Embed GPS metadata and optional creation time into an MP4 using ffmpeg.
    """
    if lat is None or lon is None:
        return

    # --- Conversion for timestamp ---
    if isinstance(timestamp, str):
        from datetime import datetime
        timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S %Z")
    # --------------------------------

    try:
        # ISO 6709 format for GPS
        location = f"{lat:+.6f}{lon:+.6f}/"
        temp_path = mp4_path + ".tmp.mp4"

        cmd = [
            f"{ffmpeg_path}", "-y",
            "-i", mp4_path,
            "-metadata", f"location={location}",
            "-codec", "copy"
        ]

        # Add creation_time metadata
        if timestamp is not None:
            creation_time = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
            cmd.extend(["-metadata", f"creation_time={creation_time}"])

        cmd.append(temp_path)

        print(f"Embedding GPS into {mp4_path}: {lat},{lon}, creation_time={timestamp}")
        safe_run(cmd)

        import os
        os.replace(temp_path, mp4_path)

    except Exception as e:
        print("Warning: could not embed GPS metadata into MP4:", e)



def safe_run(cmd, check=True):
    """Run a subprocess command (list form) and stream errors."""
    print("RUN:", " ".join(map(str, cmd)))
    try:
        subprocess.run(cmd, check=check)
    except subprocess.CalledProcessError as e:
        print("Command failed:", e)
        if check:
            raise

# ---------------------------
# ZIP extraction & merging using ffmpeg
# ---------------------------
def extract_zip(zip_path, extract_dir):
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(extract_dir)
    print("Extracted to", extract_dir)

def find_main_and_overlay(dirpath):
    """Search dirpath for *-main.jpg / *-main.mp4 and *-overlay.png"""
    main = None
    overlay = None
    p = Path(dirpath)
    for f in p.iterdir():
        name = f.name.lower()
        if name.endswith("-main.jpg") or name.endswith("-main.jpeg") or name.endswith("-main.png") or name.endswith("-main.webp") or name.endswith("-main.webp"):
            main = str(f)
        elif name.endswith("-main.mp4") or name.endswith("-main.mov") or name.endswith("-main.mkv") or name.endswith("-main.webm"):
            main = str(f)
        elif name.endswith("-overlay.png"):
            overlay = str(f)
    return main, overlay

def overlay_image(main_path, overlay_path, out_path):
    base = Image.open(main_path).convert("RGBA")
    overlay = Image.open(overlay_path).convert("RGBA").resize(base.size)

    result = Image.alpha_composite(base, overlay)
    result.convert("RGB").save(out_path, quality=95)

def ffmpeg_overlay_video(main_vid, overlay_png, out_vid):
    """
    Overlay an image on a video with possibly different size (same aspect ratio).
    Preserves audio. Re-encodes video with libx264.
    """
    
    AllowedAttemps = 3
    x = 0
    while x < AllowedAttemps:
        cmd = [
            f"{ffmpeg_path}", "-y",
            "-i", main_vid,
            "-i", overlay_png,
            "-filter_complex",
            "[1:v][0:v]scale2ref=w=iw:h=ih[ovr][base];"  # scale overlay to match video
            "[base][ovr]overlay=0:0",
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "veryfast",
            "-c:a", "copy",
            out_vid
        ]
        try:
            safe_run(cmd)
            break
        except Exception as e:
            print("Error during ffmpeg overlay:", e)
            print("Attemtping to fix currupted overlay image...")
            overlay_png = FixOverlayImage(overlay_png)
            print("Retrying ffmpeg overlay...")

def FixOverlayImage(overlay_path):
    fixed_overlay_path = overlay_path.replace(".png", "_fixed.png")

    img = Image.open(overlay_path).convert("RGBA")  # ensures alpha channel is preserved
    img.save(fixed_overlay_path)
    print("Saved fixed overlay:", fixed_overlay_path)
    return fixed_overlay_path


def process_zip_file(zip_path, out_dir):
    """Extract and produce merged file path (jpg or mp4). Returns output path or None."""
    extract_dir = str(Path(out_dir) / (Path(zip_path).stem + "_extracted"))
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir, exist_ok=True)

    extract_zip(zip_path, extract_dir)
    main, overlay = find_main_and_overlay(extract_dir)

    #delete zip file after extraction
    os.remove(zip_path)

    if not main or not overlay:
        print("ERROR: couldn't find main or overlay inside zip:", zip_path)
        return None

    main_ext = Path(main).suffix.lower()
    base_out = str(Path(out_dir) / (Path(zip_path).stem + "_merged"))
    if main_ext in [".jpg", ".jpeg", ".png", ".webp"]:
        out_img = base_out + ".jpg"
        overlay_image(main, overlay, out_img)
        shutil.rmtree(extract_dir)# clean up extracted files
        return out_img
    else:
        # assume video
        out_vid = base_out + ".mp4"
        ffmpeg_overlay_video(main, overlay, out_vid)
        shutil.rmtree(extract_dir)# clean up extracted files
        return out_vid

# ---------------------------
# Main JSON processing
# ---------------------------
def process_json(json_path, out_dir="downloaded_media"):
    os.makedirs(out_dir, exist_ok=True)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)["Saved Media"]

    # If root is dict, try to find the list inside
    if isinstance(data, dict):
        # prefer an obvious key, else pick the first list found
        list_found = None
        for k, v in data.items():
            if isinstance(v, list):
                list_found = v
                break
        if list_found is not None:
            data = list_found
        else:
            # single object -> wrap
            data = [data]

    if not isinstance(data, list):
        print("Unexpected JSON root type:", type(data))
        return

    for entry in data:
        if not isinstance(entry, dict):
            # skip stray strings or invalid items
            print("Skipping non-dict entry in JSON (likely stray):", type(entry))
            continue

        media_url = entry.get("Media Download Url") or entry.get("Download Link") or entry.get("media_url")
        if not media_url:
            print("No media URL in item, skipping.")
            continue

        try:
            print("\nDownloading:", media_url)
            saved = wget.download(media_url, out=out_dir)
            print("\nSaved as:", saved)
        except Exception as e:
            print("Download failed:", e)
            continue

        saved_path = str(saved)
        output_path = None

        # If file is a zip -> extract + merge
        try:
            if zipfile.is_zipfile(saved_path) or saved_path.lower().endswith(".zip"):
                print("Detected ZIP, processing...")
                lat, lon = parse_latlon(entry.get("Location", "") or entry.get("location", ""))
                output_path = process_zip_file(saved_path, out_dir)
            else:
                # Not a zip - check if overlay exists side-by-side (rare case)
                # If it's an image and there's companion overlay file next to it, automatically merge
                p = Path(saved_path)
                stem = p.stem
                # look for companion overlay in same directory (stem-overlay.png or stem_overlay.png)
                possible_overlay_names = [
                    str(p.with_name(stem + "-overlay.png")),
                    str(p.with_name(stem + "_overlay.png")),
                    str(p.with_name(stem + ".overlay.png")),
                ]
                found_overlay = None
                for name in possible_overlay_names:
                    if Path(name).exists():
                        found_overlay = name
                        break

                if found_overlay:
                    print("Found companion overlay:", found_overlay)
                    if p.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                        out_img = str(Path(out_dir) / (p.stem + "_merged.jpg"))
                        ffmpeg_overlay_image(str(p), found_overlay, out_img)
                        output_path = out_img
                    else:
                        out_vid = str(Path(out_dir) / (p.stem + "_merged.mp4"))
                        ffmpeg_overlay_video(str(p), found_overlay, out_vid)
                        output_path = out_vid
                else:
                    # not a zip and no companion overlay: leave as-is
                    output_path = saved_path
        except Exception as e:
            print("Error while processing file:", e)
            output_path = saved_path


        # Get timestamp
        timestamp = entry.get("Date") or entry.get("date")
        #2021-10-06 23:09:21 UTC
        nicetime = timestamp.replace(":", "-").replace(" UTC", "").replace(" ", "_")


        # Embed GPS for images
        lat, lon = parse_latlon(entry.get("Location", "") or entry.get("location", ""))
        if output_path and str(output_path).lower().endswith((".jpg", ".jpeg")) and lat is not None and lon is not None:
            try:
                embed_gps_jpg(output_path, lat, lon, timestamp)
            except Exception as e:
                print("Failed to embed GPS:", e)

        # Embed GPS for videos
        lat, lon = parse_latlon(entry.get("Location", "") or entry.get("location", ""))
        if output_path and str(output_path).lower().endswith(".mp4") and lat is not None and lon is not None:
            try:
                embed_gps_mp4(output_path, lat, lon, timestamp)
            except Exception as e:
                print("Failed to embed GPS:", e)
        
        # Rename output file to include nicetime
        if output_path and nicetime:
            p = Path(output_path)
            new_name = f"{nicetime}_{p.name}"
            new_path = str(p.with_name(new_name))
            os.rename(output_path, new_path)
            print("Renamed output to include timestamp:", new_path)
            output_path = new_path


    print("\nALL DONE.")

def CheckOutputDir(outdir):
    # Find _extracted folders within outdir
    p = Path(outdir)
    remaining = []
    for subdir in p.iterdir():
        if subdir.is_dir() and subdir.name.endswith("_extracted"):
            remaining.append(subdir)
            #print("Left Over ", subdir)
            #shutil.rmtree(subdir)
    print(f"Found {len(remaining)} leftover extracted directories in {outdir}.")
    return remaining

def FindInJSON(json_path, search_str):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)["Saved Media"]

    for entry in data:
        if not isinstance(entry, dict):
            continue
        for k, v in entry.items():
            if isinstance(v, str) and search_str.lower() in v.lower():
                print(f"Found match in entry: {entry}")
                return entry

def FixRemaining(outdir, noDelete=False):
    remaining = CheckOutputDir(outdir)
    for subdir in remaining:
        print("Processing leftover directory:", subdir)
        main, overlay = find_main_and_overlay(str(subdir))
        if not main or not overlay:
            print("Could not find main or overlay in", subdir)
            continue

        main_ext = Path(main).suffix.lower()
        base_out = str(Path(outdir) / (subdir.stem.replace("_extracted", "") + "_merged"))
        if main_ext in [".jpg", ".jpeg", ".png", ".webp"]:
            out_img = base_out + ".jpg"
            overlay_image(main, overlay, out_img)
            print("Created merged image:", out_img)
            output_path = out_img

        else:
            out_vid = base_out + ".mp4"
            ffmpeg_overlay_video(main, overlay, out_vid)
            print("Created merged video:", out_vid)
            output_path = out_vid

        entry = FindInJSON("snap_data.json", subdir.stem.replace("_extracted", ""))

        # Get timestamp
        timestamp = entry.get("Date") or entry.get("date")

        # Embed GPS for images
        lat, lon = parse_latlon(entry.get("Location", "") or entry.get("location", ""))
        if output_path and str(output_path).lower().endswith((".jpg", ".jpeg")) and lat is not None and lon is not None:
            try:
                embed_gps_jpg(output_path, lat, lon, timestamp)
            except Exception as e:
                print("Failed to embed GPS:", e)

        # Embed GPS for videos
        lat, lon = parse_latlon(entry.get("Location", "") or entry.get("location", ""))
        if output_path and str(output_path).lower().endswith(".mp4") and lat is not None and lon is not None:
            try:
                embed_gps_mp4(output_path, lat, lon, timestamp)
            except Exception as e:
                print("Failed to embed GPS:", e)




        if not noDelete:
            shutil.rmtree(subdir)  # clean up extracted files

        # input("Press Enter to continue to next...")


# ---------------------------
# CLI
# ---------------------------
if __name__ == "__main__":
    logfile = "snap_media_processor.log"
    logfile = open(logfile, "a", encoding="utf-8")
    startTime = datetime.now()
    logfile.write(f"\n\n--- New Run at {startTime} ---\n")
    json_file = "snap_data.json"
    outdir = "downloaded_media"
    if not os.path.exists(outdir):
        os.makedirs(outdir)
    if not os.path.exists(json_file):
        print("Json Data Not found, Please place in the same directory as this script")
        input("Press Enter to exit")
        exit(1)
    
    process_json(json_file, outdir)
    if len(CheckOutputDir(outdir)) > 0:
        FixRemaining(outdir,noDelete=True)


    endTime = datetime.now()
    logfile.write(f"Ended at {endTime}\n")
    print("Started at:", startTime)
    print("Ended at:", endTime)
    duration = endTime - startTime
    duration = datetime.strftime(duration, "%H:%M:%S")
    print("Duration:", duration)
    logfile.write(f"Duration: {duration}\n")
    logfile.close()
