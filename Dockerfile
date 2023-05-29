FROM docker.io/python:3-alpine

COPY backup.py backup.yml requirements.txt /opt/app/

RUN apk fix && \
	apk add --no-cache \
		ca-certificates \
		duplicity \
		openssh \
		rsync &&\
	pip install -r /opt/app/requirements.txt
RUN	addgroup -S app &&\
	adduser -S app -G app &&\
	mkdir -p \
		~app/.cache/duplicity \
		~app/.gnupg && \
	chown -R app:app ~app && \
	chown -R root:root /opt/app && \
	find /opt/app -type d -exec chmod 755 {} + && \
	find /opt/app -type f -exec chmod 644 {} +;

USER app

ENTRYPOINT ["python3", "-u", "/opt/app/backup.py"]
