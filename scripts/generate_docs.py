"""Build documentation artifacts from the installed CLI, without contacting Anki."""

from pathlib import Path

from ankiloom.cli import command_reference, skill_text

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "reference"
PUBLIC = ROOT / "docs" / "public"


def main() -> None:
    REFERENCE.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (REFERENCE / "cli.md").write_text(
        "# CLI reference\n\n"
        "Generated from this checkout's command definitions at build time. "
        "For the version you have installed, run `ankiloom --help` or "
        "`ankiloom COMMAND --help`.\n\n" + command_reference(),
        encoding="utf-8",
    )
    skill = skill_text()
    (REFERENCE / "skill.md").write_text(
        "# Agent skill\n\n"
        "This is the skill exported by `ankiloom --skill`, including the generated "
        'command reference. <a href="../SKILL.md" download="SKILL.md">Download SKILL.md</a>.\n\n'
        "````markdown\n" + skill + "\n````\n",
        encoding="utf-8",
    )
    (PUBLIC / "SKILL.md").write_text(skill, encoding="utf-8")


if __name__ == "__main__":
    main()
