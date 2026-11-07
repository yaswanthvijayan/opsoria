"""Read-only export script to extract seed demo incidents from local opsoria.db.

Uses SQLite URI mode=ro to ensure opsoria.db is never modified.
Outputs rows for INC-SYNTH-072237 and INC-SYNTH-051098 to backend/seed_demo.json.
"""

import json
import os
import sqlite3
import sys

TARGET_IDS = ("INC-SYNTH-072237", "INC-SYNTH-051098")


def export_seed_data():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "opsoria.db")
    out_path = os.path.join(base_dir, "seed_demo.json")

    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    # SQLite read-only URI connection
    conn_uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(conn_uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in TARGET_IDS)
        cur.execute(
            f"SELECT * FROM incidents WHERE incident_id IN ({placeholders}) ORDER BY created_at ASC",
            TARGET_IDS,
        )
        rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            print("Warning: No matching incidents found in database.", file=sys.stderr)
            sys.exit(1)

        # Parse stored JSON fields if they are stringified so seed JSON is clean and valid
        clean_rows = []
        for row in rows:
            clean_row = dict(row)
            for json_field in ("possible_causes", "metadata", "last_analysis"):
                val = clean_row.get(json_field)
                if isinstance(val, str):
                    try:
                        clean_row[json_field] = json.loads(val)
                    except Exception:
                        pass
            clean_rows.append(clean_row)

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(clean_rows, f, indent=2)

        print(f"Successfully exported {len(clean_rows)} seed rows to {out_path}:")
        for r in clean_rows:
            print(f"  - {r['incident_id']} (status: {r['status']}, memory_status: {r['memory_status']})")
    finally:
        conn.close()


if __name__ == "__main__":
    export_seed_data()

