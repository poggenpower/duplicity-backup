#/bin/bash +x
NAMESPACE=duplicity-backup
SECRETNAME=aws-api-key
read -p "AWS_ACCESS_KEY_ID: " -s AWS_ACCESS_KEY_ID
echo
read -p "AWS_SECRET_ACCESS_KEY: " -s AWS_SECRET_ACCESS_KEY
echo
kubectl -n ${NAMESPACE} create secret generic ${SECRETNAME} --from-literal=AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID}" --from-literal=AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY}"