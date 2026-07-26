# Keystone OIDC Image Baseline

- Upstream image tag: `quay.io/airshipit/keystone:2026.1-ubuntu_noble`
- Resolved upstream digest:
  `sha256:3dcc27ea83169118e014a100c848f147279c5c8a0709c0c62d8c4766f0219e03`
- Added Ubuntu package: `libapache2-mod-auth-openidc`
- Added temporary PoC public trust anchor: `openstack-public-ca.crt`

No Keystone Python package is replaced. The derivative only adds the Apache
OIDC authentication module required by Keystone federation.


The PoC trust anchor is the public certificate only; no private key is stored.
Replace it and rebuild the image when the temporary self-signed Gateway
certificate is replaced by the production PKI.
