from django.views.generic import TemplateView


class IndexView(TemplateView):
    template_name = "resilience_operations/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["collections"] = (
            "backup-policies", "restore-drills", "protection-groups", "dr-plans",
            "network-diagnostics", "maintenance-campaigns", "image-products", "image-builds",
        )
        return context
