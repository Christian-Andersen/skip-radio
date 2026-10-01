alias a := audit
alias c := check
alias r := run
alias t := test

[private]
default:
    @just --choose

check:
    uv run -- prek run --all-files

run *args:
    rm -f ./data/songs.db; uv run skip-radio {{ args }}

test *args:
    uv run -- pytest {{ args }}

audit:
    uv audit

ci: audit check test
