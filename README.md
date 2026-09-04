# photosort

Safe Linux CLI photo organizer. Sorts chaotic folders into date-based trees **without ever losing a unique frame**.

## Features

- **Date folders** from EXIF `DateTimeOriginal` → `DateTime` → file mtime
  - `--depth month` (default): `YYYY/MM/`
  - `--depth day`: `YYYY/MM/DD/`
- **Duplicate safety (content SHA-256)**
  - Same filename ≠ duplicate
  - Same name, different bytes → keep **both** (safe `_1`, `_2`, … rename)
  - Identical bytes → skip redundant copy (never overwrite unique files)
  - Default mode is **COPY** (non-destructive); use `--move` to move
  - Every decision is logged; unique content-hash inventory is verified
- **Metadata / stats**: aperture, focal length, lens, camera, shutter, ISO, datetime
  - `photosort stats ./library` scans the folder (or uses `photosort_metadata.json` if organize already wrote it)
  - most-used lenses / focal lengths; optional matplotlib chart

## Install

```bash
cd photos
python -m pip install -e ".[dev]"
# optional charts:
python -m pip install -e ".[charts]"
```

## Usage

```bash
# Copy into YYYY/MM/ (default), never delete sources
photosort organize ./inbox ./library

# Day-level folders
photosort organize ./inbox ./library --depth day

# Move instead of copy
photosort organize ./inbox ./library --move

# Preview only
photosort organize ./inbox ./library --dry-run

# Stats from a library folder (scans EXIF; uses cached JSON if present)
photosort stats ./library
photosort stats ./library --rescan
photosort stats ./library --save
photosort stats ./library --lens "NIKKOR Z 50mm f/1.8 S"
photosort stats ./library --chart focals.png

# Or point at the JSON explicitly
photosort stats ./library/photosort_metadata.json
```

Also: `python -m photosort …`

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
