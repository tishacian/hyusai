# ─────────────────────────────────────────────────────────────
# fiche-hosting-ovh-andritz — build pipeline
# ─────────────────────────────────────────────────────────────
#
# Generates fiche-hosting-ovh-andritz.docx from main.md using the
# shared CarakAI / METROPOLIS Pandoc toolchain (Datategy reference.docx
# template, no-hr lua filter, table style post-processing).
#
# Prerequisites:
#   brew install pandoc         (>= 2.19)
#   pip install python-docx     (only if rebuilding the reference)
#
# Usage (from this directory):
#   make              # Build fiche-hosting-ovh-andritz.docx
#   make doc          # Same
#   make deck         # Build ANDRITZ-hosting-compliance-deck.pptx (English, Visio)
#   make clean        # Remove generated docx
#   make clean-deck   # Remove generated pptx
#
# Override toolchain location if needed:
#   make TOOLCHAIN_ROOT=/path/to/project-carakai/doc
# ─────────────────────────────────────────────────────────────

TOOLCHAIN_ROOT ?= ../../../../AO/SGP/CarakAI/project-carakai/doc
BUILD_SHARED   := $(TOOLCHAIN_ROOT)/build
BUILD_LOCAL    := build

PANDOC       := pandoc
PYTHON       := python3
REFERENCE_SRC := $(BUILD_SHARED)/reference.docx
REFERENCE     := $(BUILD_LOCAL)/reference-andritz.docx
FILTERS_DIR   := $(BUILD_SHARED)/filters

PANDOC_FLAGS := --reference-doc=$(REFERENCE) \
                --lua-filter=$(FILTERS_DIR)/no-hr.lua \
                -f markdown+pipe_tables+grid_tables+multiline_tables \
                --toc --toc-depth=3

TABLE_STYLE  := TableauGrille4-Accentuation1

.PHONY: all doc deck clean clean-deck reference clean-reference

DOC_SRC := main.md
DOC_OUT := fiche-hosting-ovh-andritz.docx

DECK_SRC := ANDRITZ-hosting-compliance-deck.md
DECK_OUT := ANDRITZ-hosting-compliance-deck.pptx

all: doc

doc: $(DOC_OUT)

deck: $(DECK_OUT)

$(DECK_OUT): $(DECK_SRC)
	@echo "Building $(DECK_OUT) ..."
	$(PANDOC) -f markdown+pipe_tables -t pptx -o $@ $<
	@echo "OK  $(DECK_OUT)"

reference: $(REFERENCE)

$(REFERENCE): $(REFERENCE_SRC) $(BUILD_LOCAL)/strip-explolab.py
	@echo "Generating Datategy-only reference template ..."
	$(PYTHON) $(BUILD_LOCAL)/strip-explolab.py $(REFERENCE_SRC) $(REFERENCE)

$(DOC_OUT): $(DOC_SRC) $(REFERENCE) $(FILTERS_DIR)/no-hr.lua
	@echo "Building $(DOC_OUT) ..."
	$(PANDOC) $(PANDOC_FLAGS) -o $@ $<
	$(PYTHON) $(BUILD_SHARED)/fix-table-style.py $@ --style $(TABLE_STYLE)
	@echo "OK  $(DOC_OUT)"

clean:
	rm -f $(DOC_OUT)

clean-deck:
	rm -f $(DECK_OUT)

clean-reference:
	rm -f $(REFERENCE)
