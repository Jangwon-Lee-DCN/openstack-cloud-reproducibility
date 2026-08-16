from dataclasses import dataclass, field


class ProviderError(RuntimeError):
    def __init__(self, code, retryable=False):
        super().__init__(code); self.code, self.retryable = code, retryable


class ComputeAdapter:
    def create_server(self, operation_id, spec): raise NotImplementedError
    def delete_server(self, server_id): raise NotImplementedError


class NetworkAdapter:
    def create_port(self, operation_id, spec): raise NotImplementedError
    def delete_port(self, port_id): raise NotImplementedError


class VolumeAdapter:
    def create_volume(self, operation_id, spec): raise NotImplementedError
    def delete_volume(self, volume_id): raise NotImplementedError


@dataclass
class DeterministicProviders(ComputeAdapter, NetworkAdapter, VolumeAdapter):
    """Contract fake: idempotent IDs and observable reverse compensation."""
    resources: dict = field(default_factory=lambda: {"ports": {}, "volumes": {}, "servers": {}})
    calls: list = field(default_factory=list)
    fail_at: str | None = None

    def _create(self, kind, operation_id, spec):
        self.calls.append(f"create:{kind}")
        if self.fail_at == kind: raise ProviderError(f"{kind.upper()}_CREATE_FAILED", retryable=False)
        ident = f"{kind}-{operation_id}"
        self.resources[kind + "s"].setdefault(ident, dict(spec))
        return ident

    def _delete(self, kind, ident):
        self.calls.append(f"delete:{kind}"); self.resources[kind + "s"].pop(ident, None)

    def create_port(self, operation_id, spec): return self._create("port", operation_id, spec)
    def delete_port(self, ident): self._delete("port", ident)
    def create_volume(self, operation_id, spec): return self._create("volume", operation_id, spec)
    def delete_volume(self, ident): self._delete("volume", ident)
    def create_server(self, operation_id, spec): return self._create("server", operation_id, spec)
    def delete_server(self, ident): self._delete("server", ident)


class InstanceProvisioner:
    def __init__(self, compute, network, volume): self.compute, self.network, self.volume = compute, network, volume

    def provision(self, operation_id, spec, checkpoint=None):
        checkpoint = dict(checkpoint or {})
        try:
            if not checkpoint.get("port_id"):
                checkpoint["port_id"] = self.network.create_port(operation_id, spec["network"])
            if spec.get("volume") and not checkpoint.get("volume_id"):
                checkpoint["volume_id"] = self.volume.create_volume(operation_id, spec["volume"])
            if not checkpoint.get("server_id"):
                checkpoint["server_id"] = self.compute.create_server(operation_id, spec | checkpoint)
            return checkpoint
        except ProviderError as exc:
            exc.checkpoint = checkpoint
            if not exc.retryable:
                self.compensate(checkpoint)
            raise

    def compensate(self, checkpoint):
        if checkpoint.get("server_id"): self.compute.delete_server(checkpoint["server_id"])
        if checkpoint.get("volume_id"): self.volume.delete_volume(checkpoint["volume_id"])
        if checkpoint.get("port_id"): self.network.delete_port(checkpoint["port_id"])
