"""Write exact installed runtime dependency versions for advisory auditing."""

import sys
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement


def main(destination):
    pending = ["pdfblinder"]
    seen = {}
    while pending:
        installed = distribution(pending.pop())
        name = installed.metadata["Name"]
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        seen[key] = f"{name}=={installed.version}"
        for specifier in installed.requires or []:
            requirement = Requirement(specifier)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    seen.pop("pdfblinder")  # unreleased local project has no PyPI advisory entry
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(sorted(seen.values())) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
