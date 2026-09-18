export PYTHON_GIL := "0"

alias a := audit
alias c := check
alias r := run
alias t := test

[private]
default:
    @just --choose

setup:
    uv python install 3.14

check:
    uv run -- prek run --all-files

run *args:
    rm ./data/songs.db; uv run skip-radio {{ args }}

test *args:
    uv run -- pytest {{ args }}

audit:
    uv audit

ci: setup audit check test
