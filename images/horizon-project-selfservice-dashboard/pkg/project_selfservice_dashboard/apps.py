from django.apps import AppConfig


class ProjectSelfserviceDashboardConfig(AppConfig):
    name = "project_selfservice_dashboard"
    verbose_name = "Project Self-Service"

    def ready(self):
        # Horizon's Nova, Cinder, Neutron and Placement adapters pass the
        # catalog identity URL to keystoneauth's generic Token plugin when
        # re-scoping an existing user token.  Generic discovery normalizes a
        # path-prefixed URL such as RegionOne-VM's /identity/v3 to origin-root
        # /v3/auth/tokens.  Before the Gateway gained that compatibility path,
        # federated project owners therefore saw misleading authorization
        # errors backed by a 404.  More importantly, Horizon is already inside
        # the cluster and should not depend on the VM-facing Gateway or its DNS
        # for authentication.  Resolve only Identity to the canonical
        # in-cluster setting; all actual service endpoints remain selected from
        # the user's catalog/region.  AppConfig.ready() is intentionally used
        # instead of local_settings.py: importing openstack_dashboard.api while
        # Django settings are still loading raises AppRegistryNotReady.
        from django.conf import settings
        from openstack_dashboard.api import base as os_api_base

        if not getattr(os_api_base, "_dcn_identity_url_override_installed", False):
            catalog_url_for = os_api_base.url_for

            def dcn_url_for(request, service_type, endpoint_type=None, region=None):
                if service_type == "identity":
                    return settings.OPENSTACK_KEYSTONE_URL
                return catalog_url_for(
                    request,
                    service_type,
                    endpoint_type=endpoint_type,
                    region=region,
                )

            os_api_base.url_for = dcn_url_for
            os_api_base._dcn_identity_url_override_installed = True

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
