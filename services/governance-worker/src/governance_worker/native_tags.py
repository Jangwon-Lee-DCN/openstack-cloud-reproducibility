from __future__ import annotations

from dataclasses import dataclass

from governance_api.providers import OpenStackClient


def encode_tags(tags: dict[str, str]) -> list[str]:
    return [f"{key}={value}" for key, value in sorted(tags.items())]


def decode_tags(tags: list[str]) -> dict[str, str]:
    return dict(item.split("=", 1) for item in tags if "=" in item)


@dataclass
class MetadataTagAdapter:
    client: OpenStackClient
    project_id: str
    service: str

    def _path(self, resource_id):
        prefix = "v2.1" if self.service == "nova" else "v3"
        resources = "servers" if self.service == "nova" else "volumes"
        return f"/{prefix}/{self.project_id}/{resources}/{resource_id}/metadata"

    def read(self, resource_id: str) -> dict[str, str]:
        return self.client.request(self._path(resource_id))[1].get("metadata", {})

    def write(self, resource_id: str, tags: dict[str, str], expected_revision: int) -> int:
        self.client.request(self._path(resource_id), method="PUT", body={"metadata": tags})
        return expected_revision + 1


@dataclass
class CollectionTagAdapter:
    client: OpenStackClient
    service: str
    resource_plural: str

    def _path(self, resource_id):
        if self.service == "glance":
            return f"/v2/images/{resource_id}"
        return f"/v2.0/{self.resource_plural}/{resource_id}/tags"

    def read(self, resource_id: str) -> dict[str, str]:
        document = self.client.request(self._path(resource_id))[1]
        return decode_tags(document.get("tags", []))

    def write(self, resource_id: str, tags: dict[str, str], expected_revision: int) -> int:
        if self.service == "neutron":
            self.client.request(self._path(resource_id), method="PUT", body={"tags": encode_tags(tags)})
        else:
            current = set(self.client.request(self._path(resource_id))[1].get("tags", []))
            desired = set(encode_tags(tags))
            for tag in sorted(current - desired):
                self.client.request(f"{self._path(resource_id)}/tags/{tag}", method="DELETE")
            for tag in sorted(desired - current):
                self.client.request(f"{self._path(resource_id)}/tags/{tag}", method="PUT")
        return expected_revision + 1
