"""
core/secrets_backends/aws_ssm.py

AWS Systems Manager Parameter Store (SSM) secrets backend for ONTO.

Reads secrets from SSM using the boto3 library.
boto3 is an optional dependency — install it with:
    pip install boto3

Required environment variables:
  ONTO_SSM_PREFIX    — SSM parameter name prefix (e.g. "/onto/prod/")
  AWS_REGION         — AWS region (or set via ~/.aws/config or EC2 metadata)

Expects the following SSM parameters (SecureString type):
  {ONTO_SSM_PREFIX}db_encryption_key
  {ONTO_SSM_PREFIX}auth_passphrase_hash

IAM permissions required:
  ssm:GetParameter on arn:aws:ssm:<region>:<account>:parameter/<prefix>*
  kms:Decrypt on the KMS key used to encrypt SecureString parameters

Usage (via core/config.py):
  from core.secrets_backends.aws_ssm import get_secret
  value = get_secret("db_encryption_key")
"""

import os
from typing import Optional


def get_secret(key: str) -> Optional[str]:
    """
    Fetch a single secret value from AWS SSM Parameter Store.

    Arguments:
        key: The parameter suffix (e.g. "db_encryption_key"). The full
             parameter name is "{ONTO_SSM_PREFIX}{key}".

    Returns:
        The parameter value as a string, or None if the parameter does not exist.

    Raises:
        ImportError: If boto3 is not installed.
        RuntimeError: If AWS configuration is missing or the fetch fails.
    """
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        raise ImportError(
            "The 'boto3' package is required for the AWS SSM secrets backend. "
            "Install it with: pip install boto3"
        )

    prefix = os.environ.get("ONTO_SSM_PREFIX", "/onto/")
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION"))
    parameter_name = f"{prefix}{key}"

    try:
        client_kwargs = {"service_name": "ssm"}
        if region:
            client_kwargs["region_name"] = region
        client = boto3.client(**client_kwargs)
        response = client.get_parameter(
            Name=parameter_name,
            WithDecryption=True,
        )
        return response["Parameter"]["Value"]
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code == "ParameterNotFound":
            return None
        raise RuntimeError(
            f"Failed to fetch SSM parameter '{parameter_name}': {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"Failed to fetch SSM parameter '{parameter_name}': {exc}"
        ) from exc
