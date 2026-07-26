# FIX: Python-Aligned Aodh WSGI Runtime

- Build Aodh 22.0.0 on Python 3.12.
- Compile and install mod_wsgi for that exact interpreter.
- Configure Apache with the matching Python site-packages path.
- Run API, evaluator, listener, and notifier with two hard-anti-affinity
  replicas; use MySQL Tooz coordination for distributed workers.
- Register `/alarming` in Keystone and the public Gateway.
- Disable only the defective optional alarm-cleaner CronJob until its upstream
  template is corrected.

The core alarm API and workers remain enabled. The public health endpoint has
returned HTTP 200.
