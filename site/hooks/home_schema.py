"""Homepage Organization and SoftwareApplication JSON-LD.

The company behind GitGrit is Praktical (https://praktical.dev). Pricing is
not published, and the hosted product is not free, so this graph has no
offers, price, or isAccessibleForFree field.
"""

import json

ORG_ID = "https://praktical.dev/#organization"

GRAPH = {
    "@context": "https://schema.org",
    "@graph": [
        {
            "@type": "Organization",
            "@id": ORG_ID,
            "name": "Praktical",
            "url": "https://praktical.dev/",
            "logo": "https://praktical.dev/logo.png",
        },
        {
            "@type": "SoftwareApplication",
            "name": "GitGrit",
            "url": "https://gitgrit.dev/",
            "applicationCategory": "DeveloperApplication",
            "operatingSystem": "Web, self-hosted (Linux)",
            "license": "https://opensource.org/licenses/MIT",
            "description": (
                "Open-source engineering standards platform. Turns engineering standards into code, "
                "checks every GitHub and GitLab repository on every push, and grades each repository from A+ to F."
            ),
            "publisher": {"@id": ORG_ID},
        },
    ],
}


def on_post_page(output, page, config):
    if page.file.src_uri != "index.md":
        return output
    script = (
        '<script type="application/ld+json">'
        + json.dumps(GRAPH, ensure_ascii=False)
        + "</script>"
    )
    return output.replace("</head>", script + "\n</head>", 1)
