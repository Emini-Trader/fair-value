"""Tests for the offset self-diagnostic aggregator (examples/diagnose_offset.py).

Pure logic, loaded by path -- no network, no log file needed.
"""

import importlib.util
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parent.parent / "examples" / "diagnose_offset.py"
_spec = importlib.util.spec_from_file_location("diagnose_offset", _SRC)
diagnose_offset = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diagnose_offset)

bucket_offset_gaps = diagnose_offset.bucket_offset_gaps


def test_bucket_offset_gaps_splits_by_dte_and_turn():
    records = [
        # near-expiry, non-turn: gaps 0.0, +0.4 -> mean +0.2
        {"dte": 10, "turn": False, "model_offset": 14.0, "observed_basis": 14.0},
        {"dte": 18, "turn": False, "model_offset": 14.4, "observed_basis": 14.0},
        # near-expiry, turn: gaps -1.0, -2.0 -> mean -1.5 (model light vs basis)
        {"dte": 12, "turn": True, "model_offset": 13.0, "observed_basis": 14.0},
        {"dte": 20, "turn": True, "model_offset": 12.0, "observed_basis": 14.0},
        # far bucket, non-turn: gap +0.2
        {"dte": 90, "turn": False, "model_offset": 65.2, "observed_basis": 65.0},
    ]
    by = {(r["bucket"], r["turn"]): r for r in bucket_offset_gaps(records)}
    assert by[("0-21d", False)]["n"] == 2
    assert by[("0-21d", False)]["mean"] == pytest.approx(0.2)
    assert by[("0-21d", True)]["n"] == 2
    assert by[("0-21d", True)]["mean"] == pytest.approx(-1.5)
    assert by[("46-200d", False)]["mean"] == pytest.approx(0.2)
    assert ("22-45d", False) not in by  # empty buckets omitted


def test_bucket_offset_gaps_empty():
    assert bucket_offset_gaps([]) == []
