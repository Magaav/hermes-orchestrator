.PHONY: context-check context-fix

context-check:
	python3 tools/context/check-context-sync.py

context-fix:
	python3 tools/context/check-context-sync.py --fix
