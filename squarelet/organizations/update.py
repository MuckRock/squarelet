"""Functions to update information on other sites when someone updates their
information on squarelet"""

# Local
from ..core.update import muckrock_api


def muckrock(organization):
    data = {
        "name": organization.name,
        "private": organization.private,
        "plan": organization.plan,
        "individual": organization.individual,
    }

    return muckrock_api(f"/organization/{organization.pk}/", data)


def muckrock_add_member(organization_uuid, user_uuid):
    return muckrock_api(
        f"/organization/{organization_uuid}/membership/",
        {"user": user_uuid},
        method="post",
    )


def muckrock_remove_member(organization_uuid, user_uuid):
    return muckrock_api(
        f"/organization/{organization_uuid}/membership/{user_uuid}/", method="delete"
    )


def doccloud(_organization):
    pass
