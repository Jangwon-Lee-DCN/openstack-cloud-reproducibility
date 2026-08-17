from django.utils.translation import gettext_lazy as _
import horizon


class ServiceCatalog(horizon.Panel):
    name = _("Service Catalog")
    slug = "dcn_service_catalog"
