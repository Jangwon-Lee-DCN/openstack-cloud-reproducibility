# Registers project_selfservice_dashboard as an installed Django app so its
# templates and views are importable/discoverable (Django's app-template
# loader needs this), without adding a separate panel or panel group --
# its "Create Project (Self-Service)" action is added directly into the
# existing Identity > Projects table instead (see
# identity_projects_patch/tables.py and .../urls.py, applied over the
# stock files at image build time). See docs/proposals/iam-hardening/
# README.md, "New permission tier: self-service project lifecycle".
#
# FEATURE is required here even though nothing else in this file adds an
# actual feature flag: Horizon's enabled-file loader
# (openstack_dashboard.utils.settings.import_dashboard_config) silently
# SKIPS any enabled file lacking one of DASHBOARD/PANEL/PANEL_GROUP/FEATURE
# -- found live, the hard way, in two stages:
#   1. A first pass with only ADD_INSTALLED_APPS set was skipped entirely
#      (logged as a warning, easy to miss), so the app was never actually
#      added to INSTALLED_APPS and its templates were never discoverable,
#      producing TemplateDoesNotExist at request time instead of at
#      build/import time.
#   2. Setting DASHBOARD = "identity" (reasoning: "this app is used by the
#      identity dashboard") "fixed" that but broke the entire site instead
#      (horizon.base.NotRegistered: Dashboard with slug "identity" is not
#      registered on EVERY page, not just this one) -- DASHBOARD merges
#      this whole file's namespace into horizon_config's SHARED config
#      entry for that dashboard slug (see import_dashboard_config's
#      `config[dashboard].update(submodule.__dict__)`), clobbering the
#      real identity dashboard's own registration file's entry instead of
#      adding a separate one.
# FEATURE, by contrast, takes the *other* branch
# (`config[name] = submodule.__dict__`, keyed by this file's own name) --
# a fully isolated config entry that still gets its ADD_INSTALLED_APPS
# read and applied (update_dashboards reads ADD_INSTALLED_APPS off every
# resulting config dict, regardless of which branch produced it), without
# touching any dashboard's shared config at all. The value itself is
# unused by anything downstream; it only needs to be present.
FEATURE = "project_selfservice"
ADD_INSTALLED_APPS = ["project_selfservice_dashboard"]
