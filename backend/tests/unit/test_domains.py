import pytest

from sia.modules.companies.domains import InvalidDomainError, normalize_domain, normalize_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("acme.com", "acme.com"),
        ("ACME.COM", "acme.com"),
        ("  www.acme.com  ", "acme.com"),
        ("https://www.acme.com/about?x=1#team", "acme.com"),
        ("http://user:pw@shop.acme.com:8080/cart", "acme.com"),
        ("https://WWW.Blog.Acme.co.uk/", "acme.co.uk"),  # multi-part public suffix
        ("acme.com.", "acme.com"),  # trailing dot (fully-qualified form)
        ("münchen.de", "xn--mnchen-3ya.de"),  # internationalised -> ASCII form
        ("xn--mnchen-3ya.de", "xn--mnchen-3ya.de"),
        ("foo.github.io", "foo.github.io"),  # hosted site is its own company
        ("bar.foo.github.io", "foo.github.io"),
    ],
)
def test_normalize_domain(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "localhost",
        "192.168.1.1",
        "http://[::1]/",
        "acme",  # no public suffix
        "acme.notarealtld",
        "acme corp.com",  # whitespace
        "-acme.com",
        "acme..com",
        "a" * 64 + ".com",  # label longer than 63 characters
        "https://" + "a" * 2100 + ".com",
    ],
)
def test_invalid_domains_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidDomainError):
        normalize_domain(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("acme.com", "https://acme.com/"),
        ("http://Acme.com/About?x=1#frag", "http://acme.com/About?x=1"),
        ("https://www.linkedin.com/in/jane-doe", "https://www.linkedin.com/in/jane-doe"),
        ("https://acme.com:8443/x", "https://acme.com:8443/x"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw", ["javascript:alert(1)", "ftp://acme.com/file", "file:///etc/passwd", "http://10.0.0.1/"]
)
def test_dangerous_or_private_urls_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidDomainError):
        normalize_url(raw)
