import os
import time

try:
    import boto3
except ImportError:  # pragma: no cover - only for local test environments
    boto3 = None


def get_config():
    return {
        "instance_id": os.environ["INSTANCE_ID"],
        "idle_threshold": int(os.environ.get("IDLE_THRESHOLD", "3")),
        "state_table": os.environ["STATE_TABLE"],
        "allow_stop": os.environ.get("ALLOW_STOP", "false").strip().lower()
        in {"1", "true", "yes", "on"},
    }


def get_ec2_client():
    if boto3 is None:
        raise RuntimeError("boto3 is required to create EC2 client")
    return boto3.client("ec2")


def get_ssm_client():
    if boto3 is None:
        raise RuntimeError("boto3 is required to create SSM client")
    return boto3.client("ssm")


def get_state_table(state_table):
    if boto3 is None:
        raise RuntimeError("boto3 is required to access DynamoDB")
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(state_table)


def get_instance_state(instance_id, ec2_client=None):
    """Get the current state of an EC2 instance."""
    ec2_client = ec2_client or get_ec2_client()
    response = ec2_client.describe_instances(InstanceIds=[instance_id])
    return response["Reservations"][0]["Instances"][0]["State"]["Name"]


def check_ssh_connections(instance_id, ssm_client=None):
    """
    Check for active SSH connections on the instance.
    
    Returns:
        tuple: (has_connections: bool, connection_count: int)
    """
    print(f"Checking instance {instance_id} for active connections...")
    
    # Run SSM command to check SSH connections
    ssm_client = ssm_client or get_ssm_client()
    response = ssm_client.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={
            "commands": ["ss -tn state established '( sport = :22 )' | tail -n +2"]
        }
    )
    
    command_id = response["Command"]["CommandId"]
    
    # Wait for command to complete
    time.sleep(2)
    invocation = ssm_client.get_command_invocation(
        CommandId=command_id,
        InstanceId=instance_id
    )
    
    output = invocation.get("StandardOutputContent", "").strip()
    print("Command output:", output)
    
    # Count connections (each line represents one connection)
    connection_count = len(output.splitlines()) if output else 0
    has_connections = connection_count > 0
    
    if has_connections:
        print(f"Active connections detected: {connection_count}")
    
    return has_connections, connection_count


def get_idle_count(instance_id, state_table):
    """Get the current idle count from DynamoDB."""
    record = state_table.get_item(Key={"InstanceId": instance_id}).get("Item")
    return record["IdleCount"] if record else 0


def update_idle_count(instance_id, count, state_table):
    """Update the idle count in DynamoDB."""
    state_table.put_item(Item={"InstanceId": instance_id, "IdleCount": count})


def reset_idle_count(instance_id, state_table):
    """Reset the idle count to 0."""
    if get_idle_count(instance_id, state_table) != 0:
        print("Resetting idle counter.")
        update_idle_count(instance_id, 0, state_table)


def stop_instance(instance_id, ec2_client=None):
    """Stop the EC2 instance."""
    ec2_client = ec2_client or get_ec2_client()
    print("Idle threshold reached. Stopping instance.")
    ec2_client.stop_instances(InstanceIds=[instance_id])


def lambda_handler(event, context):
    """
    Main Lambda handler to monitor and stop idle EC2 instances.
    
    Checks for active SSH connections and stops the instance if it has been
    idle for IDLE_THRESHOLD consecutive checks.
    """
    config = get_config()
    instance_id = config["instance_id"]
    idle_threshold = config["idle_threshold"]
    allow_stop = config["allow_stop"]
    state_table = get_state_table(config["state_table"])

    state = get_instance_state(instance_id)
    
    if state != "running":
        print(f"Instance {instance_id} is not running ({state}). Skipping check.")
        reset_idle_count(instance_id, state_table)
        return {"status": f"skipped-{state}"}
    
    # Check for active connections
    has_connections, connection_count = check_ssh_connections(instance_id)
    
    if has_connections:
        print("Active connections detected.")
        reset_idle_count(instance_id, state_table)
        return {
            "status": "active",
            "connection_count": connection_count
        }
    
    # Increment idle count
    idle_count = get_idle_count(instance_id, state_table) + 1
    print(f"No connections. Idle count = {idle_count}/{idle_threshold}")
    
    if idle_count < idle_threshold:
        update_idle_count(instance_id, idle_count, state_table)
        return {
            "status": "idle-but-not-stopping",
            "idle_count": idle_count
        }
    
    if not allow_stop:
        print("Idle threshold reached but ALLOW_STOP is false. Skipping stop.")
        reset_idle_count(instance_id, state_table)
        return {
            "status": "stop-suppressed",
            "idle_count": idle_count
        }

    # Stop the instance
    stop_instance(instance_id)
    reset_idle_count(instance_id, state_table)

    return {
        "status": "stopped",
        "idle_count": idle_count
    }
