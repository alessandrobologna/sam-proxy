# sam-proxy
use lambda/apigateway to implement a simple basic auth/reverse proxy into a VPC ReST service


## Use case
Often is necessary to provide access to a third party SaaS provider to a private service running inside a VPC, and IP whitelisting is not an option because the SaaS provider can be using many CIDR blocks.
A simple solution is to run something like Nginx in a reverse proxy configuration and with some time of basic auth layer in front of it.
This simple implementation instead does it as a serverless service exposed through the API gateway.

## Setup

1. Create and activate a Python Virtual Environment:

```bash
python3 -m pip install --user virtualenv
python3 -m virtualenv venv
source venv/bin/activate
```

2. Install SAM

```bash
pip install --upgrade aws-sam-cli
```

Until SAM cli is not [yet including 1.11.0](https://github.com/awslabs/aws-sam-cli/issues/1198) also run

```bash
pip install --upgrade aws-sam-translator --force
```



## Configuration
Some environment variables need to be configured before deployment:
NAME|DESCRIPTION|DEFAULT
---|---|---
STAGE|an identifier for the deployment stage, such as "dev" or "prod"|dev
DEPLOYMENT|the name for this deployment, mapped to the service that you proxing, for instance "jenkins" |demo
UPSTREAM|The url for the service to be proxied|https://www.example.com/
PYTHON_VERSION|The python runtime versions|python3.7
KMS_KEY_ID|The KMS alias to encrypt/decrypt the secrets in Parameter Store|alias/aws/ssm
SUBNETS|A comma delimited list of subnets for the lambda funtion|subnet1,subnet2
SECURITY_GROUPS|A comma delimited list of security groups for the lambda funtion|sg1,sg2x

## Deployment

Run the `make bucket` target to create an s3 bucket for the code deployment. It needs to be done only once, and it will create a bucket named <aws-account-number>.sam.code.

After exporting the required environment variables, run `make all` to build the base lambda layer, and deploy to your AWS account. For subsequent deployments you can just run `make redeploy`


