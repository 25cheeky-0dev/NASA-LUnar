"""Evidence text retrieval is separate from physical numerical distance."""

import json
import re

from .storage import sha256


def keyword_sources(root, question, limit=10):
    terms = set(re.findall(r"[a-z0-9]+", question.lower()))
    rows = []
    for path in sorted((root / "source_products").glob("*/source.json")):
        document = json.loads(path.read_text())
        for field in (
            "limitations",
            "citation",
            "quality",
            "temporal_coverage",
            "projection",
            "nodata",
        ):
            chunk = json.dumps(document[field], ensure_ascii=False)
            score = len(terms & set(re.findall(r"[a-z0-9]+", chunk.lower())))
            if score:
                rows.append(
                    dict(
                        source_id=document["source_id"],
                        source_url=document["canonical_url"],
                        document_sha256=sha256(path),
                        field=field,
                        text=chunk,
                        score=score,
                        citation=document["citation"],
                        retrieval_model="keyword-set-overlap-v1",
                    )
                )
    return sorted(rows, key=lambda row: (-row["score"], row["source_id"], row["field"]))[:limit]
