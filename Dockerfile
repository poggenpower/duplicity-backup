FROM docker.io/python:3.11-alpine

RUN apk fix && \
	apk add --no-cache \
		ca-certificates \
		openssh \
  		gpg \
    		gpg-agent \
		librsync
# install dev version of duplicity change URL or comment out
RUN pip install setuptools_scm boto3 python-gettext &&\
	apk add gettext &&\
	apk add -t .build-deps linux-headers python3-dev librsync-dev gcc musl-dev git &&\
	pip install duplicity==3.0.0 &&\
	apk del --purge .build-deps

RUN	addgroup -S app &&\
	adduser -S app -G app &&\
	mkdir -p \
		~app/.cache/duplicity \
		~app/.gnupg && \
	chown -R app:app ~app 

COPY *.py backup.yml requirements.txt /opt/app/
RUN pip install -r /opt/app/requirements.txt&& \
	chown -R root:root /opt/app && \
	find /opt/app -type d -exec chmod 755 {} + && \
	find /opt/app -type f -exec chmod 644 {} +;

USER app

ENTRYPOINT ["python3", "-u", "/opt/app/backup.py"]
