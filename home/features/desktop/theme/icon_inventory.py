"""Shared inventory rules for the installed theme and its review catalogue."""


def filter_app_placeholders(manifest):
    """Separate macOS's generic app artwork from actual icon identities.

    Exports are content-addressed PNGs. Compare their full-size artwork, not
    names or approximate colors: unrelated icons must not be filtered out.
    Keep the reference record available for one explicit application fallback.
    """
    fallback = next(
        entry for entry in manifest["entries"]
        if entry["kind"] == "type" and entry["id"] == "com.apple.application-bundle"
    )
    fingerprint = fallback["files"]["512"]
    kept, placeholders = [], []
    for entry in manifest["entries"]:
        target = placeholders if entry["files"]["512"] == fingerprint else kept
        target.append(entry)
    return kept, fallback, placeholders
