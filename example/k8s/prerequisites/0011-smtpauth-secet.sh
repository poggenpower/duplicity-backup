#/bin/bash +x
NAMESPACE=duplicity-backup
SECRETNAME=smtp-auth-pw
read -p "DUPBACK_EMAIL__PASSWORD: " -s DUPBACK_EMAIL__PASSWORD
kubectl -n ${NAMESPACE} create secret generic ${SECRETNAME} --from-literal=DUPBACK_EMAIL__PASSWORD="${DUPBACK_EMAIL__PASSWORD}"