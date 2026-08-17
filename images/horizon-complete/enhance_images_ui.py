#!/usr/bin/env python3
"""Split the project image catalogue into platform, project, and shared views."""

from pathlib import Path


TABLES = Path(
    "/var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/"
    "dashboards/project/images/images/tables.py"
)
VIEWS = Path(
    "/var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/"
    "dashboards/project/images/views.py"
)

OLD_BUTTONS = """        buttons = [make_dict(_('Project'), 'project', 'fa-home')]
        for button_dict in filter_tenants():
            new_dict = button_dict.copy()
            new_dict['value'] = new_dict['tenant']
            buttons.append(new_dict)
        # FIXME(bpokorny): Remove this check once admins can list images with
        # GlanceV2 without getting all images in the whole cloud.
        if api.glance.VERSIONS.active >= 2:
            buttons.append(make_dict(_('Non-Public from Other Projects'),
                                     'other', 'fa-group'))
        else:
            buttons.append(make_dict(_('Shared with Project'), 'shared',
                                     'fa-share-square-o'))
        buttons.append(make_dict(_('Public'), 'public', 'fa-group'))
        return buttons
"""

NEW_BUTTONS = """        return [
            make_dict(_('Platform Images'), 'platform', 'fa-cloud'),
            make_dict(_('My Project Images'), 'project', 'fa-home'),
            make_dict(_('Shared by Users'), 'shared', 'fa-share-alt'),
        ]
"""

OLD_CATEGORIES = """def get_image_categories(im, user_tenant_id):
    categories = []
    if im.is_public:
        categories.append('public')
    if im.owner == user_tenant_id:
        categories.append('project')
    elif im.owner in filter_tenant_ids():
        categories.append(im.owner)
    elif not im.is_public:
        categories.append('shared')
        categories.append('other')
    return categories
"""

NEW_CATEGORIES = """def is_platform_image(image):
    properties = getattr(image, 'properties', {}) or {}
    platform_class = (properties.get('dcn_image_class') == 'platform' and
                      properties.get('dcn_workload_type', 'general') == 'general')
    platform_owners = set(getattr(settings, 'PLATFORM_IMAGE_OWNER_IDS', ()))
    return platform_class or image.owner in platform_owners


def get_image_categories(im, user_tenant_id):
    # Categories are deliberately exclusive. A public image is not an
    # official platform image unless its owner/property explicitly says so.
    properties = getattr(im, 'properties', {}) or {}
    if properties.get('dcn_workload_type') == 'amphora':
        return []
    if properties.get('dcn_workload_type') == 'capi':
        return ['platform']
    if is_platform_image(im):
        return ['platform']
    if im.owner == user_tenant_id:
        return ['project']
    return ['shared']
"""

def replace_once(source, old, new, label):
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} block, found {count}")
    return source.replace(old, new)


source = TABLES.read_text()
source = replace_once(source, OLD_BUTTONS, NEW_BUTTONS, "image filter")
source = replace_once(source, OLD_CATEGORIES, NEW_CATEGORIES, "classification")
TABLES.write_text(source)

views = VIEWS.read_text()
views = replace_once(
    views,
    "class IndexView(tables.DataTableView):\n    table_class = images_tables.ImagesTable\n",
    "class IndexView(tables.DataTableView):\n    table_class = images_tables.ImagesTable\n    template_name = 'project/images/index_split.html'\n",
    "image index template",
)
VIEWS.write_text(views)
