.DEFAULT_GOAL := help
.PHONY: help setup init validate test leaks skills compaction-test compaction mutants check replay clean

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | column -t -s "$$(printf '\t')"

setup: ## Once per clone: turn on the pre-push check and confirm uv and claude are on PATH
	@command -v uv >/dev/null || { echo "uv is missing: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	@command -v claude >/dev/null || { echo "claude is missing: install Claude Code"; exit 1; }
	git config core.hooksPath .githooks
	@echo "pre-push check on; run make check to try it"

init: ## Set a project up for the plugin: make init PROJECT=/path/to/project (opens /harness:init there)
	@test -n "$(PROJECT)" || { echo "usage: make init PROJECT=/path/to/project"; exit 1; }
	@test -d "$(PROJECT)" || { echo "no such folder: $(PROJECT)"; exit 1; }
	cd "$(PROJECT)" && claude "/harness:init"

validate: ## Check the plugin and marketplace files
	claude plugin validate .

test: ## Hook cases
	uv run python tests/run_cases.py

leaks: ## Fail when a file names a person, machine, home path or private word
	uv run python tests/check_leaks.py

skills: ## Fail when a skill or agent leaves the form AGENTS.md demands
	uv run python tests/check_skills.py

compaction-test: ## Check bin/compaction-report on a synthetic log folder
	uv run python tests/check_compaction.py

compaction: ## Measure auto-compaction cost in your Claude Code logs: report in compaction-report/ (SINCE=, UNTIL= as YYYY-MM-DD)
	uv run --script bin/compaction-report $(if $(SINCE),--since $(SINCE),) $(if $(UNTIL),--until $(UNTIL),)

mutants: ## Deliberate-bug audit of every rule; slow, run it once (MUTANT=text narrows it)
	uv run python tests/mutants.py $(if $(MUTANT),--only $(MUTANT),)

check: ## What the pre-push hook runs: cases, mutant check, skill form, leaks
	uv run python tests/run_cases.py
	uv run python tests/mutants.py --check
	uv run python tests/check_skills.py
	uv run python tests/check_leaks.py
	uv run python tests/check_compaction.py

replay: ## Run the always-on guard over your past Bash commands to find false refusals
	uv run --script hooks/replay.py

clean: ## Empty scratch/ and remove caches (never touches tracked files or .venv); refuses while a mutant audit runs
	@test ! -e scratch/hook-mutants || { echo "a mutant audit is using scratch/"; exit 1; }
	find scratch -mindepth 1 -delete 2>/dev/null || true
	find . -path ./.git -prune -o -path ./.venv -prune -o -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache
