# duplicity-backup
A small, easy-to-use wrapper to assist in automating backups done with [duplicity](http://duplicity.us/).
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
duplicity-backup will create one backup per year if if `--source.Basedir` is pointing to you photo collection and `--all-subdirectories` is given. 
Incremental are only created if there are changes for that year, which should not be the case for most of the past years, but they get a backup if changed, so no manual housekeeping is required. 
If there are a certain amount of incremental backups an full backup is made for this specific year. A configurable amount of full backups is kept per year.

# Setup Example Kubernets e.g. for local storage backup

## Deployment
see `exampel/k8s/` for a kubernetes deployment.

## Backup of local storage class PVs

Run with `--k8s-local-storage-discovery` to discover all folders for bound local storage PVs. 
The most common path will be replacesd with `--source.Basedir`, so mount hostpath accordingly. 

Create service account and roles as shown in `examples/k8s/k8s_localstrage_backup.yaml`
Create a cronjob as for other backups per node which is holding local storage (yes, you need to maintain this manually.)

Make sure you set the env var with the node name:
```
    env:
      - name: K8S_NODE_NAME
        valueFrom:
          fieldRef:
            fieldPath: spec.nodeName
```
and run with a Service Account, whith appropriate permissions
```
      serviceAccountName: backup-config-modifier
```
if you are not running all your containers under the same UID, you must run as `root` to have access to all files from different users:
```
        securityContext:
          runAsUser: 0
```
mount the path from the host where all local-storage classes drops their files:
```
        volumeMounts:
        - name: longhorn-local-storage
          mountPath: /local-storage
      volumes:
      - name: longhorn-local-storage
        hostPath:
          path: /var/lib/local-storage
          type: Directory
```


# Setup Example Docker 
Setup should be very straightforward as long as you have a working (passwordless) SSH connection from the source to destination. 

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

3. configure duplicity-backup

	use `backup.yaml` as a template. it should have some comments to help with configuration. 

	beside different backup flavours "full", "inc", "backup" (automatically to full then inc),
	following duplicity commands are also supported (see duplicity docs for details):
	- restore
	- verify
	- collection-status
	- remove
	- cleanup
	- list-current-files

	If you use S3 as backend you should configure AWS_REGION and AWS_ENDPOIN_URL or other via ENV Var instead of using e.g. `--s3-region` in the `args` section of the config file. This will ensure that all duplicity commands receive the same parameters. 

3. run docker container:
	```sh
	docker pull ghcr.io/poggenpower/duplicity-backup:$release && \
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
	ghcr.io/poggenpower/duplicity-backup:$release \
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
	docker pull ghcr.io/poggenpower/duplicity-backup:$release && \
	docker run -ti --rm --name duplicity --hostname duplicity \
		--mount <blah blah blah> \
	ghcr.io/poggenpower/duplicity-backup:latest \
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

