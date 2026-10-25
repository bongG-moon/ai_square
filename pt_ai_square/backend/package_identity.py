"""Stable platform identity, separate from each unchanged source declaration."""
import re


def valid_package_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9.-]{2,79}', value) else None


def source_package_id(package):
    return valid_package_id(package.get('packageId')) if isinstance(package, dict) else None


def fixed_package_id(tool=None, incoming=None):
    """Legacy reads are pure; the next authoritative tool CAS pins this value."""
    tool = tool or {}
    fixed = valid_package_id(tool.get('packageId'))
    if fixed:
        return fixed
    # Active release, rollback, withdrawal and deletion do not redefine identity.
    for version in sorted(tool.get('versions', []), key=lambda row: row['n']):
        fixed = source_package_id(version.get('package'))
        if fixed:
            return fixed
    return source_package_id(incoming)


def identity_fields(tool=None, package=None):
    fixed, source = fixed_package_id(tool, package), source_package_id(package)
    return dict(packageId=fixed, sourcePackageId=source,
                packageIdentityChanged=bool(fixed and source and fixed != source))
