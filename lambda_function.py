import boto3
import os
import time

ec2 = boto3.client("ec2")
ssm = boto3.client("ssm")
dynamodb = boto3.resource("dynamodb")

INSTANCE_ID = os.environ["INSTANCE_ID"]
IDLE_THRESHOLD = int(os.environ.get("IDLE_THRESHOLD", "3"))
STATE_TABLE = os.environ["STATE_TABLE"]

table = dynamodb.Table(STATE_TABLE)


def get_instance_state(instance_id):
    """Get the current state of an EC2 instance."""
    response = ec2.describe_instances(InstanceIds=[instance_id])
    return response["Reservations"][0]["Instances"][0]["State"]["Name"]


def check_ssh_connections(instance_id):
    """
    Check for active SSH connections on the instance.
    
    Returns:
        tuple: (has_connections: bool, connection_count: int)
    """
    print(f"Checking instance {instance_id} for active connections...")
    
    # Run SSM command to check SSH connections
    response = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={
            "commands": ["ss -tn state established '( sport = :22 )' | tail -n +2"]
        }
    )
    
    command_id = response["Command"]["CommandId"]
    
    # Wait for command to complete
    time.sleep(2)
    invocation = ssm.get_command_invocation(
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


def get_idle_count(instance_id):
    """Get the current idle count from DynamoDB."""
    record = table.get_item(Key={"InstanceId": instance_id}).get("Item")
    return record["IdleCount"] if record else 0


def update_idle_count(instance_id, count):
    """Update the idle count in DynamoDB."""
    table.put_item(Item={"InstanceId": instance_id, "IdleCount": count})


def reset_idle_count(instance_id):
    """Reset the idle count to 0."""
    if get_idle_count(INSTANCE_ID) != 0:
        print("Resetting idle counter.")
        update_idle_count(instance_id, 0)


def stop_instance(instance_id):
    """Stop the EC2 instance."""
    print("Idle threshold reached. Stopping instance.")
    ec2.stop_instances(InstanceIds=[instance_id])


def lambda_handler(event, context):
    """
    Main Lambda handler to monitor and stop idle EC2 instances.
    
    Checks for active SSH connections and stops the instance if it has been
    idle for IDLE_THRESHOLD consecutive checks.
    """
    state = get_instance_state(INSTANCE_ID)
    
    if state != "running":
        print(f"Instance {INSTANCE_ID} is not running ({state}). Skipping check.")
        reset_idle_count(INSTANCE_ID)
        return {"status": f"skipped-{state}"}
    
    # Check for active connections
    has_connections, connection_count = check_ssh_connections(INSTANCE_ID)
    
    if has_connections:
        print("Active connections detected.")
        reset_idle_count(INSTANCE_ID)
        return {
            "status": "active",
            "connection_count": connection_count
        }
    
    # Increment idle count
    idle_count = get_idle_count(INSTANCE_ID) + 1
    print(f"No connections. Idle count = {idle_count}/{IDLE_THRESHOLD}")
    
    if idle_count < IDLE_THRESHOLD:
        update_idle_count(INSTANCE_ID, idle_count)
        return {
            "status": "idle-but-not-stopping",
            "idle_count": idle_count
        }
    
    # Stop the instance
    stop_instance(INSTANCE_ID)
    reset_idle_count(INSTANCE_ID)
    
    return {
        "status": "stopped",
        "idle_count": idle_count
    }
