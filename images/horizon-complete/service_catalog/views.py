import os
import logging

from django.views import generic
import yaml

from .flavor_api import list_flavors


CATALOG = os.getenv("DCN_SERVICE_CATALOG", "/etc/openstack-dashboard/dcn-service-catalog.yaml")
LOG = logging.getLogger(__name__)


class IndexView(generic.TemplateView):
    template_name = "service_catalog/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with open(CATALOG, encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
        is_admin = bool(
            getattr(self.request.user, "is_superuser", False)
            or getattr(self.request.user, "is_admin", False)
        )
        services = []
        for name, item in value["services"].items():
            if item["audience"] == "admin" and not is_admin:
                continue
            services.append({"name": name.replace("-", " ").title(), **item})
        try:
            flavors = list_flavors(self.request.user)
            flavor_error = None
        except Exception:
            LOG.exception("Flavor availability lookup failed")
            flavors = []
            flavor_error = "Flavor availability is temporarily unavailable. No Flavor is assumed launchable."
        context.update(
            region=value["region"], services=services, flavors=flavors,
            flavor_error=flavor_error,
        )
        return context
