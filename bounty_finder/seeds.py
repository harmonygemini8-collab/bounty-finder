"""Curated list of high-star open-source projects that routinely post bounties.

These are established products (mostly on the Algora / Polar ecosystem) where a
merged PR realistically gets reviewed and paid — the opposite of the low-star
"bounty farm" repos that dominate a naive ``label:bounty`` search.

The list is a *seed*, not an allowlist: use ``--curated`` to scope discovery to
these orgs, or ``--min-stars`` to filter any search by repo popularity.
"""

# GitHub org/user logins known for real, paid bounties on high-star repos.
CURATED_ORGS = [
    "calcom",          # cal.com
    "coollabsio",      # coolify
    "twentyhq",        # twenty CRM
    "formbricks",      # formbricks
    "novuhq",          # novu
    "appflowy-io",     # appflowy
    "remotion-dev",    # remotion
    "documenso",       # documenso
    "trigger.dev",     # trigger.dev
    "triggerdotdev",
    "highlight",       # highlight.io
    "unkeyed",         # unkey
    "mudler",          # LocalAI
    "PostHog",         # posthog
    "windmill-labs",   # windmill
    "activepieces",    # activepieces
    "meilisearch",     # meilisearch
    "tolgee",          # tolgee
    "microg",          # GmsCore (user's example)
    "gitroomhq",       # postiz
    "hcengineering",   # huly / tracker
    "zoo-dev",
    "KodyKendall",
]

# Bounty labels seen across the Algora ecosystem (unicode variants matter).
CURATED_LABELS = [
    'label:"💎 Bounty"',
    'label:"💰 Bounty"',
    'label:"💵 Bounty"',
    'label:"🙌 Bounty"',
    "label:bounty",
    'label:"Algora: Up for grabs"',
]
