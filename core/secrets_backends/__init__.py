# core/secrets_backends — optional pluggable secrets backends for ONTO.
# The default backend ("env") reads from environment variables and requires
# no additional dependencies. Alternative backends (vault, aws_ssm) are
# imported only when ONTO_SECRETS_BACKEND is set to their name.
