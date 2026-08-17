import os

from django.views import generic
import yaml


CATALOG = os.getenv("DCN_SERVICE_CATALOG", "/etc/openstack-dashboard/dcn-service-catalog.yaml")


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
        context.update(region=value["region"], services=services)
        return context
