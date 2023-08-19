# duplicity-backup
A small, easy-to-use wrapper to assist in automating backups done with [duplicity](http://duplicity.nongnu.org/).
With special use case Backup of photo collection or other tye pf archives.

## Features
- full configurable by ENV Vars, config file or command line switches
	- use `--help` for full list of parameter or check the backup.yml as example config
- trigger one backup per source to decuple.
	- Special use case: create a separate backup for all subdirectories. 
- report backup runs via Email

## Use Case: Photo Collention Backup

Typical photo collection has a folder structure, e.g. the higest level is the year and then month or event. 
You can backup the whole structure at once. But this will create a huge backup. As you constantly adding new photos regular incrementat backups are needded. 
But chaining many incremental backups increase the risk of data corruption as one damaged incremental corrupts all following. Therefore regular full backups are required - which are huge again.

### Solution:
duplicity-backup will create one backup per year if if `--source.Basedir` is pointing to you pfoto collection and `--all-subdirectories` is given. 
Incremental are only created if there are changes for that year, which should not be the case for most of the past years, but they get a backup if changed, so no manual housekeeping is required. 
If there are a certain amount of incremental backups an full backup is made for this specific year. A configurable amount of full backups is kept per year.

# Setup Example Kubernets

see `exampel/k8s/` for a kubernetes deployment.

# Setup Example Docker 
Setup should be very straightforward as long as you have a working (passwordless) SSH connection from the source to destination. If you need to go over the Internet, I highly recommend using a VPN to tunnel your traffic.

Here's a "loose" guide on how to set up your system:

1. gpg keys:
	new key:
	```sh
	gpg --gen-key
	```

	OR

	existing key:
	```sh
	gpg --list-keys
	```
	!!! IMPORTANT !!! don't loose these keys, otherwise your backup is lost too. 
	Alternatively you can put the keys as PEM in the config file. 

2. ssh keys:
	```sh
	ssh-keygen -t ecdsa -b 521
	ssh-copy-id user@remote.domain.tld
	```
	Only required if backup via ssh. 

3. run docker container:
	```sh
	docker pull ghcr.io/intrand/duplicity-backup:$release && \
	docker run \
		-ti \
		--rm \
		--name duplicity \
		--hostname duplicity \
		--mount source="${HOME}/.cache/duplicity",destination="/home/duplicity/.cache/duplicity",type=bind \
		--mount source="${HOME}/.gnupg",destination="/home/duplicity/.gnupg",type=bind \
		--mount source="${HOME}/backup.yml",destination="/opt/backup.yml",type=bind \
		--mount source="${HOME}/.ssh",destination="/home/duplicity/.ssh",type=bind \
		--mount source="/mnt/mydata",destination="/mnt/mydata",type=bind \
	ghcr.io/poggenpower/duplicity-backup:latest \
		--args='--rsync-options="--bwlimit=4096"'
	```

4. schedule with crontab/cronjob/kubernetes:

	I highly recommend running this inside Kubernetes to make the agent more reliable. Check the [deploy](deploy) directory for manifests.

	crontab example:

	Although optional, this short guide assumes you have written an extremely short script that runs the docker container correctly for your environment. It should probably also accept arbitrary arguments which can be appended to the container arguments. In POSIX shells, you'd use `${@}` in the script.

	Here's an example of such a script:
	```sh
	# contents of ~/backup.sh:
	#!/bin/sh
	docker pull ghcr.io/intrand/duplicity-backup:$release && \
	docker run -ti --rm --name duplicity --hostname duplicity \
		--mount <blah blah blah> \
	ghcr.io/intrand/duplicity-backup:latest \
		--args='--rsync-options="--bwlimit=4096"' \
		${@};
	exit ${?};
	```

	```sh
	crontab -e
	```

	```sh
	# # full backup on jan & jul 1st:
	0 0 1 1,7 * ~/backup.sh --full >> ~/backup-full.log;
	# # weekly backup every week:
	0 0 * * 1 ~/backup.sh >> ~/backup.log;
	```
