PY ?= .venv/bin/python
SPACE ?= Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263
PRODUCT ?= BMC Helix ITSM
VERSION ?= 26.3
WORK ?= /tmp/helix
ENGINE ?= weasyprint
OUT ?= $(WORK)/$(subst:,-,$(PRODUCT))-$(VERSION)-complete.pdf
SECTIONS ?=

.PHONY: help bootstrap selftest selftest-full probe pdf lint clean

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

pdf:
	$(PY) scripts/build_docs_pdf.py \
	  --space-path "$(SPACE)" --product "$(PRODUCT)" --version "$(VERSION)" \
	  --workspace "$(WORK)" --out "$(OUT)" --engine "$(ENGINE)" \
	  $(if $(SECTIONS),--only-sections "$(SECTIONS)",) \
	  --report "$(WORK)/coverage-report.md"
	@echo
	@echo "PDF:      $(OUT)"
	@echo "coverage: $(WORK)/coverage.md"

lint:
	$(PY) -m compileall -q scripts >/dev/null && echo "python syntax OK"

clean:
	rm -rf $(WORK) build
