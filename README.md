# photosort

Safe Linux CLI photo organizer. Sorts chaotic folders into date-based trees **without ever losing a unique frame**.

## Features

- **Date folders** from EXIF `DateTimeOriginal` → `DateTime` → file mtime
  - `--depth month` (default): `YYYY/MM/`
  - `--depth day`: `YYYY/MM/DD/`
- **In-place or into a library**
  - `photosort organize SOURCE` — dest omitted → sort **in place** under `SOURCE` into `YYYY/MM`
  - `photosort organize SOURCE DEST` — sort from source into dest
- **Duplicate safety (content SHA-256)**
  - Same filename ≠ duplicate
  - Same name, different bytes → keep **both** (safe `_1`, `_2`, … rename)
  - Identical bytes → skip redundant transfer (never overwrite unique files)
  - Already at the correct date path → left alone (`already_sorted`)
  - Default mode is **MOVE**; use `--copy` for non-destructive copy (`--move` kept as explicit alias)
  - Every decision is logged; unique content-hash inventory is verified
- **Metadata / stats**: aperture, focal length, lens, camera, shutter, ISO, datetime
  - `photosort stats ./library` walks **all subfolders** and reads EXIF (use `--cache` for JSON only)
  - most-used lenses / focal lengths; optional matplotlib chart

## Install

```bash
cd photos
python -m pip install -e ".[dev]"
# optional charts:
python -m pip install -e ".[charts]"
```

### RAW metadata (important)

Pillow cannot read lens/focal tags from most RAW files (CR2/NEF/ARW/DNG/…).
Install **ExifTool** so `stats` / organize see the same tags as Lightroom:

```bash
# Debian/Ubuntu
sudo apt install libimage-exiftool-perl
# macOS
brew install exiftool
```

`photosort stats` will print which reader it uses. Without ExifTool, RAW frames still count in "Photos scanned" but show up under "no lens EXIF".

## Usage

```bash
# In-place sort under ./inbox into YYYY/MM/ (default MOVE)
photosort organize ./inbox

# Move into a separate library
photosort organize ./inbox ./library

# Non-destructive copy instead of move
photosort organize ./inbox ./library --copy

# Day-level folders
photosort organize ./inbox ./library --depth day

# Explicit move (default; alias for back-compat)
photosort organize ./inbox ./library --move

# Preview only
photosort organize ./inbox ./library --dry-run

# Stats: walks ALL subfolders by default (live EXIF)
photosort stats ./library
photosort stats ./library --cache          # optional: use photosort_metadata.json
photosort stats ./library --save
photosort stats ./library --lens "NIKKOR Z 50mm f/1.8 S"
# After scan, prompts Y/n to show a bar chart (X=focal mm min→max, Y=count)
# or non-interactive:
photosort stats ./library --open-chart
photosort stats ./library --chart focals.png --no-open

# Or point at the JSON explicitly
photosort stats ./library/photosort_metadata.json
```

Also: `python -m photosort …`

## Progress / verbosity

By default both `organize` and `stats` print live progress on stderr (`==> phase`, `[n/total] …`).

- `-v` / `--verbose` (`organize`): also echo every decision to stderr
- `-q` / `--quiet`: hide progress; final summary/stats only
- Full decision log for organize: `DEST/photosort.log` (override with `--log`)

## Tests

```bash
pytest -q
```

## Layout

```
photosort/          # package
tests/              # pytest + Pillow/piexif fixtures
pyproject.toml
requirements.txt
```
