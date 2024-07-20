import time
import boto3
import fnmatch
import argparse

def wait(seconds):
    print(f"Wait {seconds}s: ", end="")
    for i in range(seconds):
        print(".", end="", flush=True)
        time.sleep(1)
    print("")

def initiate_restore(bucket_name, file_pattern, days=7, dry_run=False):
    # Create a session using the default profile
    session = boto3.Session()
    
    # Create an S3 client
    s3 = session.client('s3')
    
    # List objects in the bucket
    paginator = s3.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=bucket_name)


    restored_files = 0

    for page in page_iterator:
        if 'Contents' in page:
            for obj in page['Contents']:
                key = obj['Key']
                if fnmatch.fnmatch(key, file_pattern) and obj['StorageClass'] == 'GLACIER':
                    response = s3.head_object(Bucket=bucket_name, Key=key)
                    trigger_restore = False
                    if 'Restore' in response:
                        restore_status = response['Restore']
                        print(f"Restore status for {key}: {restore_status}")
                        if 'ongoing-request="true"' in restore_status:
                            print(f"{key} is currently being restored.")
                        elif 'ongoing-request="false"' in restore_status:
                            print(f"{key} has been successfully restored and is now available for access.")
                    else:
                        trigger_restore = True
                        restored_files += 1
                    if not dry_run and trigger_restore:
                        response = s3.restore_object(
                            Bucket=bucket_name,
                            Key=key,
                            RestoreRequest={
                                'Days': days,
                                'GlacierJobParameters': {
                                    'Tier': 'Expedited'  # Use 'Bulk' or 'Expedited' for different retrieval options
                                }
                            }
                        )
                        print(f"Restore initiated: {key}, Status: {response['ResponseMetadata']['HTTPStatusCode']}")
                    elif dry_run:
                        print(f"Dry run: trigger restore of {key}")
                    if restored_files % 3 == 0 and restored_files > 0:
                        wait(300)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Initiate restore on S3 Glacier Flexible Retrieval by file pattern.')
    parser.add_argument('bucket_name', type=str, help='The name of the S3 bucket.')
    parser.add_argument('file_pattern', type=str, help='The file pattern to match (e.g., "*.txt").')
    parser.add_argument('--days', type=int, default=7, help='The number of days to keep the restored files available.')
    parser.add_argument('--dry-run', action="store_true", help='show what would happen')
    
    args = parser.parse_args()
    
    initiate_restore(args.bucket_name, args.file_pattern, args.days, args.dry_run)
