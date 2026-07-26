# RECONCILE: Aodh

1. Build or pull the digest-pinned Python 3.12/mod_wsgi Aodh image.
2. Re-encrypt the Aodh values profile for the target database, Keystone,
   RabbitMQ, and registry credentials.
3. Run `deploy/scripts/reconcile.sh`; it upgrades the clean upstream chart
   using the local values file.
4. Keep the optional alarm cleaner disabled until its template volume defect
   is fixed and verified in a separate chart patch commit.
