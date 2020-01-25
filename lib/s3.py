import logging
import boto3
import os
import re

from botocore.exceptions import ClientError
from botocore.client import Config


def s3_client(aws_id, aws_key):
	s3 = boto3.client(
		's3',
		aws_access_key_id=aws_id,
		aws_secret_access_key=aws_key,
		config=Config(connect_timeout=10, read_timeout=10, retries={'max_attempts': 0})
	)

	return s3


def put_object(s3_client, dest_bucket_name, dest_object_name, src_data):
	"""Add an object to an Amazon S3 bucket

	The src_data argument must be of type bytes or a string that references
	a file specification.

    :param s3_client: s3_client as returned by s3_client()
	:param dest_bucket_name: string
	:param dest_object_name: string
	:param src_data: bytes of data or string reference to file spec
	:return: True if src_data was added to dest_bucket/dest_object, otherwise
	False
	"""

	# https://docs.aws.amazon.com/code-samples/latest/catalog/python-s3-put_object.py.html

	# Construct Body= parameter
	if isinstance(src_data, bytes):
		object_data = src_data
	elif isinstance(src_data, str):
		try:
			object_data = open(src_data, 'rb')
			# possible FileNotFoundError/IOError exception
		except Exception as e:
			logging.error(e)
			return False
	else:
		logging.error('Type of ' + str(type(src_data)) +
					  ' for the argument \'src_data\' is not supported.')
		return False

	try:
		s3_client.put_object(Bucket=dest_bucket_name, Key=dest_object_name, Body=object_data)
	except ClientError as e:
		# AllAccessDisabled error == bucket not found
		# NoSuchKey or InvalidRequest error == (dest bucket/obj == src bucket/obj)
		logging.error(e)
		return False
	finally:
		if isinstance(src_data, str):
			object_data.close()
	return True

def get_matching_s3_keys(s3_client, bucket, prefix='', pattern=''):
    """
    Generate the keys in an S3 bucket.

    :param bucket: Name of the S3 bucket.
    :param prefix: Only fetch keys that start with this prefix (optional).
    :param pattern: Only fetch keys that match this regex pattern (optional).
    """

    # Adapted from https://alexwlchan.net/2017/07/listing-s3-keys/

    kwargs = {'Bucket': bucket}

    # If the prefix is a single string (not a tuple of strings), we can
    # do the filtering directly in the S3 API.
    if isinstance(prefix, str):
        kwargs['Prefix'] = prefix

    while True:

        # The S3 API response is a large blob of metadata.
        # 'Contents' contains information about the listed objects.
        resp = s3_client.list_objects_v2(**kwargs)
        for obj in resp['Contents']:
            key = obj['Key']
            if key.startswith(prefix) and re.search(pattern, key):
                yield key

        # The S3 API is paginated, returning up to 1000 keys at a time.
        # Pass the continuation token into the next response, until we
        # reach the final page (when this field is missing).
        try:
            kwargs['ContinuationToken'] = resp['NextContinuationToken']
        except KeyError:
            break

class S3:
	"""AWS S3 client for getting/putting objects to/from oca-data bucket"""

	def __init__(self, aws_id, aws_key):
		self.s3 = s3_client(aws_id, aws_key)


	def download_file(self, object_name, file_path):

		# Retrieve the object
		self.s3.download_file('oca-data', object_name, file_path)


	def upload_file(self, object_name, file_path):

		# Put the object into the bucket
		put_object(self.s3, 'oca-data', object_name, file_path)


	def list_files(self, pattern):

		all_files = get_matching_s3_keys(self.s3, 'oca-data', 'private/', pattern)

		files = [os.path.basename(x) for x in all_files if x != 'private/']

		return files
