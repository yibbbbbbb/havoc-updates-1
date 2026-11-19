"""Generate the desktop release channel from an already committed artifact."""

import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FILE = "public/desktop/HavocMidnight.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "revision", help="Full commit ID containing the standalone desktop"
    )
    revision = parser.parse_args().revision
    if not re.fullmatch("[0-9a-f]{40}", revision):
        parser.error("Pass a full, 40-character Git commit ID.")
    data = subprocess.check_output(["git", "show", revision + ":" + FILE], cwd=REPO)
    if data != (REPO / FILE).read_bytes():
        parser.error("The checked-out desktop does not match the target commit.")
    tree = ast.parse(data)
    compile(tree, FILE, "exec")
    versions = [
        s.value.value
        for s in tree.body
        if isinstance(s, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "DESKTOP_RELEASE" for t in s.targets
        )
        and isinstance(s.value, ast.Constant)
    ]
    if len(versions) != 1 or not re.fullmatch(
        r"(0|[1-9][0-9]{0,5})(\.(0|[1-9][0-9]{0,5})){2}", versions[0]
    ):
        parser.error("The desktop must declare one numeric three-part release number.")
    if len(data) > 8 * 1024 * 1024:
        parser.error("The desktop exceeds the updater download limit.")
    manifest = {
        "product": "havoc-midnight-desktop",
        "version": versions[0],
        "revision": revision,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }
    (REPO / "public/desktop/stable.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print("Prepared Havoc desktop", versions[0], "at", revision)


if __name__ == "__main__":
    main()
