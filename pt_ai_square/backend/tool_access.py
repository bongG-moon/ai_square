"""Shared detail/catalog permission decision using trusted server-side inputs."""
from .department_access import group_matches


def can_read(tool, uid, profile, *, administrator=False, personal_grant=False):
    if not profile or not profile.get('enabled', True):
        return False
    return bool(tool.get('owner') == uid or administrator
                or not tool.get('data', {}).get('approval') or personal_grant
                or (profile.get('enabled') is True
                    and any(group_matches(rule, profile)
                            for rule in tool.get('departmentGrants', []))))
