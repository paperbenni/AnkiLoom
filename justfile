# Show available development commands.
default:
    @just --list

# Check lint, formatting, and types without modifying files.
check:
    uv run ruff check .
    uv run ruff format --check .
    uv run ty check
