import boto3
import logging
import json
import io
import base64
import os
import re
import requests
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all 
import aws_lambda_logging

log = logging.getLogger()
patch_all()
ssm = boto3.client('ssm')


def proxy_handler(event, context):
    aws_lambda_logging.setup(
        level=os.environ.get('LOGLEVEL', 'INFO'),
        aws_request_id=context.aws_request_id,
        boto_level='CRITICAL'
    )

    log.info(event)
    response = forward_request(event)
    log.info(dict(**response.headers))
    buffer = io.BytesIO()
    raw = response.raw

    chunk = raw.read(4096)
    while len(chunk)>0:
        buffer.write(chunk)
        chunk = raw.read(4096)

    response.headers.pop('content-length','')
    response.headers.pop('accept-ranges','')
    
    result = {
        'isBase64Encoded' : True,
        'statusCode': response.status_code,
        'body': base64.b64encode(buffer.getvalue()).decode('utf-8'),
        'headers': dict(**response.headers)
    }
    log.info(result)
    return result


@xray_recorder.capture()
def forward_request(event):
    url = os.environ['UPSTREAM'] + event['path']
    method =  event['httpMethod']
    headers = event['headers']

    xray_subsegment = xray_recorder.current_subsegment()
    xray_subsegment.put_annotation("url", url) 
    xray_subsegment.put_annotation("method", method) 

    # set upstream host header
    headers['Host'] = re.match('https?://([^/]+)',os.environ['UPSTREAM'])[1]
    # do not encode if not requested
    if not headers.get('Accept-Encoding'):
        headers['Accept-Encoding'] = ''
    # do not pass authorization header to upstream
    headers.pop('Authorization','')

    # handle post payload 
    body = event.get('body')
    if body and event.get('isBase64Encoded'):
        body = base64.b64decode(body).decode('utf-8') 
        
    response = requests.request(
        method, 
        url,
        headers=event['headers'],
        params=event.get('multiValueQueryStringParameters',{}),
        stream=True,
        data = body if body else '' 
    )
    return response


def auth_handler(event, context):
    aws_lambda_logging.setup(
        level=os.environ.get('LOGLEVEL', 'INFO'),
        aws_request_id=context.aws_request_id,
        boto_level='CRITICAL'
    )
    try:
        authorization_user='Unknown'
        authorization = event['authorizationToken'] if 'TOKEN' == event['type'] else event['headers']['Authorization'] 
        if authorization:
            authorization_method, authorization_value = authorization.split(' ')
            authorization = base64.b64decode(authorization_value).decode('utf-8')
            authorization_user, authorization_password = authorization.split(':')
            parameter = ssm.get_parameter(
                Name=os.environ['SSM_AUTHORIZATION_PATH']+authorization_user,
                WithDecryption=True
            ).get('Parameter')
            if parameter['Value'] == authorization_password:
                log.info({
                    'Method':authorization_method,
                    'User':authorization_user,
                    'Effect': 'Allow'
                })
                effective_resource = re.match('(arn:aws:execute-api:[^:]+:[^:]+:[^/]+/[^/]+).*',event['methodArn'])[1]
                policy = {
                    'principalId' : authorization_user,
                    'policyDocument': {
                        'Version': '2012-10-17',
                        'Statement': [{
                            'Action': 'execute-api:Invoke',
                            'Effect': 'Allow',
                            'Resource': f'{effective_resource}/*'
                        }]
                    }
                }
                log.info({
                    'Authorization' : 'Success',
                    'Policy' : policy
                })
                return policy

            # authorization failed                
            log.info({
                'Method':authorization_method,
                'User':authorization_user,
                'Effect': 'Deny'
            })
    except Exception as e:
        log.error(e)

    raise Exception('Unauthorized')
