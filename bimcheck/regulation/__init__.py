"""S1 regulation pipeline: PDF redline -> articles.json -> rules catalogue.

    from bimcheck.regulation import load_rules, load_articles, get_rule, validate_catalogue
"""
from .catalogue import (  # noqa: F401
    ALLOWED_CUSTOM_IDS,
    MEASURES_BY_KIND,
    apply_overrides,
    get_article,
    get_rule,
    load_articles,
    load_rules,
    make_rule_id,
    merge_catalogues,
    rules_by_automation,
    validate_catalogue,
)
