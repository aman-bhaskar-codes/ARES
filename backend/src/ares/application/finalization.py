from ares.domain.models import FinalizedClaim


def compose_checked_markdown(claims: list[FinalizedClaim]) -> str:
    if not claims:
        return "### Evidence-checked answer\n\nNo claim met the current evidence checks."
    return "### Evidence-checked answer\n\n" + "\n\n".join(
        claim.text.strip() for claim in claims if claim.text.strip()
    )
