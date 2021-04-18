"""
Lambda function that transfer an event into a service inside an EKS cluster
"""
# Build-ins
import re
import os
from http import HTTPStatus
from typing import List, Dict, Any
from tempfile import NamedTemporaryFile
from base64 import urlsafe_b64encode, decodebytes
# Third party
from aws_lambda_powertools.utilities.typing import LambdaContext
from urllib3.response import HTTPResponse
from boto3.session import Session
from botocore.signers import RequestSigner
from kubernetes import client as kube_client
from kubernetes.client import ApiClient, ApiException

# Configuration
EKS_CLUSTER_NAME_PARAMETER = 'x-k8s-aws-id'
EKS_TOKEN_PREFIX = 'k8s-aws-v1.'
STS_URL = 'https://sts.{}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15'
STS_TOKEN_EXPIRES_IN = 60
DEFAULT_REGION = 'eu-central-1'
DEFAULT_SERVICE_PORT = 8080
DEFAULT_SERVICE_REQUEST_TIMEOUT = 30
DEFAULT_SERVICE_REQUEST_METHOD = "GET"
DEFAULT_SERVICE_REQUEST_PATH = "hello"

# Environment variables
CLUSTER_NAME_ENV = "CLUSTER_NAME"
CLUSTER_REGION_ENV = "CLUSTER_REGION"
SERVICE_NAMESPACE_ENV = "SERVICE_NAMESPACE"
SERVICE_NAME_ENV = "SERVICE_NAME"
SERVICE_PORT_ENV = "SERVICE_PORT"
SERVICE_REQUEST_TIMEOUT_ENV = "SERVICE_REQUEST_TIMEOUT"
SERVICE_REQUEST_METHOD_ENV = "SERVICE_REQUEST_METHOD"
SERVICE_REQUEST_PATH_ENV = "SERVICE_REQUEST_PATH"


def _get_cluster_info(cluster_name: str, region: str) -> Dict[str, Any]:
    """
    Gets the cluster information using EKS describe cluster method
    :param cluster_name: The cluster name
    :param region: The region of the cluster
    :return: A dictionary with information about the cluster
    """
    session = Session()
    eks = session.client('eks', region_name=region)
    return eks.describe_cluster(name=cluster_name)['cluster']


def _get_cluster_endpoint(cluster_info: Dict[str, Any]) -> str:
    """
    Gets the cluster endpoint
    :param cluster_info: The cluster information from boto3 describe_cluster API
    :return: (str) The endpoint of the cluster
    """
    return cluster_info['endpoint']


def _get_cluster_certificate(cluster_info: Dict[str, Any]) -> bytes:
    """
    Gets the cluster certificate
    :param cluster_info: The cluster information from boto3 describe_cluster API
    :return: (str) The endpoint of the cluster
    """
    encoded_ca = cluster_info['certificateAuthority']['data'].encode()
    return decodebytes(encoded_ca)


def _get_bearer_token(cluster_name: str, region: str = DEFAULT_REGION) -> str:
    """
    Generates a bearer token for the EKS cluster's authentication
    :param cluster_name: The cluster name
    :param region: The region of the EKS cluster
    :return: (str) Bearer token for the EKS cluster
    """
    session = Session()
    client = session.client('sts', region_name=region)
    print(f"Lambda's AWS identity: {client.get_caller_identity()}")
    service_id = client.meta.service_model.service_id
    signer = RequestSigner(
        service_id,
        region,
        'sts',
        'v4',
        session.get_credentials(),
        session.events
    )

    params = {
        'method': 'GET',
        'url': STS_URL.format(region),
        'body': {},
        'headers': {
            EKS_CLUSTER_NAME_PARAMETER: cluster_name
        },
        'context': {}
    }

    signed_url = signer.generate_presigned_url(
        params,
        region_name=region,
        expires_in=STS_TOKEN_EXPIRES_IN,
        operation_name=''
    )
    base64_url = urlsafe_b64encode(signed_url.encode('utf-8')).decode('utf-8')
    # remove any base64 encoding padding:
    return EKS_TOKEN_PREFIX + re.sub(r'=*', '', base64_url)


