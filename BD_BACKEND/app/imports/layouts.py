"""Built-in column-header aliases (Apollo and common external sources) and header matching.

Needed so a mapping can be suggested for a new file without anyone configuring it first: the
Apollo export has a known column list (Q-DATA-01), and other providers use similar but not
identical names. Headers are matched by their normalized text, never by column position
(D-040). The three predefined BD layouts are still unresolved (U2) and are not defined here;
saved admin profiles (SourceProfile.mapping_defaults) take priority over these built-ins.
"""

import re

from app.leads.contracts import TARGET_FIELDS_BY_KEY

# Anything that is not a letter, digit or "#" (as in "# Employees") separates words.
_SEPARATORS = re.compile(r"[^0-9a-z#]+")

# Apollo export header -> target key (Q-DATA-01). Apollo Record Id, Subsidiary of and
# Number of Retail Locations are deliberately absent: they stay in raw_rows only (Q-IMPORT-11).
APOLLO_ALIASES: dict[str, str] = {
    "First Name": "first_name",
    "Last Name": "last_name",
    "Title": "title",
    "Company Name": "company_name",
    "Company Name for Emails": "company_name_for_emails",
    "Email": "email",
    "Email Status": "email_status",
    "Primary Email Source": "email_source",
    "Primary Email Verification Source": "email_verification_source",
    "Email Confidence": "email_confidence",
    "Primary Email Catch-all Status": "email_catch_all_status",
    "Primary Email Last Verified At": "email_last_verified_at",
    "Secondary Email": "secondary_email",
    "Secondary Email Status": "secondary_email_status",
    "Secondary Email Source": "secondary_email_source",
    "Secondary Email Verification Source": "secondary_email_verification_source",
    "Tertiary Email": "tertiary_email",
    "Tertiary Email Status": "tertiary_email_status",
    "Tertiary Email Source": "tertiary_email_source",
    "Tertiary Email Verification Source": "tertiary_email_verification_source",
    "Seniority": "seniority",
    "Departments": "department",
    "Sub Departments": "sub_department",
    "Contact Owner": "owner_name",
    "Account Owner": "account_owner_name",
    "Work Direct Phone": "phone_work_direct",
    "Home Phone": "phone_home",
    "Mobile Phone": "phone_mobile",
    "Corporate Phone": "phone_corporate",
    "Other Phone": "phone_other",
    "Company Phone": "company_phone",
    "Do Not Call": "do_not_call",
    "Stage": "source_stage",
    "Lists": "lists",
    "Last Contacted": "last_contacted_at",
    "# Employees": "employee_count",
    "Industry": "industry",
    "Keywords": "keywords",
    "Person Linkedin Url": "linkedin_url",
    "Website": "website",
    "Company Linkedin Url": "company_linkedin_url",
    "Facebook Url": "company_facebook_url",
    "Twitter Url": "company_twitter_url",
    "City": "city",
    "State": "state",
    "Country": "country",
    "Company Address": "company_address",
    "Company City": "company_city",
    "Company State": "company_state",
    "Company Country": "company_country",
    "Technologies": "technologies",
    "Annual Revenue": "annual_revenue",
    "Total Funding": "total_funding",
    "Latest Funding": "latest_funding_round_type",
    "Latest Funding Amount": "latest_funding_amount",
    "Last Raised At": "latest_funding_date",
    "Email Sent": "email_sent",
    "Email Open": "email_opened",
    "Email Bounced": "email_bounced",
    "Replied": "replied",
    "Demoed": "demoed",
    "SIC Codes": "sic",
    "NAICS Codes": "naics",
    "Apollo Contact Id": "source_record_id",
    "Apollo Account Id": "company_source_id",
    "Primary Intent Topic": "intent_primary_topic",
    "Primary Intent Score": "intent_primary_score",
    "Secondary Intent Topic": "intent_secondary_topic",
    "Secondary Intent Score": "intent_secondary_score",
    "Qualify Contact": "qualify_contact",
}

# Names other providers and hand-made spreadsheets commonly use. Kept short on purpose: a
# header not listed here is simply left unmapped for the user to assign, never guessed.
GENERIC_ALIASES: dict[str, str] = {
    "Email Address": "email",
    "E-mail": "email",
    "E-mail Address": "email",
    "Work Email": "email",
    "Business Email": "email",
    "Given Name": "first_name",
    "Firstname": "first_name",
    "Surname": "last_name",
    "Family Name": "last_name",
    "Lastname": "last_name",
    "Job Title": "title",
    "Position": "title",
    "Company": "company_name",
    "Organization": "company_name",
    "Organisation": "company_name",
    "Company Website": "website",
    "Domain": "website",
    "LinkedIn": "linkedin_url",
    "LinkedIn URL": "linkedin_url",
    "LinkedIn Profile": "linkedin_url",
    "Phone": "phone_work_direct",
    "Mobile": "phone_mobile",
    "Employees": "employee_count",
    "Number of Employees": "employee_count",
    "Revenue": "annual_revenue",
    "Sector": "industry",
}


def normalize_header(header: str) -> str:
    """Reduce a header to the text used for matching: lowercase words joined by one space.

    "E-mail Address", "e mail  address" and "E-MAIL ADDRESS" all normalize to the same value.
    """
    return _SEPARATORS.sub(" ", header.casefold()).strip()


def _build_alias_lookup(*tables: dict[str, str]) -> dict[str, str]:
    """Normalize the header of every alias table into one lookup (earlier tables win).

    Raises:
        ValueError: If an alias points at a key that is not in the field registry, which
            would silently produce a mapping W2 cannot read.
    """
    lookup: dict[str, str] = {}
    for table in tables:
        for header, key in table.items():
            if key not in TARGET_FIELDS_BY_KEY:
                raise ValueError(f"alias {header!r} points at unknown field {key!r}")
            lookup.setdefault(normalize_header(header), key)
    return lookup


# Normalized header -> target key. Apollo names come first so they win over generic ones.
BUILTIN_ALIAS_LOOKUP: dict[str, str] = _build_alias_lookup(APOLLO_ALIASES, GENERIC_ALIASES)
