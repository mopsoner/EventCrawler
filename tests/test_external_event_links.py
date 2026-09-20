from pathlib import Path


def test_external_event_links_open_safely_in_a_new_tab():
    templates = Path(__file__).parents[1] / "templates"
    expected_links = {
        "event.html": '<a href="{{ event.event_url }}" target="_blank" rel="noopener noreferrer">',
        "failures.html": '<a href="{{ r.event_url }}" target="_blank" rel="noopener noreferrer">',
        "free.html": '<a href="{{ r.event_url }}" class="text-link" target="_blank" rel="noopener noreferrer">',
        "tickets.html": '<a href="{{ r.event_url }}" class="text-link" target="_blank" rel="noopener noreferrer">',
    }

    for filename, link in expected_links.items():
        assert link in (templates / filename).read_text(encoding="utf-8"), filename
