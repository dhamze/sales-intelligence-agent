"""Country matching across the spellings people and the AI actually use.

Users type "DE", "Germany" or "deutschland"; the AI profile says "Germany". To compare them, every
spelling is reduced to an ISO 3166-1 alpha-2 code where we know one; unknown spellings fall back
to a case-insensitive comparison of the text itself.
"""

import unicodedata

# ISO 3166-1 alpha-2 code: English short name, then common alternative spellings.
_TABLE = """
AD Andorra|AE United Arab Emirates;UAE|AF Afghanistan|AG Antigua and Barbuda|AL Albania
AM Armenia|AO Angola|AR Argentina|AT Austria;Osterreich|AU Australia|AZ Azerbaijan
BA Bosnia and Herzegovina|BB Barbados|BD Bangladesh|BE Belgium;Belgie;Belgique|BF Burkina Faso
BG Bulgaria|BH Bahrain|BI Burundi|BJ Benin|BN Brunei|BO Bolivia|BR Brazil;Brasil|BS Bahamas
BT Bhutan|BW Botswana|BY Belarus|BZ Belize|CA Canada|CD Democratic Republic of the Congo;DR Congo
CF Central African Republic|CG Republic of the Congo;Congo|CH Switzerland;Schweiz;Suisse
CI Ivory Coast;Cote d'Ivoire|CL Chile|CM Cameroon|CN China;PRC|CO Colombia|CR Costa Rica|CU Cuba
CV Cape Verde;Cabo Verde|CY Cyprus|CZ Czechia;Czech Republic|DE Germany;Deutschland|DJ Djibouti
DK Denmark;Danmark|DM Dominica|DO Dominican Republic|DZ Algeria|EC Ecuador|EE Estonia|EG Egypt
ER Eritrea|ES Spain;Espana|ET Ethiopia|FI Finland;Suomi|FJ Fiji|FR France|GA Gabon
GB United Kingdom;UK;Great Britain;Britain;England;Scotland;Wales;Northern Ireland
GD Grenada|GE Georgia|GH Ghana|GM Gambia|GN Guinea|GQ Equatorial Guinea|GR Greece
GT Guatemala|GW Guinea-Bissau|GY Guyana|HK Hong Kong|HN Honduras|HR Croatia;Hrvatska|HT Haiti
HU Hungary|ID Indonesia|IE Ireland|IL Israel|IN India|IQ Iraq|IR Iran|IS Iceland|IT Italy;Italia
JM Jamaica|JO Jordan|JP Japan|KE Kenya|KG Kyrgyzstan|KH Cambodia|KR South Korea;Korea
KW Kuwait|KZ Kazakhstan|LA Laos|LB Lebanon|LI Liechtenstein|LK Sri Lanka|LR Liberia|LS Lesotho
LT Lithuania|LU Luxembourg|LV Latvia|LY Libya|MA Morocco|MC Monaco|MD Moldova|ME Montenegro
MG Madagascar|MK North Macedonia;Macedonia|ML Mali|MM Myanmar;Burma|MN Mongolia|MO Macau;Macao
MT Malta|MU Mauritius|MV Maldives|MW Malawi|MX Mexico|MY Malaysia|MZ Mozambique|NA Namibia
NE Niger|NG Nigeria|NI Nicaragua|NL Netherlands;Holland;The Netherlands;Nederland|NO Norway;Norge
NP Nepal|NZ New Zealand|OM Oman|PA Panama|PE Peru|PG Papua New Guinea|PH Philippines
PK Pakistan|PL Poland;Polska|PR Puerto Rico|PS Palestine|PT Portugal|PY Paraguay|QA Qatar
RO Romania|RS Serbia|RU Russia;Russian Federation|RW Rwanda|SA Saudi Arabia|SC Seychelles
SD Sudan|SE Sweden;Sverige|SG Singapore|SI Slovenia|SK Slovakia|SL Sierra Leone|SM San Marino
SN Senegal|SO Somalia|SR Suriname|SV El Salvador|SY Syria|SZ Eswatini;Swaziland|TD Chad|TG Togo
TH Thailand|TJ Tajikistan|TN Tunisia|TR Turkey;Turkiye|TT Trinidad and Tobago|TW Taiwan
TZ Tanzania|UA Ukraine|UG Uganda
US United States;USA;U.S.;U.S.A.;United States of America;America
UY Uruguay|UZ Uzbekistan|VA Vatican City;Holy See|VE Venezuela|VN Vietnam;Viet Nam|YE Yemen
ZA South Africa|ZM Zambia|ZW Zimbabwe
"""

# Three-letter codes that commonly appear in CRM exports.
_ALPHA3 = {
    "USA": "US", "GBR": "GB", "DEU": "DE", "FRA": "FR", "AUT": "AT", "CHE": "CH", "NLD": "NL",
    "BEL": "BE", "ESP": "ES", "ITA": "IT", "IRL": "IE", "SWE": "SE", "NOR": "NO", "DNK": "DK",
    "FIN": "FI", "POL": "PL", "CAN": "CA", "AUS": "AU", "IND": "IN", "JPN": "JP", "CHN": "CN",
    "BRA": "BR", "MEX": "MX", "SGP": "SG", "ISR": "IL", "PRT": "PT", "CZE": "CZ", "LUX": "LU",
}  # fmt: skip


def _key(text: str) -> str:
    """Lowercase, accents removed, punctuation and extra spaces dropped."""
    decomposed = unicodedata.normalize("NFKD", text)
    letters = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = "".join(ch if ch.isalnum() else " " for ch in letters.casefold())
    return " ".join(cleaned.split())


def _build() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for entry in _TABLE.replace("\n", "|").split("|"):
        entry = entry.strip()
        if not entry:
            continue
        code, names = entry.split(" ", 1)
        lookup[_key(code)] = code
        for name in names.split(";"):
            lookup[_key(name)] = code
    for alpha3, code in _ALPHA3.items():
        lookup.setdefault(_key(alpha3), code)
    return lookup


_LOOKUP = _build()


def canonical_country(text: str) -> str:
    """The ISO alpha-2 code when known, otherwise the normalised text itself."""
    key = _key(text)
    return _LOOKUP.get(key, key)


def same_country(a: str, b: str) -> bool:
    return canonical_country(a) == canonical_country(b)
