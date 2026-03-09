import boto3
from functools import lru_cache
from typing import Tuple
from django.conf import settings
from botocore.config import Config


@lru_cache(maxsize=1)
def get_s3_client():
    """Return a boto3 S3 client configured from Django settings."""
    client_kwargs = {}
    access_key = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
    secret_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)
    region_name = getattr(settings, 'AWS_S3_REGION_NAME', None)
    signature_version = getattr(settings, 'AWS_S3_SIGNATURE_VERSION', None)

    if access_key and secret_key:
        client_kwargs['aws_access_key_id'] = access_key
        client_kwargs['aws_secret_access_key'] = secret_key
    if region_name:
        client_kwargs['region_name'] = region_name
    if signature_version:
        client_kwargs['config'] = Config(signature_version=signature_version)

    return boto3.client('s3', **client_kwargs)


def parse_s3_uri(uri: str) -> Tuple[str, str]:
    """Split an s3://bucket/key URI into bucket and key parts."""
    if not uri or not uri.startswith('s3://'):
        raise ValueError(f'Invalid S3 URI: {uri}')

    without_scheme = uri[5:]
    if '/' not in without_scheme:
        raise ValueError(f'Invalid S3 URI: {uri}')
    bucket, key = without_scheme.split('/', 1)
    if not bucket or not key:
        raise ValueError(f'Invalid S3 URI: {uri}')
    return bucket, key