def _authenticate_to_eks_cluster(cluster_endpoint: str, ca_cert_path: str, sts_token: str) -> None:
    """
    Authenticates against the EKS cluster
    :param cluster_endpoint: The clutser HTTPS endpoint
    :param ca_cert_path: The EKS CA certificate path
    :param sts_token: The STS token
    """
    configuration = kube_client.Configuration()
    configuration.host = cluster_endpoint
    configuration.verify_ssl = True
    configuration.debug = False
    configuration.ssl_ca_cert = ca_cert_path
    configuration.api_key = {"authorization": "Bearer " + sts_token}
    kube_client.Configuration.set_default(configuration)


def _list_namespaced_services(namespace: str) -> List[str]:
    """
    Lists all the services inside a kubernetes namespace.
    :param namespace: The Kubernetes namespace
    :return: (List[str]) List of all services names.
    """
    v1_api = kube_client.CoreV1Api()
    print(f"Fetch all services in {namespace} namespace")
    try:
        services = [service.metadata.name
                    for service in v1_api.list_namespaced_service(namespace).items]
    except ApiException as err:
        print(f"Cannot list Kubernetes services in {namespace} namespace due to {str(err)}")
        raise err
    print(f"Services in {namespace} namespace: {services}")
    return services


def _proxy_http_request_kubernetes_service(service: str, port: int, path: str, namespace: str,
                                           method: str, headers: dict,
                                           body: Any, timeout: int) -> HTTPResponse:
    """
    Sends a proxy HTTP request to a Kubernetes service using Kubernetes raw API
    :param service: The Kubernetes service
    :param port: Service's port
    :param path: Request path
    :param namespace: The Kubernetes namespace
    :param method: Request method
    :param headers: Request headers
    :param body: Request body
    :param timeout: Request timeout
    :raise ApiException: In case of proxy pass error to the service
    :return: (HTTPResponse) The service's response
    """
    api_client = ApiClient()
    full_path = f"/api/v1/namespaces/{namespace}/services/{service}:{port}/proxy/{path}"
    print(f"Sending {method} request to  {full_path} with body {body}")
    response: HTTPResponse = api_client.call_api(
        resource_path=full_path,
        method=method,
        header_params={"Accept": "*/*"}.update(headers),
        body=body,
        response_type="str",
        auth_settings=["BearerToken"],
        async_req=False,
        _preload_content=False,
        _return_http_data_only=True,
        _request_timeout=timeout)
    return response


def handler(event: Dict, context: LambdaContext):
    """
    Lambda event handler
    """
    cluster_name = os.environ.get(CLUSTER_NAME_ENV)
    cluster_region = os.environ.get(CLUSTER_REGION_ENV, DEFAULT_REGION)
    service = os.environ.get(SERVICE_NAME_ENV)
    port = int(os.environ.get(SERVICE_PORT_ENV, DEFAULT_SERVICE_PORT))
    namespace = os.environ.get(SERVICE_NAMESPACE_ENV)
    request_method = os.environ.get(SERVICE_REQUEST_METHOD_ENV, DEFAULT_SERVICE_REQUEST_METHOD)
    request_path = os.environ.get(SERVICE_REQUEST_PATH_ENV, DEFAULT_SERVICE_REQUEST_PATH)
    request_timeout = int(os.environ.get(SERVICE_REQUEST_TIMEOUT_ENV, DEFAULT_SERVICE_REQUEST_TIMEOUT))
    print(f"Cluster name {cluster_name} in region {cluster_region}")

    cluster_info = _get_cluster_info(cluster_name, cluster_region)
    cluster_endpoint = _get_cluster_endpoint(cluster_info)
    cluster_ca_cert = _get_cluster_certificate(cluster_info)
    sts_token = _get_bearer_token(cluster_name, cluster_region)
    with NamedTemporaryFile(suffix=".pem") as ca_file:
        ca_file.write(cluster_ca_cert)
        ca_file.seek(0)
        _authenticate_to_eks_cluster(cluster_endpoint=cluster_endpoint, ca_cert_path=ca_file.name, sts_token=sts_token)
        available_services = _list_namespaced_services(namespace)
        if service not in available_services:
            raise ValueError(f"There is no such Kubernetes service {service} in namespace {namespace}")
        response = _proxy_http_request_kubernetes_service(
            service=service,
            port=port,
            path=request_path,
            namespace=namespace,
            method=request_method,
            headers={},
            body=event,
            timeout=request_timeout
        )
        assert response.status == HTTPStatus.OK.value
        return {
            "lambda_request_id": context.aws_request_id,
            "lambda_arn": context.invoked_function_arn,
            "status_code": HTTPStatus.OK.value,
            "event": event,
            "response": {
                "status": response.status,
                "data": response.data
            }
        }
