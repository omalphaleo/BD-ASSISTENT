# Thin entry point for `make check` (B5). All logic lives in scripts/check.sh so the same checks
# run with `bash scripts/check.sh` on machines where make is unavailable or blocked.

.PHONY: check

check:
	bash scripts/check.sh
