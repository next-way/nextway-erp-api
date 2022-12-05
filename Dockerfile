FROM nextway-odoo-web
ARG env_file=.env.shared
USER root
WORKDIR /usr/local/
COPY fastapi-requirements.txt .
RUN pip install pip --upgrade
RUN pip install -r fastapi-requirements.txt
ADD . api/
WORKDIR api
EXPOSE 8082
CMD uvicorn app.main:app --reload --host 0.0.0.0 --port 8082
USER odoo
