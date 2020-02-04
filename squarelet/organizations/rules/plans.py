# pylint: disable=unused-argument, invalid-unary-operand-type

# Third Party
from rules import add_perm, always_allow, always_deny, is_authenticated, predicate

# Squarelet
from squarelet.core.rules import skip_if_not_obj


@predicate
@skip_if_not_obj
def is_public(user, plan):
    return plan.public


@predicate
@skip_if_not_obj
def is_private_organization(user, plan):
    return plan.private_organizations.filter(pk=user.organization.pk).exists()


add_perm(
    "organizations.view_entitlement",
    is_public | (is_authenticated & is_private_organization),
)
add_perm("organizations.add_entitlement", always_deny)
add_perm("organizations.change_entitlement", always_deny)
add_perm("organizations.delete_entitlement", always_deny)
