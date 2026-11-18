"""MkDocs hook: add FAQPage structured data to pages with a "## FAQ" section.

Use case and compare pages end with an FAQ (### question, then answer
paragraphs). This turns that section into schema.org FAQPage JSON-LD in the
page head, so search engines and AI answer engines can read the questions and
answers directly. The page text stays the single source: nothing to keep in
sync by hand.
"""

import html
import json
import re

SECTIONS = ("use-cases/", "compare/")

_FAQ = re.compile(r'<h2 id="faq">.*?</h2>(.*?)(?=<h2|</article>)', re.S)
_QA = re.compile(r"<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|$)", re.S)
_TAG = re.compile(r"<[^>]+>")


def _text(fragment):
    fragment = re.sub(r'<a class="headerlink".*?</a>', "", fragment, flags=re.S)
    return html.unescape(_TAG.sub("", fragment)).strip()


def on_post_page(output, page, config):
    if not page.file.src_uri.startswith(SECTIONS):
        return output
    faq = _FAQ.search(output)
    if not faq:
        return output
    entities = []
    for question, answer in _QA.findall(faq.group(1)):
        q, a = _text(question), " ".join(_text(answer).split())
        if q and a:
            entities.append(
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            )
    if not entities:
        return output
    data = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": entities}
    script = '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>"
    return output.replace("</head>", script + "\n</head>", 1)
