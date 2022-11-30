# Nextway ERP API

API to expose Odoo models related for Nextway ERP.

## Development Setup

Spin up your favorite virtual env.

```console
$ pyenv virtualenv 3.10.8 nextway-erp-api
$ pyenv local nextway-erp-api
```

Install dependencies.

```console
$ pipenv shell
(nextway-erp-api) $ pipenv install
```

## Run server

Make sure Odoo is running or the database at least is before running API server.

```console
$ env ODOO_RC=/path/to/nextway-erp-web/config/odoo.conf uvicorn app.main:app --reload --host 0.0.0.0 --port 8082
INFO:     Will watch for changes in these directories: ['/Users/awesome/projects/nextway-erp-api']
INFO:     Uvicorn running on http://127.0.0.1:8082 (Press CTRL+C to quit)
INFO:     Started reloader process [29186] using WatchFiles
INFO:     Started server process [29188]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

Head on to http://127.0.0.1:8082/docs/ to try out!
