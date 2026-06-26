.PHONY: context-check context-fix harness-check loop-copilot

context-check:
	python3 tools/context/check-context-sync.py
	python3 tools/context/check-harness-promises.py

context-fix:
	python3 tools/context/check-context-sync.py --fix
	python3 tools/context/check-harness-promises.py

harness-check:
	python3 tools/context/check-harness-promises.py

loop-copilot:
	python3 tools/context/watch-loop-copilot.py
