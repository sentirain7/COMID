"""Unit tests for DumpParser last-frame parsing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from parsers.dump_parser import DumpParser


def _make_frame(timestep: int, n_atoms: int = 2) -> str:
    atom_lines = "\n".join(
        f"{atom_id} 1 {atom_id * 0.1:.3f} {atom_id * 0.2:.3f} {atom_id * 0.3:.3f}"
        for atom_id in range(1, n_atoms + 1)
    )
    return (
        "ITEM: TIMESTEP\n"
        f"{timestep}\n"
        "ITEM: NUMBER OF ATOMS\n"
        f"{n_atoms}\n"
        "ITEM: BOX BOUNDS pp pp pp\n"
        "0 10\n"
        "0 10\n"
        "0 10\n"
        "ITEM: ATOMS id type x y z\n"
        f"{atom_lines}\n"
    )


def test_parse_last_frame_returns_final_timestep(tmp_path):
    dump_file = tmp_path / "traj.dump"
    dump_file.write_text(_make_frame(0) + _make_frame(100) + _make_frame(200))

    parser = DumpParser()
    frame = parser.parse_last_frame(dump_file)

    assert frame is not None
    assert frame.timestep == 200
    assert frame.n_atoms == 2
    assert frame.atoms[0]["id"] == 1


def test_find_last_marker_offset_handles_chunk_boundaries(tmp_path):
    parser = DumpParser()
    marker = b"ITEM: TIMESTEP"

    prefix_size = (1024 * 1024) - 5
    payload = b"A" * prefix_size + marker + b"\n123\n"
    dump_file = tmp_path / "boundary.dump"
    dump_file.write_bytes(payload)

    offset = parser._find_last_marker_offset(dump_file, marker)

    assert offset == prefix_size


def test_parse_last_frame_returns_none_when_marker_missing(tmp_path):
    dump_file = tmp_path / "invalid.dump"
    dump_file.write_text("no frame marker here\n")

    parser = DumpParser()
    frame = parser.parse_last_frame(dump_file)

    assert frame is None
