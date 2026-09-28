"""The map opens a node's url on click, so only plain http(s) links are kept."""
from app.domain.architecture.resolve import resolve_topology
from app.domain.architecture.topology import (
    INBOUND,
    OUTBOUND,
    ComponentDecl,
    Evidence,
    ExternalLink,
    RepositoryTopology,
    safe_url,
)


def test_safe_url_keeps_only_http_links():
    assert safe_url(" https://stripe.com ") == "https://stripe.com"
    assert safe_url("http://x.io") == "http://x.io"
    assert safe_url("https://x.io/" + "a" * 3000) == ("https://x.io/" + "a" * 3000)[:2048]
    for bad in ("javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,x", "//evil.io", "", None):
        assert safe_url(bad) == ""


def test_resolve_topology_drops_unsafe_external_urls():
    topology = RepositoryTopology(
        components=(ComponentDecl(path="", name="shop"),),
        externals=(
            ExternalLink("", "Stripe", OUTBOUND, url="https://stripe.com"),
            ExternalLink("", "Evil", INBOUND, url="javascript:alert(1)"),
        ),
        evidence=Evidence(tree_size=1, files_read=("README.md",)),
    )

    resolved = resolve_topology(topology, roster=[], this_repo="acme/shop")

    assert {e.name: e.url for e in resolved.externals} == {"Stripe": "https://stripe.com", "Evil": ""}
