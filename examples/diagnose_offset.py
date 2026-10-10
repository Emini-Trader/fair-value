"""Self-diagnostic: does the carry model offset systematically drift from the
observed front basis -- near expiry, or on funding-turn sessions?

The snapshot build (web/build_fairvalue.py) appends one record per session to
web/offset_history.jsonl: the model offset (fair value premium) and the observed
front basis (ES_front - SPX close), with days-to-expiry and a turn flag. This
script aggregates that log -- no network, just reads the file.

    python examples/diagnose_offset.py

Random per-session close noise (the SPX/ES settlement mismatch) averages out, so
a *mean* gap ~ 0 in a bucket means the model tracks the observed basis there
(nothing to correct). A stable non-zero mean -- e.g. near expiry on turns -- is
the data-measured drift to fold back in (no hand-set constant). This is what
decides whether step (iii), an automatic turn correction, is even warranted.
"""
import json
import pathlib
import statistics as st
import sys

#: (low, high) inclusive days-to-expiry buckets; the turn effect concentrates low.
DEFAULT_DTE_BUCKETS = ((0, 21), (22, 45), (46, 200))


def bucket_offset_gaps(records, dte_buckets=DEFAULT_DTE_BUCKETS):
    """Aggregate model-vs-observed offset gaps by (days-to-expiry bucket, turn).

    Args:
        records: iterable of dicts with ``dte`` (int), ``turn`` (bool),
            ``model_offset`` (float) and ``observed_basis`` (float).
        dte_buckets: inclusive ``(low, high)`` day ranges.

    ``gap = model_offset - observed_basis`` (signed: positive means the model
    prices the front richer than it traded). Returns a list of
    ``{bucket, turn, n, mean, stdev}`` rows, non-empty buckets only.
    """
    out = []
    for lo, hi in dte_buckets:
        for turn in (False, True):
            gaps = [
                r["model_offset"] - r["observed_basis"]
                for r in records
                if lo <= r["dte"] <= hi and bool(r.get("turn")) == turn
            ]
            if not gaps:
                continue
            out.append({
                "bucket": f"{lo}-{hi}d",
                "turn": turn,
                "n": len(gaps),
                "mean": st.fmean(gaps),
                "stdev": st.pstdev(gaps) if len(gaps) > 1 else 0.0,
            })
    return out


def _load(path: pathlib.Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    rows.sort(key=lambda r: r.get("date", ""))
    return rows


def main() -> int:
    log = pathlib.Path(__file__).resolve().parent.parent / "web" / "offset_history.jsonl"
    if not log.exists() or not log.read_text().strip():
        print(f"No offset history yet at {log}\n"
              f"It accumulates one record per session as the snapshot runs; "
              f"re-run after a few sessions.")
        return 0
    records = _load(log)
    rows = bucket_offset_gaps(records)
    print(f"Offset self-diagnostic over {len(records)} sessions "
          f"({records[0]['date']} .. {records[-1]['date']})")
    print("  gap = model_offset - observed_basis (ES_front - SPX close)\n")
    print(f"{'bucket':>8} {'turn':>5} {'n':>4} {'mean gap':>9} {'stdev':>7}")
    print("-" * 38)
    for r in rows:
        print(f"{r['bucket']:>8} {str(r['turn']):>5} {r['n']:>4} "
              f"{r['mean']:>+9.2f} {r['stdev']:>7.2f}")
    print("-" * 38)
    print("mean ~ 0  -> model tracks the observed basis (nothing to correct).\n"
          "stable non-zero mean near expiry / on turns -> the drift to fold back\n"
          "in, data-measured (no constant). Needs enough sessions per bucket first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
