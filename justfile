export PYTHON_GIL := "0"

alias a := audit
alias c := check
alias r := run
alias t := test
alias ci := continuous_integration

[private]
default:
    @just --choose

bootstrap:
    @command -v uv >/dev/null 2>&1 || { echo "Error: uv is required but was not found in PATH." >&2; exit 1; }
    uv sync --locked

check:
    uvx prek@latest run --all-files

run *args:
    rm ./data/songs.db; uv run skip-radio {{ args }}

test *args:
    uv run -- pytest {{ args }}

audit:
    uv audit

continuous_integration: bootstrap audit check test
