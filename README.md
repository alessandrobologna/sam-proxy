# sam-proxy
use lambda/apigateway to implement a simple reverse proxy


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