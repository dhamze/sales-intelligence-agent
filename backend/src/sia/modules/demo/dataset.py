"""The sample dataset: fictional companies, their website text and contacts, plus an ICP.

Everything here is invented (names, domains under .example, people), so the public demo shows
realistic data without copying anyone's website or personal details. `.example` domains can
never resolve, so nothing here can make the app contact a real site.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SamplePage:
    path: str
    title: str
    text: str


@dataclass(frozen=True)
class SampleContact:
    first_name: str
    last_name: str
    title: str


@dataclass(frozen=True)
class SampleCompany:
    name: str
    domain: str
    industry: str | None
    employee_count: int | None
    country: str | None
    city: str | None
    pages: list[SamplePage]
    contacts: list[SampleContact] = field(default_factory=list)

    @property
    def website(self) -> str:
        return f"https://{self.domain}/"

    def page_url(self, page: SamplePage) -> str:
        return f"https://{self.domain}/{page.path}"


def _p(path: str, title: str, text: str) -> SamplePage:
    return SamplePage(path, title, " ".join(text.split()))


def _c(first: str, last: str, title: str) -> SampleContact:
    return SampleContact(first, last, title)


SAMPLE_ICP: dict[str, Any] = {
    "criteria": [
        {"kind": "industry", "industries": ["Software", "Fintech"], "importance": 5},
        {"kind": "size", "min_employees": 50, "max_employees": 1000, "importance": 3},
        {"kind": "country", "countries": ["DE", "AT", "CH", "NL"], "importance": 3},
        {"kind": "keywords", "keywords": ["automation", "payments", "finance teams"],
         "importance": 2},
        {"kind": "has_contacts", "min_contacts": 1, "importance": 2},
    ]
}  # fmt: skip

SAMPLE_COMPANIES: list[SampleCompany] = [
    SampleCompany(
        "Northwind Ledger", "northwind-ledger.example", "Fintech", 180, "DE", "Hamburg",
        [
            _p("", "Northwind Ledger", """Northwind Ledger automates accounts payable for
               mid-sized manufacturers. Our platform reads supplier invoices, matches them to
               purchase orders and schedules payments. Finance teams close the month four days
               faster on average."""),
            _p("careers", "Careers", """We are hiring 12 engineers in Hamburg to build our new
               treasury module. We recently opened an office in Vienna to serve customers in
               Austria."""),
        ],
        [_c("Lena", "Hartmann", "CFO"), _c("Jonas", "Weber", "Head of Accounts Payable")],
    ),
    SampleCompany(
        "Alpenfold Payroll", "alpenfold.example", "Software", 420, "AT", "Vienna",
        [
            _p("", "Alpenfold", """Alpenfold runs payroll for companies with 50 to 2,000
               employees in Austria, Germany and Switzerland. Payslips, tax filings and social
               security reports are generated automatically every month."""),
            _p("news", "News", """Alpenfold has started migrating its customers from on-premise
               installations to a new cloud platform, with completion planned for 2027."""),
        ],
        [_c("Miriam", "Gruber", "COO")],
    ),
    SampleCompany(
        "Kestrel Treasury", "kestrel-treasury.example", "Fintech", 95, "CH", "Zurich",
        [
            _p("", "Kestrel Treasury", """Kestrel Treasury gives finance teams a live view of
               cash across all bank accounts. The software forecasts liquidity for the next 13
               weeks and flags payments that would breach limits."""),
        ],
    ),
    SampleCompany(
        "Dunmore Logistics", "dunmore-logistics.example", "Logistics & Transportation", 2600,
        "NL", "Rotterdam",
        [
            _p("", "Dunmore Logistics", """Dunmore Logistics operates container terminals and
               inland barge services between Rotterdam and the Rhine valley. More than 40,000
               containers move through our terminals every month."""),
            _p("about", "About", """Our finance team processes over 9,000 carrier invoices a
               month and is looking at automation to reduce manual checks."""),
        ],
        [_c("Pieter", "de Vries", "Finance Director")],
    ),
    SampleCompany(
        "Brightwater Health", "brightwater-health.example", "Healthcare", 760, "DE", "Cologne",
        [
            _p("", "Brightwater Health", """Brightwater Health runs 22 outpatient rehabilitation
               centres in North Rhine-Westphalia. Patients book appointments online and see a
               therapist within 48 hours."""),
        ],
    ),
    SampleCompany(
        "Quillmark Software", "quillmark.example", "Software", 140, "DE", "Leipzig",
        [
            _p("", "Quillmark", """Quillmark builds contract management software for legal
               and procurement teams. Contracts are tagged automatically and renewal dates
               trigger reminders."""),
            _p("partners", "Partners", """Quillmark integrates with the leading ERP systems and
               plans to add automated payments for supplier contracts this year."""),
        ],
        [_c("Felix", "Braun", "VP Sales"), _c("Sara", "Koch", "Head of Partnerships")],
    ),
    SampleCompany(
        "Ostara Energy", "ostara-energy.example", "Energy & Utilities", 3100, "DE", "Munich",
        [
            _p("", "Ostara Energy", """Ostara Energy builds and operates solar parks in
               southern Germany with a combined capacity of 1.4 gigawatts."""),
        ],
    ),
    SampleCompany(
        "Tidewell Insurance Tech", "tidewell.example", "Fintech", 65, "NL", "Amsterdam",
        [
            _p("", "Tidewell", """Tidewell provides claims automation software to mid-sized
               insurers. Claims are triaged in seconds and simple claims are paid out
               automatically."""),
            _p("careers", "Careers", """Tidewell is hiring its first finance operations manager
               to scale billing and payments as the customer base doubles."""),
        ],
        [_c("Noor", "Bakker", "CEO")],
    ),
    SampleCompany(
        "Fernhill Retail Group", "fernhill-retail.example", "Retail & E-commerce", 8500, "GB",
        "Manchester",
        [
            _p("", "Fernhill", """Fernhill Retail Group runs 140 home and garden stores across
               the United Kingdom and an online shop with next-day delivery."""),
        ],
    ),
    SampleCompany(
        "Glacier Analytics", "glacier-analytics.example", "Software", 38, "CH", "Basel",
        [
            _p("", "Glacier Analytics", """Glacier Analytics helps pharmaceutical companies
               analyse clinical trial data. Our statisticians and software engineers work from
               Basel."""),
        ],
    ),
    SampleCompany(
        "Halcyon Pay", "halcyon-pay.example", "Fintech", 310, "DE", "Berlin",
        [
            _p("", "Halcyon Pay", """Halcyon Pay processes card and instant payments for
               online marketplaces. Marketplaces split each payment between sellers
               automatically and pay out daily."""),
            _p("news", "News", """Halcyon Pay received an e-money licence from the German
               financial regulator and is expanding into the Netherlands."""),
        ],
        [_c("Paul", "Schneider", "Head of Finance"), _c("Aylin", "Demir", "Payments Lead")],
    ),
    SampleCompany(
        "Mosswood Manufacturing", "mosswood.example", "Manufacturing", 540, "AT", "Linz",
        [
            _p("", "Mosswood", """Mosswood Manufacturing makes precision aluminium parts for
               the automotive and aerospace industries in two plants in Upper Austria."""),
            _p("careers", "Careers", """Our finance team is introducing automation for supplier
               invoices and is hiring an ERP specialist."""),
        ],
    ),
]  # fmt: skip
