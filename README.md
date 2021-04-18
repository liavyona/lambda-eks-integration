# lambda-eks-integration

## Purpose

A simple Lambda that takes its event and send it into a Service in EKS cluster.

The Lambda authenticates to the EKS using IAM role and a ClusterRole defining it permissions.
The Service type is `ClusterIP`, so the Lambda uses the 
[Kubernetes Service proxy API](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.19/#create-connect-proxy-path-pod-v1-core)
which enables to send HTTP requests without exposing any endpoint. 

With such a solution, connecting Kubernetes applications environment into cloud resources cannot be easier.
The service is available only within the cluster but still can handle incoming events.
The service also doesn't have an Authentication & Authorization layer because it is being taken care of by the cluster.

_Note: The Lambda create a proxy channel between the event source and a Kubernetes Service.
But it can do any other Kubernetes action as long as it has the right permissions._
  
## Setup
1. Create a simple HTTP service in your Kubernetes cluster:
```bash
kubectl apply -f ./simple-service/simple-service.yml 
```
2. [Create an IAM role for your Lambda](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html)
3. [Add IAM role authentication to the EKS](https://docs.aws.amazon.com/eks/latest/userguide/add-user-role.html)
4. Add IAM role user cluster permissions
```bash
kubectl apply -f ./eks-Lambda/lambda-cluster-role.yml
```
5. Create a new Lambda with the IAM role and your code - Using zip or ECR image.
6. Configure the new Lambda with the following environment variables:
```bash
CLUSTER_NAME=YOUR EKS CLUSTER NAME
CLUSTER_REGION=YOUR EKS CLUSTER REGION
SERVICE_NAMESPACE= YOUR K8S SERVICE NAMESPACE
SERVICE_NAME= YOUR K8S SERVICE NAME
SERVICE_PORT= YOUR K8S SERVICE PORT
SERVICE_REQUEST_TIMEOUT= TIMEOUT
SERVICE_REQUEST_METHOD=THE SERVICE EXPOSED METHOD
SERVICE_REQUEST_PATH=THE SERVICE URI
```

## Usage

Test your Lambda with such as event:
```json
{
  "name": "John",
  "age": 24
}
```
The response should look like:
```json
{
  "lambda_request_id": "12341234-1234-1234-1234-123412341234",
  "lambda_arn": "arn:aws:lambda:YOUR_REGION:YOUR_ACCOUNT:function:YOUR_FUNCTION",
  "status_code": 200,
  "event": {
    "name": "John",
    "age": 24
  },
  "response": {
    "status": 200,
    "data": "{'message':'Hello world from John','event':{'name':'John','age':24}}"
  }
}
```



