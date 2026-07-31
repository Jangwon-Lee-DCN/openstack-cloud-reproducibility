FROM python:3.12-slim-bookworm AS driver

COPY magnum-driver/ /src/

RUN pip install --no-cache-dir --no-deps --target /driver /src

FROM registry.dcn.ssu.ac.kr/openstack/magnum@sha256:4eda7acd9b7eea0c66662917a29151e22118e8ac89859017cc84a3948c5b426a

COPY --from=driver /driver/ /var/lib/openstack/lib/python3.12/site-packages/

RUN /var/lib/openstack/bin/python -c \
      "import importlib.metadata as m; assert any(e.name == 'k8s_capi_gitops_v1' for e in m.entry_points().select(group='magnum.drivers'))"
