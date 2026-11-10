# Show available development commands.
default:
    @just --list

# Install the current checkout as a uv tool, replacing any installed version.
install:
    uv tool install --force .

# Check lint, formatting, and types without modifying files.
check:
    uv run ruff check .
    uv run ruff format --check .
    uv run ty check

# Serve the documentation locally (run npm ci first).
docs:
    npm run docs:dev

# Generate command references and build the documentation.
docs-build:
    npm run docs:build
