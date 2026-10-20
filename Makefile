.PHONY: test

PYTHON ?= python3

test:
	$(PYTHON) -B -m unittest discover -s tests -p 'test_*.py'
