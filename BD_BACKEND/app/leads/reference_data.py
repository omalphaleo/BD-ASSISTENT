"""Starter reference lists for lead cleaning: free-mail domains, role prefixes, sectors, states.

Needed because import validation (D-069, D-072) and normalization (D-076, D-078) compare
incoming values against fixed lists; keeping them in one constants module means the rules
in normalization.py and validation.py stay free of data, and the seed command can load the
same lists into the industry and state mapping tables.
These are STARTER lists (open items U3 and U6, `[UNRESOLVED]` in docs/plan.md): they are
meant to grow, and making them admin-editable is a later task (M2-B6).
"""

# Free-mail domains: an address here is "personal", never a work email (D-069, D-072).
PERSONAL_EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.uk",
        "yahoo.co.in",
        "ymail.com",
        "hotmail.com",
        "hotmail.co.uk",
        "outlook.com",
        "live.com",
        "msn.com",
        "aol.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "gmx.net",
        "mail.com",
        "zoho.com",
        "yandex.com",
        "rediffmail.com",
    }
)

# Role-address prefixes: a mailbox like info@ reaches a team, not a named person (D-042, D-072).
GENERIC_EMAIL_PREFIXES: frozenset[str] = frozenset(
    {
        "info",
        "sales",
        "support",
        "contact",
        "hello",
        "admin",
        "office",
        "marketing",
        "enquiries",
        "inquiries",
        "help",
        "service",
        "team",
        "mail",
        "hr",
        "jobs",
        "careers",
        "billing",
        "accounts",
        "noreply",
        "no-reply",
    }
)

# Country-code second-level suffixes (acme.co.uk): the company label is the part before them.
SECOND_LEVEL_DOMAIN_SUFFIXES: frozenset[str] = frozenset(
    {"co.uk", "org.uk", "ac.uk", "com.au", "co.nz", "co.in", "co.za", "com.br", "co.jp"}
)

# Value used when a row has no industry (D-070): never quarantined, never mandatory.
UNKNOWN_INDUSTRY = "Unknown"

# The 20 two-digit NAICS sectors: (code, standard name). D-076 maps source industries to these.
NAICS_SECTORS: tuple[tuple[str, str], ...] = (
    ("11", "Agriculture, Forestry, Fishing and Hunting"),
    ("21", "Mining, Quarrying, and Oil and Gas Extraction"),
    ("22", "Utilities"),
    ("23", "Construction"),
    ("31-33", "Manufacturing"),
    ("42", "Wholesale Trade"),
    ("44-45", "Retail Trade"),
    ("48-49", "Transportation and Warehousing"),
    ("51", "Information"),
    ("52", "Finance and Insurance"),
    ("53", "Real Estate and Rental and Leasing"),
    ("54", "Professional, Scientific, and Technical Services"),
    ("55", "Management of Companies and Enterprises"),
    ("56", "Administrative and Support and Waste Management and Remediation Services"),
    ("61", "Educational Services"),
    ("62", "Health Care and Social Assistance"),
    ("71", "Arts, Entertainment, and Recreation"),
    ("72", "Accommodation and Food Services"),
    ("81", "Other Services (except Public Administration)"),
    ("92", "Public Administration"),
)

# Common source wordings (Apollo/LinkedIn style) mapped to a NAICS sector name above.
# Keys are lowercase; values must be names from NAICS_SECTORS (a test enforces this).
INDUSTRY_ALIASES: dict[str, str] = {
    "software": "Information",
    "computer software": "Information",
    "information technology": "Information",
    "information technology and services": "Information",
    "internet": "Information",
    "telecommunications": "Information",
    "financial services": "Finance and Insurance",
    "banking": "Finance and Insurance",
    "insurance": "Finance and Insurance",
    "hospital & health care": "Health Care and Social Assistance",
    "healthcare": "Health Care and Social Assistance",
    "consulting": "Professional, Scientific, and Technical Services",
    "management consulting": "Professional, Scientific, and Technical Services",
    "marketing and advertising": "Professional, Scientific, and Technical Services",
    "legal services": "Professional, Scientific, and Technical Services",
    "education": "Educational Services",
    "higher education": "Educational Services",
    "retail": "Retail Trade",
    "real estate": "Real Estate and Rental and Leasing",
    "manufacturing": "Manufacturing",
    "construction": "Construction",
    "government administration": "Public Administration",
}

UNITED_STATES = "United States"

# Country wordings seen in exports mapped to one standard name; keys are lowercase (D-078).
COUNTRY_ALIASES: dict[str, str] = {
    "us": UNITED_STATES,
    "u.s.": UNITED_STATES,
    "usa": UNITED_STATES,
    "u.s.a.": UNITED_STATES,
    "united states": UNITED_STATES,
    "united states of america": UNITED_STATES,
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "united kingdom": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "uae": "United Arab Emirates",
    "united arab emirates": "United Arab Emirates",
}

# US states and DC: abbreviation -> standard name (D-078). Other countries are kept as given.
US_STATES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
