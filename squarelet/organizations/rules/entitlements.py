# Third Party
from rules import add_perm, always_allow, always_deny

# XXX do we want to allow private entitlements?
add_perm("organizations.view_entitlement", always_allow)
add_perm("organizations.add_entitlement", always_deny)
add_perm("organizations.change_entitlement", always_deny)
add_perm("organizations.delete_entitlement", always_deny)
