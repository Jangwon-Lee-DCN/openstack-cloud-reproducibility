import re

PROJECT_LABEL = "openstack_project_id"


def project_selector(query: str, project_id: str, project_label: str = PROJECT_LABEL) -> str:
    """Add an immutable project matcher to every LogQL stream selector."""
    if not re.fullmatch(r"[0-9a-fA-F-]{16,64}", project_id):
        raise ValueError("invalid project id")
    matcher = f'{project_label}="{project_id}"'
    selectors = 0

    def inject(match: re.Match[str]) -> str:
        nonlocal selectors
        selectors += 1
        body = match.group(1).strip()
        if re.search(rf"(?:^|,)\s*{re.escape(project_label)}\s*[!~]?=", body):
            body = re.sub(
                rf"(?:^|,)\s*{re.escape(project_label)}\s*[!~]?=\s*\"[^\"]*\"\s*",
                "",
                body,
            ).strip(", ")
        return "{" + ",".join(part for part in (matcher, body) if part) + "}"

    secured = re.sub(r"\{([^{}]*)\}", inject, query)
    if selectors == 0:
        raise ValueError("a LogQL stream selector is required")
    return secured
