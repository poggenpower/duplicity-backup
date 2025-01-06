FROM docker.io/python:3.12-alpine

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
	apk add -t .build-deps build-base linux-headers python3-dev librsync-dev git &&\
	CFLAGS="-Wno-int-conversion" pip install https://gitlab.com/duplicity/duplicity/-/archive/rel.3.0.3.2/duplicity-rel.3.0.0.tar.bz2 &&\
	apk del --purge .build-deps

RUN	addgroup -S app &&\
	adduser -S app -G app &&\
	mkdir -p \
		~app/.cache/duplicity \
		~app/.gnupg && \
	chown -R app:app ~app 

COPY src/*.py backup.yml requirements.txt /opt/app/
RUN pip install -r /opt/app/requirements.txt&& \
	chown -R root:root /opt/app && \
	find /opt/app -type d -exec chmod 755 {} + && \
	find /opt/app -type f -exec chmod 644 {} +;

USER app

ENTRYPOINT ["python3", "-u", "/opt/app/backup.py"]
