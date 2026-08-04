# FAST-ITERATION DEV IMAGE ONLY -- not the source of truth. This Dockerfile
# layers on top of whatever HORIZON_BASE happened to be live at build time,
# which is exactly the pattern that has repeatedly dropped previously-applied
# features when two people rebuilt from different "current live" bases in
# parallel (confirmed live more than once this engagement). The real,
# reproducible build is images/horizon-complete/Dockerfile, assembled by
# deploy/scripts/build-images.sh from a single pinned public upstream base
# plus every feature's current source (Octavia workflow, Designate, the VPC
# dashboard wheel, this project's pkg/, and Magnum UI) in one deterministic
# pass -- no dependency on registry state at all. Use *that* path (or
# reconcile-full-stack.sh with BUILD_IMAGES=1) for anything meant to persist;
# treat this file as a scratch pad for quickly testing a change against
# whatever is currently deployed, and mirror any lasting change into
# pkg/ so build-images.sh's next horizon-complete run picks it up too.
#
# This incremental development image must retain the Magnum UI layer.  The
# previous base (6b13...) predated Magnum and silently removed its panels when
# project-selfservice was rebuilt on top of it.
ARG HORIZON_BASE=registry.dcn.ssu.ac.kr/openstack/horizon@sha256:f6074a6b86c7ad95c61207b092e1b0b6048cc6504b04b9686b7956c23242f2db
FROM ${HORIZON_BASE}

USER root

# Docker layers are additive: an earlier pass of this same image shipped
# a standalone "Project Management" panel (superseded below by adding the
# action directly into Identity > Projects instead), and neither deleting
# files from the build context nor re-COPYing a directory removes files
# that only exist in a lower layer. Explicitly remove that superseded
# panel's registration and package directory first, so no earlier layer
# in the base image's own history can leave a dangling nav entry (its
# panel/views no longer exist, so it would 404) or stale package content
# behind.
RUN rm -f /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_1800_project_selfservice_panel_group.py \
          /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_1810_project_selfservice_panel.py \
    && rm -rf /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/__pycache__ \
    && rm -rf /var/lib/openstack/lib/python3.12/site-packages/project_selfservice_dashboard

# Preserve every already-deployed panel from the immutable base image
# (Octavia, Designate, VPC, ENI), then add self-service project creation
# directly into the stock Identity > Projects table -- see
# docs/proposals/iam-hardening/README.md, "New permission tier:
# self-service project lifecycle". Superseded the original design (a
# separate "Project Management" panel under the Project dashboard) once
# it was confirmed empirically that non-admin users CAN already reach
# Identity > Projects here (identity:list_user_projects' `user_id:
# %(target.user.id)s` clause allows anyone to see their own projects,
# and Horizon's panel-level policy_rules is an OR check, not AND) --
# only the native "Create Project" *action* is admin-gated, so adding a
# second, self-service-scoped action to the same existing table is more
# natural than a separate panel.
COPY pkg/project_selfservice_dashboard /var/lib/openstack/lib/python3.12/site-packages/project_selfservice_dashboard

# Full replacements of three stock Identity > Projects files, not a
# monkeypatch from outside them -- each is kept as a complete copy of the
# upstream file plus one local addition, so a diff against upstream shows
# exactly that addition (see the comment at the top of each file for what
# changed). views.py was added after tables.py/urls.py, once a real user
# hit a live bug in the *stock* IndexView.get_data() -- see its own
# comment for the full story.
COPY pkg/identity_projects_patch/tables.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/tables.py
COPY pkg/identity_projects_patch/urls.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/urls.py
COPY pkg/identity_projects_patch/views.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/views.py

COPY pkg/enabled/_1800_project_selfservice_app.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_1800_project_selfservice_app.py

RUN python3 -c "import project_selfservice_dashboard" \
    && python3 -m py_compile /var/lib/openstack/lib/python3.12/site-packages/project_selfservice_dashboard/apps.py \
    && python3 -m py_compile /var/lib/openstack/lib/python3.12/site-packages/project_selfservice_dashboard/facade.py \
    && python3 -m py_compile /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/tables.py \
    && python3 -m py_compile /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/urls.py \
    && python3 -m py_compile /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/views.py
