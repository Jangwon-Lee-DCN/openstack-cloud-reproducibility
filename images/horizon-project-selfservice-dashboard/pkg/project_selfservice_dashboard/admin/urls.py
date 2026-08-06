from django.urls import re_path
from project_selfservice_dashboard.admin import views

urlpatterns = [re_path(r"^$", views.ProjectOperationsView.as_view(), name="index")]
