from config import SUPABASE_KEY,SUPABASE_URL
from supabase import create_client, Client 
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
