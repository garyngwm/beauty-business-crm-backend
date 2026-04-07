import os

from dotenv import load_dotenv
from supabase import AClient, acreate_client

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")


# New method to prevent disconnects
async def get_supabase_client():
    supabase: AClient = await acreate_client(url, key)
    return supabase
