"""Paths for technical artifacts in ordinary workflow cases."""
from pathlib import Path
import argparse

TECH_DIR = "_llm"


def case_for_artifact(path: Path) -> Path:
    """Return the case used for document references in a matter YAML file."""
    parent = path.parent
    return parent.parent if parent.name == TECH_DIR else parent


def technical_path(case: Path, name: str | Path, *, create_parent: bool = False) -> Path:
    """Use an existing legacy location, otherwise use _llm.

    Raise on two locations so that a reader or writer cannot silently split state.
    Anonymizer projects retain their separately enforced layout.
    """
    case = Path(case)
    name = Path(name)
    if name.is_absolute() or name.drive or ".." in name.parts or not name.parts:
        raise ValueError(f"Ожидается путь относительно служебной папки: {name}")
    legacy = case / name
    if "_anonymizer" in case.parts or case.name == TECH_DIR:
        return legacy
    current = case / TECH_DIR / name
    if legacy.exists() and current.exists():
        raise ValueError(f"Два расположения служебного файла: {legacy} и {current}")
    path = legacy if legacy.exists() else current
    if not path.resolve().is_relative_to(case.resolve()):
        raise ValueError(f"Служебный путь выходит за пределы дела: {path}")
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("name")
    args = parser.parse_args()
    try:
        print(technical_path(args.case, args.name))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
