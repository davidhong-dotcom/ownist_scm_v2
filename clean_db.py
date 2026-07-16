import toml
from supabase import create_client, Client
import os

secrets_path = os.path.join(".streamlit", "secrets.toml")
secrets = toml.load(secrets_path)
url = secrets["supabase"]["url"]
key = secrets["supabase"]["key"]

supabase: Client = create_client(url, key)

channels = ["도착보장", "신라면세점", "신세계면세점", "롯데면세점", "현대면세점"]

print("Starting Supabase DB cleanup for July 2026...")

for channel in channels:
    print(f"Cleaning data for channel: {channel} from 2026-07-01")
    res = supabase.table("shipping_data") \
        .delete() \
        .eq("channel", channel) \
        .gte("shipping_date", "2026-07-01") \
        .lte("shipping_date", "2026-07-31") \
        .execute()
    
    deleted_count = len(res.data) if hasattr(res, 'data') and res.data else 0
    print(f"Deleted records: {deleted_count}")

print("Clean up completed.")
