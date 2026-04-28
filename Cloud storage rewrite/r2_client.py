import os
import json
import io
import zipfile
try:
    import boto3
    from botocore.config import Config
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

from typing import List, Optional, Dict
import logging

# Configuration from environment variables
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
R2_BUCKET_NAME = "bloodspire-arena"

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("r2_client")

def get_r2_client():
    """Initialize the boto3 client for Cloudflare R2."""
    if not HAS_BOTO3 or not all([R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL]):
        return None
    return boto3.client(
        service_name="s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )

_shown_diagnostic = False

def is_configured() -> bool:
    """Check if R2 credentials are provided."""
    global _shown_diagnostic
    client = get_r2_client()
    if client is None and not _shown_diagnostic:
        _shown_diagnostic = True
        if not HAS_BOTO3:
            print("  [R2 Config] Error: 'boto3' library not found. Run: python -m pip install boto3")
        else:
            missing = [k for k in ["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT_URL"] 
                       if not os.environ.get(k)]
            if missing:
                print(f"  [R2 Config] Error: Missing environment variables: {', '.join(missing)}")
    
    # Optional: Quick connectivity test if everything looks okay
    if client and not _shown_diagnostic:
        try:
            client.head_bucket(Bucket=R2_BUCKET_NAME)
            _shown_diagnostic = True
            print(f"  [R2 Config] Success: Connected to bucket '{R2_BUCKET_NAME}'")
        except Exception as e:
            _shown_diagnostic = True
            print(f"  [R2 Config] Error: Could not reach bucket. Check your Bucket Name and Permissions. {e}")
            return False
            
    return client is not None

def upload_team(turn: int, manager_id: str, team_id: str, upload_data: dict):
    """Upload a team file to the uploads/{turn}/ prefix."""
    client = get_r2_client()
    if not client: return
    fname = f"upload_{manager_id}_team{team_id}.json" if team_id else f"upload_{manager_id}.json"
    key = f"uploads/{turn}/{fname}"
    try:
        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=key,
            Body=json.dumps(upload_data, indent=2),
            ContentType="application/json"
        )
        logger.info(f"Uploaded team for manager {manager_id} to R2: {key}")
    except Exception as e:
        logger.error(f"R2 Upload failed: {e}")

def list_uploads(turn: int) -> Dict[str, dict]:
    """List and fetch all team uploads for a specific turn from R2."""
    client = get_r2_client()
    if not client: return {}
    prefix = f"uploads/{turn}/"
    uploads = {}
    try:
        response = client.list_objects_v2(Bucket=R2_BUCKET_NAME, Prefix=prefix)
        if "Contents" in response:
            for obj in response["Contents"]:
                key = obj["Key"]
                if not key.endswith(".json"): continue
                res = client.get_object(Bucket=R2_BUCKET_NAME, Key=key)
                data = json.loads(res["Body"].read().decode("utf-8"))
                
                mid = data.get("manager_id") or ""
                team_id = data.get("team_id") or (data.get("team") or {}).get("team_id", "")
                key_id = f"{mid}_team{team_id}" if team_id else mid
                uploads[key_id] = data
        return uploads
    except Exception as e:
        logger.error(f"R2 list_uploads failed: {e}")
        return {}

def delete_all_uploads(turn: int):
    """Remove all temporary team uploads for a turn after it has run."""
    client = get_r2_client()
    if not client: return
    prefix = f"uploads/{turn}/"
    try:
        response = client.list_objects_v2(Bucket=R2_BUCKET_NAME, Prefix=prefix)
        if "Contents" in response:
            delete_keys = {"Objects": [{"Key": obj["Key"]} for obj in response["Contents"]]}
            client.delete_objects(Bucket=R2_BUCKET_NAME, Delete=delete_keys)
            logger.info(f"Deleted all R2 uploads for turn {turn}")
    except Exception as e:
        logger.error(f"R2 delete_all_uploads failed: {e}")

def save_result(turn: int, manager_id: str, team_id: str, result_dict: dict):
    """Save a turn result file to the results/{turn}/ prefix."""
    client = get_r2_client()
    if not client: return
    fname = f"result_{manager_id}_team{team_id}.json" if team_id else f"result_{manager_id}.json"
    key = f"results/{turn}/{fname}"
    try:
        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=key,
            Body=json.dumps(result_dict, indent=2),
            ContentType="application/json"
        )
        logger.info(f"Saved result for manager {manager_id} to R2: {key}")
    except Exception as e:
        logger.error(f"R2 save_result failed: {e}")

def save_newsletter(turn: int, text: str):
    """Save the turn newsletter to R2."""
    client = get_r2_client()
    if not client: return
    key = f"results/{turn}/newsletter.txt"
    try:
        client.put_object(Bucket=R2_BUCKET_NAME, Key=key, Body=text, ContentType="text/plain")
        logger.info(f"Saved newsletter to R2: {key}")
    except Exception as e:
        logger.error(f"R2 save_newsletter failed: {e}")

def get_presigned_url(key: str, expires_in: int = 3600) -> Optional[str]:
    """Generate a temporary presigned URL for direct R2 download."""
    client = get_r2_client()
    if not client: return None
    try:
        return client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": R2_BUCKET_NAME, "Key": key},
            ExpiresIn=expires_in
        )
    except Exception as e:
        logger.error(f"R2 presigned URL generation failed for {key}: {e}")
        return None

def get_newsletter_url(turn: int) -> Optional[str]:
    return get_presigned_url(f"results/{turn}/newsletter.txt")

def cleanup_old_results(current_turn: int):
    """Delete result folders older than (current_turn - 5)."""
    client = get_r2_client()
    if not client: return
    try:
        response = client.list_objects_v2(Bucket=R2_BUCKET_NAME, Prefix="results/")
        if "Contents" in response:
            to_delete = []
            for obj in response["Contents"]:
                key = obj["Key"]
                parts = key.split("/")
                if len(parts) >= 2 and parts[1].isdigit():
                    turn_num = int(parts[1])
                    if turn_num <= current_turn - 5:
                        to_delete.append({"Key": key})
            if to_delete:
                for i in range(0, len(to_delete), 1000):
                    client.delete_objects(Bucket=R2_BUCKET_NAME, Delete={"Objects": to_delete[i:i+1000]})
                logger.info(f"Cleaned up {len(to_delete)} old R2 result objects")
    except Exception as e:
        logger.error(f"R2 cleanup_old_results failed: {e}")

def archive_turn(turn: int, turn_dir: str):
    """Creates a zip of all results for that turn and saves it under archives/ in R2."""
    client = get_r2_client()
    if not client or not os.path.exists(turn_dir): return
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(turn_dir):
            for file in files:
                zf.write(os.path.join(root, file), file)
    key = f"archives/turn_{turn:04d}_full_backup.zip"
    try:
        client.put_object(Bucket=R2_BUCKET_NAME, Key=key, Body=zip_buffer.getvalue(), ContentType="application/zip")
        logger.info(f"Archived turn {turn} to R2: {key}")
    except Exception as e:
        logger.error(f"R2 archive failed: {e}")