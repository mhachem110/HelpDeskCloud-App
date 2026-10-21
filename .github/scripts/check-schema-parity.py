"""Check that the Helm migration schema mirrors the canonical local schema."""

import argparse
from pathlib import Path


CANONICAL = Path("database/init.sql")
HELM_MIRROR = Path("helm/helpdesk/files/001_init.sql")


def check_schema_parity(repository_root):
    root = Path(repository_root)
    canonical = (root / CANONICAL).read_bytes()
    mirror = (root / HELM_MIRROR).read_bytes()
    if canonical != mirror:
        raise ValueError(
            f"{HELM_MIRROR} is out of sync with canonical {CANONICAL}; "
            "review both files before updating the required Helm mirror"
        )
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path,
                        default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    try:
        check_schema_parity(args.repository_root)
        print(f"{HELM_MIRROR} matches canonical {CANONICAL}.")
        return 0
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
