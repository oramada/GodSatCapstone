#!/usr/bin/env python3
"""Inventory BUAA-MSOD without extracting its multi-gigabyte image archive."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import struct
import zipfile
from pathlib import Path


EXPECTED_BYTES = 3_202_765_210
EXPECTED_MD5 = "d5ade6c7313b236f251a781424c7fbbd"
RECORD_URL = "https://zenodo.org/records/15187755"


def read_tiff_dimensions_and_bits(zf: zipfile.ZipFile, member: str) -> tuple[int, int, tuple[int, ...]]:
    """Read TIFF IFD dimensions and BitsPerSample using only the standard library."""
    with zf.open(member) as source:
        header = source.read(8)
        if len(header) != 8 or header[:2] not in (b"II", b"MM"):
            raise ValueError(f"invalid TIFF header: {member}")
        endian = "<" if header[:2] == b"II" else ">"
        if struct.unpack(endian + "H", header[2:4])[0] != 42:
            raise ValueError(f"unsupported TIFF magic: {member}")
        ifd_offset = struct.unpack(endian + "I", header[4:8])[0]
        source.seek(ifd_offset)
        entry_count_raw = source.read(2)
        if len(entry_count_raw) != 2:
            raise ValueError(f"missing TIFF IFD: {member}")
        entry_count = struct.unpack(endian + "H", entry_count_raw)[0]
        wanted: dict[int, tuple[int, ...]] = {}
        for _ in range(entry_count):
            entry = source.read(12)
            if len(entry) != 12:
                raise ValueError(f"truncated TIFF IFD: {member}")
            tag, value_type, value_count = struct.unpack(endian + "HHI", entry[:8])
            if tag not in (256, 257, 258):
                continue
            if value_type not in (3, 4):  # SHORT or LONG
                raise ValueError(f"unsupported TIFF dimension field type: {member}")
            unit = 2 if value_type == 3 else 4
            fmt = "H" if value_type == 3 else "I"
            byte_count = value_count * unit
            value_area = entry[8:12]
            if byte_count <= 4:
                raw = value_area[:byte_count]
            else:
                current = source.tell()
                value_offset = struct.unpack(endian + "I", value_area)[0]
                source.seek(value_offset)
                raw = source.read(byte_count)
                source.seek(current)
            if len(raw) != byte_count:
                raise ValueError(f"truncated TIFF tag {tag}: {member}")
            wanted[tag] = struct.unpack(endian + str(value_count) + fmt, raw)
        if 256 not in wanted or 257 not in wanted or 258 not in wanted:
            raise ValueError(f"missing TIFF width/height/bits tag: {member}")
        return wanted[256][0], wanted[257][0], wanted[258]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=Path("data/ground_sensor/buaa_msod/MSOD.zip"))
    parser.add_argument("--output", type=Path, default=Path("data/ground_sensor/buaa_msod/audit.json"))
    parser.add_argument("--skip-md5", action="store_true", help="Skip hashing the 3.2 GB archive")
    parser.add_argument("--skip-crc", action="store_true", help="Skip reading and CRC-checking every archive member")
    args = parser.parse_args()

    archive = args.archive
    size_bytes = archive.stat().st_size
    md5 = None
    if not args.skip_md5:
        digest = hashlib.md5()
        with archive.open("rb") as source:
            for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
                digest.update(block)
        md5 = digest.hexdigest()

    counts: dict[str, dict] = {}
    group_sets: dict[str, set[str]] = {}
    tiff_metadata: collections.Counter[str] = collections.Counter()
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        tiff_files = [name for name in zf.namelist() if name.lower().endswith(".tif")]
        for name in tiff_files:
            width, height, bits = read_tiff_dimensions_and_bits(zf, name)
            tiff_metadata[f"{width}x{height};bits_per_sample={','.join(map(str, bits))}"] += 1
        for split in ("train", "val", "test"):
            prefix = f"MSOD/{split}/"
            image_names = {
                name[len(prefix + "images/") : -4]: name
                for name in zf.namelist()
                if name.startswith(prefix + "images/") and name.lower().endswith(".tif")
            }
            group_sets[split] = {stem.split("/")[0] for stem in image_names}
            label_names = {
                name[len(prefix + "labels/") : -4]: name
                for name in zf.namelist()
                if name.startswith(prefix + "labels/") and name.lower().endswith(".txt")
            }
            class_counts: collections.Counter[str] = collections.Counter()
            empty_labels = 0
            annotated_files = 0
            boxes = 0
            malformed_lines = 0
            for name in label_names.values():
                lines = zf.read(name).decode("utf-8").splitlines()
                lines = [line.strip() for line in lines if line.strip()]
                if not lines:
                    empty_labels += 1
                    continue
                annotated_files += 1
                for line in lines:
                    fields = line.split()
                    if len(fields) != 5:
                        malformed_lines += 1
                        continue
                    class_counts[fields[0]] += 1
                    boxes += 1
            list_name = f"MSOD/{split}.txt"
            image_list = zf.read(list_name).decode("utf-8").splitlines()
            counts[split] = {
                "images": len(image_names),
                "labels": len(label_names),
                "empty_label_files": empty_labels,
                "annotated_label_files": annotated_files,
                "bounding_boxes": boxes,
                "class_counts": dict(sorted(class_counts.items())),
                "malformed_label_lines": malformed_lines,
                "image_without_label_stem_count": len(set(image_names) - set(label_names)),
                "label_without_image_stem_count": len(set(label_names) - set(image_names)),
                "listed_image_paths": len(image_list),
                "listed_path_example": image_list[0] if image_list else None,
                "folder_group_count": len({stem.split("/")[0] for stem in image_names}),
                "folder_group_examples": sorted({stem.split("/")[0] for stem in image_names})[:5],
                "annotated_frame_fraction": annotated_files / len(image_names) if image_names else None,
            }

        split_group_overlaps = {
            "train_val": sorted(group_sets["train"] & group_sets["val"]),
            "train_test": sorted(group_sets["train"] & group_sets["test"]),
            "val_test": sorted(group_sets["val"] & group_sets["test"]),
        }

        bad_crc_member = None if args.skip_crc else zf.testzip()
        archive_summary = {
            "member_count": len(infos),
            "uncompressed_bytes": sum(info.file_size for info in infos),
            "crc_check": "skipped" if args.skip_crc else ("passed" if bad_crc_member is None else "failed"),
            "bad_crc_member": bad_crc_member,
        }

    result = {
        "dataset": "BUAA-MSOD",
        "source_record": RECORD_URL,
        "license": "CC BY 4.0",
        "archive": str(archive),
        "archive_size_bytes": size_bytes,
        "publisher_expected_size_bytes": EXPECTED_BYTES,
        "size_matches_publisher": size_bytes == EXPECTED_BYTES,
        "archive_md5": md5,
        "publisher_expected_md5": EXPECTED_MD5,
        "md5_matches_publisher": md5 == EXPECTED_MD5 if md5 is not None else None,
        "archive_summary": archive_summary,
        "archive_tiff_metadata": {
            "file_count": len(tiff_files),
            "dimension_and_bit_depth_counts": dict(sorted(tiff_metadata.items())),
        },
        "splits": counts,
        "split_folder_group_overlaps": split_group_overlaps,
        "publisher_observation_metadata": {
            "site": "Xinglong Observatory, National Astronomical Observatories, Chinese Academy of Sciences",
            "telescope_mode": "track rate",
            "field_of_view_degrees": [5, 5],
            "exposure_times_ms": [150, 240],
            "source_image_resolution": "16-bit, 6000 x 6000 pixels",
            "source_observational_sequences": 4,
            "source_frames_per_sequence": 60,
        },
        "study_interpretation": {
            "supports": "crop-level optical object-detection benchmarking with annotated boxes and empty-label crops within the benchmark split",
            "does_not_supply": "full-field frame opportunity counts, catalog-wide task opportunities, sensor health/outage telemetry, or operational acquisition-failure causes; empty crops alone do not establish these quantities",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["size_matches_publisher"] or (md5 is not None and not result["md5_matches_publisher"]):
        raise SystemExit("publisher archive size or checksum mismatch")
    if archive_summary["bad_crc_member"]:
        raise SystemExit(f"archive CRC failure: {archive_summary['bad_crc_member']}")


if __name__ == "__main__":
    main()
