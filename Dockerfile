FROM docker.io/python:3

COPY backup.py backup.yml /opt/app/

RUN apk fix && \
	apk add --no-cache \
		ca-certificates \
		duplicity \
		openssh \
		rsync && \
	mkdir -p \
		~app/.cache/duplicity \
		~app/.gnupg && \
	chown -R app:app ~app && \
	chown -R root:root /opt/app && \
	find /opt/app -type d -exec chmod 755 {} + && \
	find /opt/app -type f -exec chmod 644 {} +;

USER app

ENTRYPOINT ["python3", "-u", "/opt/app/backup.py"]
