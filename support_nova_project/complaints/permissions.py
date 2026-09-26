"""
Which complaints a staff member may see and act on (SRS FR ii role-based access, Step 62).

    reviewer / manager / admin   every complaint (review queue, reassignment, reports)
    agent                        only complaints currently ASSIGNED to them
    customer                     none here - customers use their own /my endpoints

Complaints outside a user's scope return 404 (not 403), so nobody can discover that a
complaint ID exists by probing.
"""

from django.shortcuts import get_object_or_404

from accounts.models import User

from .models import Complaint

FULL_ACCESS_ROLES = (User.Role.REVIEWER, User.Role.MANAGER, User.Role.ADMIN)


def has_full_access(user):
    return user.is_superuser or user.role in FULL_ACCESS_ROLES


def visible_complaints(user, queryset=None):
    queryset = Complaint.objects.all() if queryset is None else queryset
    if has_full_access(user):
        return queryset
    if user.role == User.Role.AGENT:
        return queryset.filter(assigned_to=user)
    return queryset.none()


def get_visible_complaint(user, complaint_id, queryset=None):
    return get_object_or_404(visible_complaints(user, queryset), complaint_id=complaint_id.upper())
