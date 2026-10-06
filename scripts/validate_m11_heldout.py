from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

REQUIRED_MODALITIES = {"web", "academic", "software", "document_table", "audio", "video"}
REQUIRED_TAGS = {
    "conflict",
    "insufficient_evidence",
    "date_window",
    "numeric_unit",
    "multilingual",
    "authorization_sensitive",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the independently authored M11 held-out manifest boundary"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--minimum-cases", type=int, default=100)
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    failures: list[str] = []

    authoring = payload.get("authoring") if isinstance(payload, dict) else None
    if (
        not isinstance(authoring, dict)
        or authoring.get("independent_from_implementation") is not True
    ):
        failures.append("authoring.independent_from_implementation must be true")
    if (
        not isinstance(payload.get("license_and_rights"), str)
        or not payload["license_and_rights"].strip()
    ):
        failures.append("license_and_rights must be documented")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        failures.append("cases must be a list")
        cases = []
    if len(cases) < args.minimum_cases:
        failures.append(f"held-out set has {len(cases)} cases; need >= {args.minimum_cases}")

    ids: list[str] = []
    modalities: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            failures.append(f"case[{index}] must be an object")
            continue
        case_id = case.get("id")
        query = case.get("query")
        modality = case.get("modality")
        case_tags = case.get("tags")
        facets = case.get("required_facets")
        if not isinstance(case_id, str) or not case_id.strip():
            failures.append(f"case[{index}] has no id")
        else:
            ids.append(case_id)
        if not isinstance(query, str) or not query.strip():
            failures.append(f"case[{index}] has no query")
        if modality not in REQUIRED_MODALITIES:
            failures.append(f"case[{index}] has unsupported modality {modality!r}")
        else:
            modalities[modality] += 1
        if not isinstance(case_tags, list) or any(not isinstance(tag, str) for tag in case_tags):
            failures.append(f"case[{index}] tags must be strings")
        else:
            tags.update(case_tags)
        if (
            not isinstance(facets, list)
            or not facets
            or any(not isinstance(facet, str) or not facet.strip() for facet in facets)
        ):
            failures.append(f"case[{index}] required_facets must be a non-empty string list")
        if not isinstance(case.get("annotation_ref"), str) or not case["annotation_ref"].strip():
            failures.append(f"case[{index}] annotation_ref is required")

    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicates:
        failures.append(f"duplicate case ids: {', '.join(duplicates[:10])}")
    missing_modalities = sorted(REQUIRED_MODALITIES - set(modalities))
    if missing_modalities:
        failures.append(f"missing modality slices: {', '.join(missing_modalities)}")
    missing_tags = sorted(REQUIRED_TAGS - set(tags))
    if missing_tags:
        failures.append(f"missing required slices/tags: {', '.join(missing_tags)}")

    result = {
        "gate_passed": not failures,
        "case_count": len(cases),
        "modalities": dict(sorted(modalities.items())),
        "required_tag_counts": {tag: tags[tag] for tag in sorted(REQUIRED_TAGS)},
        "failures": failures,
    }
    print(json.dumps(result, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
