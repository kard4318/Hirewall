# Staff roles and what each may do: a deny-by-default permission table
"""A role reaches only what is listed for it here. Anything missing is refused."""

HR_ADMIN = "hr_admin"
RECRUITER = "recruiter"
EMPLOYEE = "employee"

# Each role signs in to one area. The token audience is that area, so an employee token never works on HR routes.
ROLE_AUDIENCE = {HR_ADMIN: "hr", RECRUITER: "hr", EMPLOYEE: "employee"}

PERMISSIONS: dict[str, frozenset[str]] = {
    "hr_area": frozenset({HR_ADMIN, RECRUITER}),      # read and propose anything in the HR dashboard
    "approve": frozenset({HR_ADMIN, RECRUITER}),      # decide on items in the approval queue
    "manage_users": frozenset({HR_ADMIN}),
    "security_view": frozenset({HR_ADMIN}),
    "erase_candidate": frozenset({HR_ADMIN}),
    "employee_qa": frozenset({EMPLOYEE, HR_ADMIN, RECRUITER}),
}


def is_role(role: str) -> bool:
    return role in ROLE_AUDIENCE


def can(role: str | None, permission: str) -> bool:
    """True only when the permission exists and lists this role."""
    return bool(role) and role in PERMISSIONS.get(permission, frozenset())
