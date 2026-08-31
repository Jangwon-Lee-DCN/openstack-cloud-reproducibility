#!/usr/bin/env python3
"""Make federated logout invalidate the Horizon session before OP logout."""

from pathlib import Path


path = Path(
    "/var/lib/openstack/lib/python3.12/site-packages/openstack_auth/views.py"
)
source = path.read_text()
old = """    if (settings.WEBSSO_ENABLED and settings.WEBSSO_DEFAULT_REDIRECT and
            settings.WEBSSO_DEFAULT_REDIRECT_LOGOUT):
        auth_user.unset_session_user_variables(request)
        return django_http.HttpResponseRedirect(
            settings.WEBSSO_DEFAULT_REDIRECT_LOGOUT)
"""
new = """    if (settings.WEBSSO_ENABLED and settings.WEBSSO_DEFAULT_REDIRECT and
            settings.WEBSSO_DEFAULT_REDIRECT_LOGOUT):
        # Clearing selected OpenStack values leaves Django's session cookie
        # alive.  Flush the local session before starting RP-initiated logout
        # so neither Horizon nor the identity provider can restore the user.
        auth.logout(request)
        return django_http.HttpResponseRedirect(
            settings.WEBSSO_DEFAULT_REDIRECT_LOGOUT)
"""
if source.count(old) != 1:
    raise SystemExit("unexpected openstack_auth logout implementation")
path.write_text(source.replace(old, new))
