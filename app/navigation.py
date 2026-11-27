"""Sidebar navigation for every role, including features that are still being built.

Each role's menu lives here so the dashboards and the "under progress" page
render the same sidebar. Upcoming features link to /coming-soon/<slug>.
"""

from typing import Optional

from app.models.users import Role

# Features not built yet: slug -> label and a short description for the placeholder page
UPCOMING_FEATURES: dict[str, dict[str, str]] = {
    "notices": {
        "label": "Notices",
        "description": "Publish college-wide and department notices for staff and students.",
    },
    "exams": {
        "label": "Exams",
        "description": "Create exams, publish timetables and generate hall tickets.",
    },
    "students": {
        "label": "Students",
        "description": "Browse and manage every student in your department.",
    },
    "mentor-groups": {
        "label": "Mentor groups",
        "description": "Assign mentors and balance students across mentor groups.",
    },
    "subjects": {
        "label": "Subjects",
        "description": "Manage subjects and trainer assignments for each semester.",
    },
    "leave-requests": {
        "label": "Leave requests",
        "description": "Review, approve or reject student leave requests.",
    },
    "marks": {
        "label": "Marks",
        "description": "View internal and semester exam marks subject by subject.",
    },
    "enter-marks": {
        "label": "Enter marks",
        "description": "Enter and submit marks for the subjects you teach.",
    },
    "schedule": {
        "label": "Schedule",
        "description": "See your weekly teaching timetable across sections.",
    },
    "hall-ticket": {
        "label": "Hall ticket",
        "description": "Download your hall ticket for upcoming exams.",
    },
}

# Each role's menu: (key, label, url) for live pages, or an upcoming feature slug
_ROLE_MENUS: dict[Role, list] = {
    Role.MANAGEMENT: [
        ("dashboard", "Dashboard", "/management"),
        "notices",
        "exams",
    ],
    Role.HOD: [
        ("dashboard", "Dashboard", "/hod"),
        ("registrations", "Registrations", "/hod/registrations"),
        "students",
        "mentor-groups",
        "subjects",
        "leave-requests",
    ],
    Role.MENTOR: [
        ("dashboard", "Dashboard", "/mentor"),
        ("attendance", "Mark attendance", "/mentor/attendance"),
        "leave-requests",
        "marks",
    ],
    Role.TRAINER: [
        ("dashboard", "Dashboard", "/trainer"),
        "enter-marks",
        "schedule",
    ],
    Role.STUDENT: [
        ("dashboard", "Dashboard", "/student"),
        ("change-password", "Change password", "/change-password"),
        ("attendance", "Attendance", "/student/attendance"),
        "marks",
        "hall-ticket",
    ],
}


def coming_soon_url(slug: str) -> str:
    """URL of the placeholder page for an upcoming feature."""
    return f"/coming-soon/{slug}"


def role_upcoming_slugs(role: Role) -> set[str]:
    """Upcoming feature slugs that appear in this role's menu."""
    return {item for item in _ROLE_MENUS.get(role, []) if isinstance(item, str)}


def build_nav(role: Role, active: str, pending_count: Optional[int] = None) -> list[dict]:
    """Build the sidebar links for a role, marking `active` (a key or slug) as current."""
    links = []
    for item in _ROLE_MENUS.get(role, []):
        if isinstance(item, str):
            links.append(
                {
                    "label": UPCOMING_FEATURES[item]["label"],
                    "url": coming_soon_url(item),
                    "active": active == item,
                    "tag": "Soon",
                }
            )
            continue
        key, label, url = item
        link = {"label": label, "url": url, "active": active == key}
        if key == "registrations" and pending_count:
            link["badge"] = pending_count
        links.append(link)
    return links
