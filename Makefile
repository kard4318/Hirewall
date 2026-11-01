# Developer shortcuts for Hirewall (some are still placeholders)
.PHONY: help install dev test attack-suite screener-demo seed reset

help:
	@echo "Targets: install dev test attack-suite screener-demo seed reset"

install:
	@echo "install: placeholder, not implemented yet"

dev:
	@echo "dev: placeholder, not implemented yet"

screener-demo:
	python scripts/demo_screener.py --demo --job job-preset-backend --fake-llm

test:
	cd backend && python -m pytest .

attack-suite:
	cd backend && python -m pytest services/screener/tests/test_screener_attacks.py

seed:
	@echo "seed: placeholder, not implemented yet"

reset:
	@echo "reset: placeholder, not implemented yet"
