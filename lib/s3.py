import logging
import boto3
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


# https://docs.aws.amazon.com/code-samples/latest/catalog/python-s3-get_object.py.html

def get_object(s3_client, bucket_name, object_name):
    """Retrieve an object from an Amazon S3 bucket

    :param s3_client: s3_client as returned by s3_client()
    :param bucket_name: string
    :param object_name: string
    :return: botocore.response.StreamingBody object. If error, return None.
    """

    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=object_name)
    except ClientError as e:
        # AllAccessDisabled error == bucket or object not found
        logging.error(e)
        return None

    # Return an open StreamingBody object
    return response['Body']


# https://docs.aws.amazon.com/code-samples/latest/catalog/python-s3-put_object.py.html

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


class S3:
	"""AWS S3 client for getting/putting objects to/from oca-data bucket"""

	def __init__(self, aws_id, aws_key):
		self.s3 = s3_client(aws_id, aws_key)


	def get_object_stream(self, object_name):
		# TODO: Because the parsing takes some time, on large XML files the
		# connection can easily timeout using this stream method. Instead we ned
		# simply download the file to a local folder and parse it from there. We can
		# probably just remove these put_object() and get_object_stream() fuctions.

		# Set up logging
		logging.basicConfig(level=logging.DEBUG,
		                    format='%(levelname)s: %(asctime)s: %(message)s')

		# Retrieve the object
		stream = get_object(self.s3, 'oca-data', object_name)

		return stream

	def get_object_download(self, object_name, file_path):

		# Set up logging
		logging.basicConfig(level=logging.DEBUG,
		                    format='%(levelname)s: %(asctime)s: %(message)s')

		# Retrieve the object
		stream = self.s3.download_file('oca-data', f"private/{object_name}", file_path)


	def put_object_file(self, object_name, file_name):

		# Set up logging
		logging.basicConfig(level=logging.DEBUG,
		                    format='%(levelname)s: %(asctime)s: %(message)s')

		# Put the object into the bucket
		success = put_object(self.s3, 'oca-data', f"public/{object_name}", file_name)

		if success:
			logging.info(f'Added {object_name} to oca-data/public')
