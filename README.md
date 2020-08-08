# duplicity-backup
A small, easy-to-use wrapper to assist in automating backups done with [duplicity](http://duplicity.nongnu.org/).

# Setup
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

2. ssh keys:
	```sh
	ssh-keygen -t ecdsa -b 521
	ssh-copy-id user@remote.domain.tld
	```

3. run docker container:
	```sh
	docker pull intrand/duplicity-backup:latest && docker run -ti --rm --name duplicity --hostname duplicity \
	--mount source="${HOME}/.cache/duplicity",destination="/home/duplicity/.cache/duplicity",type=bind \
	--mount source="${HOME}/.gnupg",destination="/home/duplicity/.gnupg",type=bind \
	--mount source="${HOME}/backup.yml",destination="/opt/backup.yml",type=bind \
	--mount source="${HOME}/.ssh",destination="/home/duplicity/.ssh",type=bind \
	--mount source="/mnt/mydata",destination="/mnt/mydata",type=bind \
	intrand/duplicity-backup:latest --args='--rsync-options="--bwlimit=4096"'
	```

4. schedule with crontab/cronjob/kubernetes:

	I highly recommend running this inside Kubernetes to make the agent more reliable. Check the [deploy](deploy) directory for manifests.

	crontab example:

	Although optional, this short guide assumes you have written an extremely short script that runs the docker container correctly for your environment. It should probably also accept arbitrary arguments which can be appended to the container arguments. In POSIX shells, you'd use `${@}` in the script.

	Here's an example of such a script:
	```sh
	# contents of ~/backup.sh:
	#!/bin/sh
	docker pull intrand/duplicity-backup:latest && docker run -ti --rm --name duplicity --hostname duplicity \
	--mount <blah blah blah> \
	intrand/duplicity-backup:latest --args='--rsync-options="--bwlimit=4096"' ${@};
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
