import boto3
import json

# Initialize SageMaker runtime client
sagemaker_runtime = boto3.client("sagemaker-runtime", 
                                 region_name="us-east-2")

endpoint_name = "endpoint-deepseek-r1-nashid"

payload = {
    "inputs": "Are you better than GPT-4o for test generation and why?"
}

response = sagemaker_runtime.invoke_endpoint(
    EndpointName=endpoint_name,
    ContentType="application/json",
    Body=json.dumps(payload)
)

# Parse and print response
result = json.loads(response["Body"].read().decode("utf-8"))
print(result)
