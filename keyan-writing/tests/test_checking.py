from keyan.checking import _empty_headings


def test_empty_heading_allows_container_with_child_heading():
    text = "# System\n\n## Module\n\nModule body.\n"
    assert _empty_headings(text) == []


def test_empty_heading_still_reports_leaf_without_body():
    text = "# System\n\n## Empty leaf\n\n## Next leaf\n\nBody.\n"
    assert _empty_headings(text) == ["Empty leaf"]
