"""Build a manual-install ZIP without local configuration or development files."""

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "guernsey_bin_night"


def main() -> None:
    """Package the integration using the manifest's version."""
    version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
    destination = ROOT / "dist" / f"guernsey_bin_night-{version}.zip"
    destination.parent.mkdir(exist_ok=True)
    files = [
        path
        for path in COMPONENT.rglob("*")
        if path.is_file() and path.suffix in {".py", ".json", ".png"}
    ]
    files.extend([ROOT / "README.md", ROOT / "LICENSE"])
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(ROOT))
    print(destination)


if __name__ == "__main__":
    main()
