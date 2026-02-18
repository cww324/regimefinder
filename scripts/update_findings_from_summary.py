import json
from pathlib import Path


SUMMARY_PATH = Path("results/summary.json")
FINDINGS_SIMPLE = Path("FINDINGS_SIMPLIFIED.md")
START = "<!-- DERIVED_STATUS_START -->"
END = "<!-- DERIVED_STATUS_END -->"


def build_block(summary: dict) -> str:
    lines = [START, "", "## Derived Status (Artifact-Backed)"]
    for hyp_id in sorted(summary.keys()):
        row = summary[hyp_id]
        lines.append(
            f"- {hyp_id}: `{row.get('final_status')}` "
            f"(artifact: `results/runs/{row.get('latest_artifact')}`)"
        )
    lines.extend(["", END, ""])
    return "\n".join(lines)


def replace_or_append(text: str, block: str) -> str:
    if START in text and END in text:
        pre = text.split(START)[0].rstrip()
        post = text.split(END, 1)[1].lstrip("\n")
        return f"{pre}\n\n{block}\n{post}"
    return text.rstrip() + "\n\n" + block


def main() -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    original = FINDINGS_SIMPLE.read_text(encoding="utf-8")
    block = build_block(summary)
    updated = replace_or_append(original, block)
    FINDINGS_SIMPLE.write_text(updated, encoding="utf-8")
    print(f"updated={FINDINGS_SIMPLE}")


if __name__ == "__main__":
    main()
