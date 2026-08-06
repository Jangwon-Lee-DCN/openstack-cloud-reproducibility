from types import SimpleNamespace
from django.utils.translation import gettext_lazy as _
from horizon import exceptions, messages
from horizon import tables as horizon_tables
from project_selfservice_dashboard import facade, tables


class ProjectOperationsView(horizon_tables.DataTableView):
    table_class = tables.DomainProjectsOverviewTable
    page_title = _("Project Operations")

    def get_data(self):
        try:
            projects = facade.domain_projects_overview(self.request)
        except facade.FacadeError as exc:
            messages.error(self.request, str(exc))
            return []
        except Exception:
            exceptions.handle(self.request, _("Unable to retrieve project operations inventory."))
            return []
        return [
            SimpleNamespace(
                id=item["project_id"], project_id=item["project_id"],
                project_name=item["project_name"], admins=", ".join(item["admins"]) or "-",
                member_count=item["member_count"], tags=", ".join(item.get("tags", [])),
                last_activity=item["last_activity"],
            ) for item in projects
        ]
