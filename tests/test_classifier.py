"""Tests for the document classifier."""

from antbot.scout.classifier import Classifier, ClassifyResult


def test_keyword_match_finance():
    c = Classifier()
    result = c.classify_text("Invoice #1234. Payment due: $450. Tax: $45.")
    assert result.category == "Finance"
    assert result.method == "keyword"
    assert result.confidence > 0


def test_keyword_match_contract():
    c = Classifier()
    result = c.classify_text("This agreement is entered into by the parties hereby. Termination clause applies.")
    assert result.category == "Contracts"


def test_keyword_match_technical():
    c = Classifier()
    result = c.classify_text("API endpoint specification: POST /v1/users. Schema documentation for the interface.")
    assert result.category == "Technical"


def test_keyword_match_notes():
    c = Classifier()
    result = c.classify_text("Meeting notes from Monday. Action items: review PR, update agenda.")
    assert result.category == "Notes"


def test_keyword_match_data():
    c = Classifier()
    result = c.classify_text("Dataset export with 50000 records across 12 columns. CSV format.")
    assert result.category == "Data"


def test_no_match_returns_unsorted():
    c = Classifier()
    result = c.classify_text("random gibberish xyzzy plugh")
    assert result.category == "Unsorted"
    assert result.method == "default"


def test_file_extension_fallback():
    c = Classifier()
    result = c.classify_file("/path/to/file.csv")
    assert result.category == "Data"

    result = c.classify_file("/path/to/notes.md")
    assert result.category == "Notes"

    result = c.classify_file("/path/to/report.pdf")
    assert result.category == "Unsorted"  # PDFs need content analysis


def test_custom_categories():
    custom = {
        "Recipes": ["ingredient", "tablespoon", "bake", "oven"],
    }
    c = Classifier(categories=custom)
    result = c.classify_text("Add 2 tablespoon of butter. Bake in oven at 350F.")
    assert result.category == "Recipes"


def test_confidence_reflects_match_quality():
    c = Classifier()
    # Strong match (many keywords)
    strong = c.classify_text("invoice receipt payment tax statement balance due amount billing")
    # Weak match (one keyword)
    weak = c.classify_text("just a payment note")
    assert strong.confidence > weak.confidence
