import json
import re
from pathlib import Path

import pdfplumber

PDF_DIR = Path(__file__).resolve().parents[1] / "docs" / "pdfs"
OUTPUT_PATH = Path("docs/data/****2026_users.json")
PASSWORD = "****2026"

# Matches IDs like ****2026-XXXX-00144 or ****2026-XXXXXX-00144
ID_REGEX = re.compile(r"****2026-[A-Z0-9]+-(\d{5})")


def extract_rows_from_text(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Normalize multiple spaces to single space for easier parsing
        normalized = re.sub(r"\s+", " ", line)
        match = ID_REGEX.search(normalized)
        if not match:
            continue

        iscc_id = match.group(1)
        after = normalized[match.end():].strip()
        if not after:
            continue

        # Heuristic: username is the first token, school is the remainder
        parts = after.split(" ", 1)
        username = parts[0]
        school = parts[1].strip() if len(parts) > 1 else ""
        if not school:
            continue

        rows.append({
            "iscc_id": iscc_id,
            "username": username,
            "school": school,
        })

    return rows


def main():
    results = []
    pdf_paths = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_paths:
        raise FileNotFoundError(f"No PDFs found in: {PDF_DIR}")

    for pdf_path in pdf_paths:
        with pdfplumber.open(str(pdf_path), password=PASSWORD) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                results.extend(extract_rows_from_text(text))

    # De-duplicate by iscc_id + username + school while preserving order
    seen = set()
    unique_results = []
    for row in results:
        key = (row["iscc_id"], row["username"], row["school"])
        if key in seen:
            continue
        seen.add(key)
        unique_results.append(row)

    OUTPUT_PATH.write_text(
        json.dumps(unique_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Wrote {len(unique_results)} rows to {OUTPUT_PATH} from {len(pdf_paths)} PDFs")


if __name__ == "__main__":
    main()
