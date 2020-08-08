FROM alpine:latest

RUN apk add --no-cache \
		ca-certificates \
		duplicity \
		py3-pip \
		openssh \
		rsync && \
	pip3 install --no-cache --upgrade install \
		pip \
		pyyaml \
		sh && \
	adduser -D -u 1000 duplicity && \
	mkdir -p ~duplicity/.cache/duplicity && \
	mkdir -p ~duplicity/.gnupg && \
	chown -R duplicity:duplicity ~duplicity;

COPY backup.py backup.yml /opt/

USER duplicity

ENTRYPOINT ["python3", "-u", "/opt/backup.py"]
