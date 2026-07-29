# Kubernetes host tuning

Apply `99-kubernetes-inotify.conf` to every Kubernetes node:

```bash
sudo install -o root -g root -m 0644 \
  99-kubernetes-inotify.conf /etc/sysctl.d/99-kubernetes-inotify.conf
sudo sysctl --system
```

## Why this is required

On 2026-07-28, `cloud-controller-0` exhausted Ubuntu's default
`fs.inotify.max_user_instances=128`. CRI-O could no longer create watches and
kubelet failed to rotate container logs with `too many open files`. The
process file-descriptor limits were not exhausted.

These values are conservative host-wide ceilings, not preallocated memory.
Monitor actual consumption and raise them only when justified.
