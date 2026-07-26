# VERIFY: Ceilometer

- Two central and two notification workers are Ready on distinct controllers.
- One compute pollster is Ready per compute-labeled node.
- Importing `libvirt` succeeds and active libvirt domains are visible.
- Notification logs contain neither recurring connection closure errors nor
  management-port URLs.
- A known VM produces a provider-side CPU or disk sample in Gnocchi.

The final end-to-end sample condition is currently pending and blocks a
production-ready declaration.
