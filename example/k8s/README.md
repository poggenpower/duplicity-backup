# Kubernetes Deployment

runs a `--all-subdirectories` job to backup a photo collection mounted to `/mnt/mydata` and send the back into longterm S3 storage in AWS.

## directories
- `_debug`: pod deplyment to help with troubleshooting
- `base`: base setup, is used by kustomize to create individual backup configs
- `photo-weekly`: deployment for the photo collention backup
- `prerequisites`: setting up some prerequisites that are not part of base. 

## setup

1. from `prerequisites` create the namespace and run the scripts to create secrets
2. from `base` make sure mount points fit to your needs
3. from `photo-weeely/conf` customise the backup.yml to your needs. 
4. deploy `kubectl apply -k ./photo-weekly`