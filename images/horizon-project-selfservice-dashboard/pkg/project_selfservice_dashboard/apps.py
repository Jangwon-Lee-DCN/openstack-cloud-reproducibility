from django.apps import AppConfig


class ProjectSelfserviceDashboardConfig(AppConfig):
    name = "project_selfservice_dashboard"
    verbose_name = "Project Self-Service"

    def ready(self):
        # Replaces openstack_dashboard.api.keystone.is_domain_admin
        # everywhere, by overwriting the attribute on the already-imported
        # keystone module object. See facade.is_domain_admin for the full
        # story of why the stock implementation is broken in this
        # deployment (undefined Horizon-local policy rule, plus a
        # domain-scoped token that signed-cookie sessions never cache in
        # the first place) and why this fixes it without needing to
        # maintain a full patched copy of api/keystone.py (a much larger,
        # more widely-imported file than the identity/projects/* files
        # already patched elsewhere in this image).
        #
        # This works because every real caller -- the identity/{projects,
        # users,groups,roles,credentials} panels/tables, and keystone.py's
        # own keystoneclient(admin=True) -- resolves is_domain_admin via
        # the module's global namespace at call time (either
        # `keystone.is_domain_admin(...)` from outside the module, or a
        # bare `is_domain_admin(...)` call from code defined inside
        # keystone.py itself, which Python still resolves through the
        # same module __dict__ at call time, not at def time). Confirmed
        # by grepping every caller in the deployed image before relying
        # on this.
        from openstack_dashboard.api import keystone as os_keystone

        from . import facade

        os_keystone.is_domain_admin = facade.is_domain_admin
