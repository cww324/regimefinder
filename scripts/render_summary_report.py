import json
from datetime import datetime, timezone
from pathlib import Path


SUMMARY_PATH = Path("results/summary.json")
STATUS_PATH = Path("reports/STATUS.md")


def load_summary() -> dict:
    if not SUMMARY_PATH.exists():
        return {}
    txt = SUMMARY_PATH.read_text(encoding="utf-8").strip()
    if not txt:
        return {}
    return json.loads(txt)


def fmt_num(v):
    if v is None:
        return "n/a"
    if isinstance(v, (int, float)):
        return f"{v:.6f}" if isinstance(v, float) else str(v)
    return str(v)


def build_markdown(summary: dict) -> str:
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        "# STATUS",
        "",
        f"Generated: {ts}",
        "",
    ]
    if not summary:
        lines.extend(["No hypothesis results in `results/summary.json`.", ""])
        return "\n".join(lines)

    lines.extend(
        [
            "| Hypothesis | Classification | Gross n | Gross mean | Slip4 mean | Slip5 mean | Timestamp |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for hyp_id in sorted(summary.keys()):
        row = summary[hyp_id]
        cost_modes = row.get("cost_modes", {})
        gross = cost_modes.get("gross", {}).get("metrics", {}).get("baseline", {})
        slip4 = cost_modes.get("bps8", {}).get("metrics", {}).get("baseline", {})
        slip5 = cost_modes.get("bps10", {}).get("metrics", {}).get("baseline", {})
        lines.append(
            "| "
            f"{hyp_id} | "
            f"{row.get('final_status', 'n/a')} | "
            f"{fmt_num(gross.get('n'))} | "
            f"{fmt_num(gross.get('mean'))} | "
            f"{fmt_num(slip4.get('mean'))} | "
            f"{fmt_num(slip5.get('mean'))} | "
            f"{row.get('timestamp_utc', 'n/a')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    summary = load_summary()
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(build_markdown(summary), encoding="utf-8")
    print(f"wrote {STATUS_PATH}")


if __name__ == "__main__":
    main()
