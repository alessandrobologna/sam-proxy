import base64
import io
import json
import logging
import os
import re

import aws_lambda_logging
import backoff
import boto3
import botocore
import requests
from aws_xray_sdk.core import patch_all, xray_recorder
from cachetools import TTLCache, cached

log = logging.getLogger()
patch_all()
ssm = boto3.client('ssm')

ssm_cache = TTLCache(maxsize=1000, ttl=300)

@xray_recorder.capture()
def proxy_handler(event, context):
    aws_lambda_logging.setup(
        level=os.environ.get('LOGLEVEL', 'INFO'),
        aws_request_id=context.aws_request_id,
        boto_level='CRITICAL'
    )

    log.info(event)
    response = forward_request(event)
    log.info(dict(**response.headers)) 
    buffer = get_response_buffer(response.raw)
    
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
def sanitize_request_headers(headers):
    # set upstream host header
    headers['Host'] = re.match('https?://([^/]+)',os.environ['UPSTREAM'])[1]
    # do not encode if not requested
    if not headers.get('Accept-Encoding'):
        headers['Accept-Encoding'] = ''
    # do not pass authorization header to upstream
    headers.pop('Authorization','')
    return headers

@xray_recorder.capture()
def forward_request(event):
    url = os.environ['UPSTREAM'] + event['path']
    method =  event['httpMethod']
    headers = event['headers']

    xray_subsegment = xray_recorder.current_subsegment()
    xray_subsegment.put_annotation("url", url) 
    xray_subsegment.put_annotation("method", method) 

    headers = sanitize_request_headers(headers)

    # handle post payload 
    body = event.get('body')
    if body and event.get('isBase64Encoded'):
        body = base64.b64decode(body).decode('utf-8') 
        
    return make_request(method, url, event, body)

@xray_recorder.capture()
@backoff.on_exception(backoff.expo, requests.exceptions.ConnectionError, max_time=10)
def make_request(method, url, event, body):
    response = requests.request(
        method, 
        url,
        headers=event['headers'],
        params=event.get('multiValueQueryStringParameters',{}),
        stream=True,
        data = body if body else '' 
    )
    return response

@xray_recorder.capture()
def get_response_buffer(raw):
    buffer = io.BytesIO()
    chunk = raw.read(4096)
    while len(chunk)>0:
        buffer.write(chunk)
        chunk = raw.read(4096)
    return buffer

@xray_recorder.capture()
def auth_handler(event, context):
    aws_lambda_logging.setup(
        level=os.environ.get('LOGLEVEL', 'INFO'),
        aws_request_id=context.aws_request_id,
        boto_level='CRITICAL'
    )
    authorization_user='Unknown'
    authorization_method = 'N/A'
    try:
        authorization_header = event['authorizationToken'] if 'TOKEN' == event['type'] else event['headers']['Authorization'] 
        if authorization_header:
            authorization_method, authorization_value = authorization_header.split(' ')
            authorization_user, authorization_password = base64.b64decode(authorization_value).decode('utf-8').split(':')
            parameter = get_ssm_param(authorization_user)
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

    except Exception as e:
        log.error(e)

    # authorization failed                
    log.info({
        'Method':authorization_method,
        'User':authorization_user,
        'Effect': 'Deny'
    })
    raise Exception('Unauthorized')

@xray_recorder.capture()
@cached(ssm_cache)
@backoff.on_exception(backoff.expo, botocore.exceptions.ClientError, max_time=10)
def get_ssm_param(authorization_user):
    parameter = ssm.get_parameter(
        Name=os.environ['SSM_AUTHORIZATION_PATH']+authorization_user,
        WithDecryption=True
    ).get('Parameter')
    return parameter
