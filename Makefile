PY ?= .venv/bin/python
SPACE ?= Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263
PRODUCT ?= BMC Helix ITSM
VERSION ?= 26.3
WORK ?= /tmp/helix
ENGINE ?= weasyprint
# same name the script would choose by itself: spaces -> dashes
PDFNAME := $(shell printf '%s' "$(PRODUCT)" | tr ' ' '-')-$(VERSION)-complete.pdf
OUT ?= $(WORK)/$(PDFNAME)
SECTIONS ?=
PHASES ?= inventory,fetch,render,assemble,verify
MAX_DOCS ?=
EXTRA ?=

.PHONY: help bootstrap selftest selftest-full probe pdf e2e-mock lint clean watch ci-validate ci-full

help:
	@echo "make bootstrap      create .venv, install deps, run the offline self-test"
	@echo "make pdf            build the complete offline PDF (needs internet)"
	@echo "make selftest       offline logic test (cleaning, links, TOC, verifier)"
	@echo "make selftest-full  also exercise the real WeasyPrint engine"
	@echo "make probe          read-only report of what the docs portal allows"
	@echo "make lint           byte-compile all python"
	@echo
	@echo "variables: SPACE= PRODUCT= VERSION= SECTIONS= ENGINE=$(ENGINE) WORK=$(WORK)"

bootstrap:
	bash scripts/bootstrap.sh

selftest:
	$(PY) scripts/selftest.py

selftest-full:
	$(PY) scripts/selftest.py --with-render

probe:
	bash scripts/probe_docs_site.sh

pdf: ## one section for a smoke test: make pdf SECTIONS=Getting-started MAX_DOCS=15
	$(PY) scripts/build_docs_pdf.py \
	  --space-path "$(SPACE)" --product "$(PRODUCT)" --version "$(VERSION)" \
	  --workspace "$(WORK)" --out "$(OUT)" --engine "$(ENGINE)" \
	  --phases "$(PHASES)" \
	  $(if $(SECTIONS),--only-sections "$(SECTIONS)",) \
	  $(if $(MAX_DOCS),--max-docs "$(MAX_DOCS)",) $(EXTRA) \
	  --report "$(WORK)/coverage-report.md"
	@echo
	@echo "PDF:      $(OUT)"
	@echo "coverage: $(WORK)/coverage.md"

e2e-mock: ## full pipeline against a fake portal on localhost (no internet needed)
	$(PY) scripts/integration_test.py --full

lint:
	$(PY) -m compileall -q scripts >/dev/null && echo "python syntax OK"

clean:
	rm -rf $(WORK) build

ci-validate: ## arm the CI validation build (small scope) and show the push command
	@cp .build-config.validate.json .build-config.json 2>/dev/null || true
	@echo "git add .build-config.json && git commit -m 'CI: validation build' && git push origin HEAD:$$(git rev-parse --abbrev-ref HEAD)"

ci-full: ## arm the complete build (whole space, published as a GitHub Release)
	@cp .build-config.full.json .build-config.json
	@echo "git add .build-config.json && git commit -m 'CI: full documentation build' && git push origin HEAD:$$(git rev-parse --abbrev-ref HEAD)"

watch: ## follow the CI build's live state
	bash scripts/watch_ci.sh
