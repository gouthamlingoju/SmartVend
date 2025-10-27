from config import SUPABASE_KEY, SUPABASE_URL, DISPLAY_CODE_TTL_MINUTES
from supabase import create_client, Client
import asyncio
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional


# Create a synchronous supabase client (blocking). We'll call it from async wrappers.
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
	supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Pool flag used by main.py to detect DB availability
pool = bool(supabase)


async def init_pool():
	"""Initialize any connection/pool resources. For Supabase client this is a no-op
	but the API in `main.py` expects an async callable.
	"""
	global pool
	# already created above; still expose as async
	pool = bool(supabase)
	return


async def close_pool():
	# supabase-py doesn't expose a close; keep interface
	return


def _res_data(res):
	# supabase client may return an object with .data/.error or a dict
	if res is None:
		return None
	if hasattr(res, "data"):
		return res.data
	if isinstance(res, dict):
		return res.get("data")
	# fallback
	return None


def _res_error(res):
	if res is None:
		return None
	if hasattr(res, "error"):
		return res.error
	if isinstance(res, dict):
		return res.get("error")
	return None


def _now():
	return datetime.now(timezone.utc)


def _hash_code(code: str) -> str:
	return hashlib.sha256(code.encode('utf-8')).hexdigest()


async def get_machine_by_id(machine_id: str) -> Optional[dict]:
	"""Return machine row or None."""
	if not supabase:
		return None

	def _query():
		return supabase.table('machines').select('*').eq('id', machine_id).single().execute()

	res = await asyncio.to_thread(_query)
	data = _res_data(res)
	return data


async def upsert_machine(machine_id: str, api_key: str, ttl_minutes: Optional[int]):
	"""Create or update a machine row and generate a display code when registering.
	Returns the upserted row.
	"""
	if not supabase:
		return None

	ttl = int(ttl_minutes) if ttl_minutes else int(DISPLAY_CODE_TTL_MINUTES) if DISPLAY_CODE_TTL_MINUTES else 10
	display_code = f"{secrets.randbelow(900000)+100000}"  # 6-digit
	expires_at = (_now() + timedelta(minutes=ttl)).isoformat()

	payload = {
		'id': machine_id,
		'api_key': api_key,
		'display_code': display_code,
		'display_code_expires_at': expires_at,
		'last_seen_at': _now().isoformat()
	}

	def _upsert():
		return supabase.table('machines').upsert(payload).execute()

	res = await asyncio.to_thread(_upsert)
	data = _res_data(res)
	# upsert returns list of rows; return the first
	if isinstance(data, list) and data:
		row = data[0]
	else:
		row = data
	return row


async def get_machine_status_for_esp32(machine_id: str, provided_key: str):
	"""Return status info for machine if API key matches, otherwise None."""
	m = await get_machine_by_id(machine_id)
	if not m:
		return None
	expected = m.get('api_key')
	if not expected or not secrets.compare_digest(str(expected), str(provided_key)):
		return None

	# Build status object
	# include basic machine fields and current lock if any
	def _lock_query():
		return supabase.table('locks').select('*').eq('machine_id', machine_id).single().execute()

	res = await asyncio.to_thread(_lock_query) if supabase else None
	lock = _res_data(res) if res else None

	status = {
		'id': m.get('id'),
		'status': m.get('status'),
		'current_stock': m.get('current_stock'),
		'display_code': m.get('display_code'),
		'display_code_expires_at': m.get('display_code_expires_at'),
		'locked': bool(lock and lock.get('status') == 'locked'),
		'locked_by': lock.get('locked_by') if lock else None,
		'lock_expires_at': lock.get('expires_at') if lock else None,
	}
	return status


async def get_public_status(machine_id: str, client_id: Optional[str] = None):
	"""Return public view of machine status. Only reveal locked_by when it matches client_id."""
	m = await get_machine_by_id(machine_id)
	if not m:
		return None

	def _lock_query():
		return supabase.table('locks').select('*').eq('machine_id', machine_id).single().execute()

	res = await asyncio.to_thread(_lock_query) if supabase else None
	lock = _res_data(res) if res else None

	locked_by = None
	if lock and lock.get('status') == 'locked':
		if client_id and client_id == lock.get('locked_by'):
			locked_by = lock.get('locked_by')
		else:
			locked_by = None

	out = {
		'id': m.get('id'),
		'status': m.get('status'),
		'current_stock': m.get('current_stock'),
		'display_code_expires_at': m.get('display_code_expires_at'),
		'locked_by': locked_by,
		'expires_at': lock.get('expires_at') if lock else None,
	}
	return out


async def unlock_by_client_db(machine_id: str, client_id: str):
	"""Unlock machine if owned by client_id. Returns dict with possible error or new_display_code."""
	# fetch lock
	def _get_lock():
		return supabase.table('locks').select('*').eq('machine_id', machine_id).single().execute()

	res = await asyncio.to_thread(_get_lock)
	lock = _res_data(res)
	if not lock or lock.get('status') != 'locked':
		return {'error': 'no_lock'}
	if lock.get('locked_by') != client_id:
		return {'error': 'not_owner'}

	# delete lock
	def _delete_lock():
		return supabase.table('locks').delete().eq('machine_id', machine_id).execute()

	await asyncio.to_thread(_delete_lock)

	# generate new display code
	ttl = int(DISPLAY_CODE_TTL_MINUTES) if DISPLAY_CODE_TTL_MINUTES else 10
	display_code = f"{secrets.randbelow(900000)+100000}"
	expires_at = (_now() + timedelta(minutes=ttl)).isoformat()

	def _update_machine():
		return supabase.table('machines').update({
			'display_code': display_code,
			'display_code_expires_at': expires_at
		}).eq('id', machine_id).execute()

	await asyncio.to_thread(_update_machine)
	return {'new_display_code': display_code}


async def confirm_dispense_db(machine_id: str, transaction_id: str, dispensed: int):
	"""Mark transaction as completed and clear lock; return new display code.
	Returns {'error': ...} on failure or {'new_display_code': ...} on success.
	"""
	# fetch transaction
	def _get_tx():
		return supabase.table('transactions').select('*').eq('id', transaction_id).single().execute()

	res = await asyncio.to_thread(_get_tx)
	tx = _res_data(res)
	if not tx:
		return {'error': 'tx_not_found'}

	# update transaction
	def _update_tx():
		return supabase.table('transactions').update({
			'dispensed': dispensed,
			'payment_status': 'completed',
			'completed_at': _now().isoformat()
		}).eq('id', transaction_id).execute()

	await asyncio.to_thread(_update_tx)

	# clear lock for machine
	def _delete_lock():
		return supabase.table('locks').delete().eq('machine_id', machine_id).execute()

	await asyncio.to_thread(_delete_lock)

	# new display code
	ttl = int(DISPLAY_CODE_TTL_MINUTES) if DISPLAY_CODE_TTL_MINUTES else 10
	display_code = f"{secrets.randbelow(900000)+100000}"
	expires_at = (_now() + timedelta(minutes=ttl)).isoformat()

	def _update_machine():
		return supabase.table('machines').update({
			'display_code': display_code,
			'display_code_expires_at': expires_at,
			'status': 'idle'
		}).eq('id', machine_id).execute()

	await asyncio.to_thread(_update_machine)
	return {'new_display_code': display_code}


async def lock_by_code(client_id: str, code: str, ttl_minutes: int):
	"""Attempt to claim a machine using a display code. Returns None on server error or
	a dict with error or success info.
	"""
	# find machine by display_code and not expired
	def _find_machine():
		return supabase.table('machines').select('*').eq('display_code', code).execute()

	res = await asyncio.to_thread(_find_machine)
	data = _res_data(res)
	if not data:
		return {'error': 'code_not_found'}
	# data may be a list
	machine = data[0] if isinstance(data, list) else data

	# check expiry
	exp = machine.get('display_code_expires_at')
	if not exp or _now().isoformat() > exp:
		return {'error': 'code_not_found'}

	machine_id = machine.get('id')

	# check existing lock
	def _get_lock():
		return supabase.table('locks').select('*').eq('machine_id', machine_id).single().execute()

	res_lock = await asyncio.to_thread(_get_lock)
	lock = _res_data(res_lock)
	if lock and lock.get('status') == 'locked' and lock.get('expires_at') and _now().isoformat() < lock.get('expires_at'):
		return {'error': 'busy', 'machine_id': machine_id}

	# create/update lock
	ttl = int(ttl_minutes) if ttl_minutes else int(DISPLAY_CODE_TTL_MINUTES) if DISPLAY_CODE_TTL_MINUTES else 10
	expires_at = (_now() + timedelta(minutes=ttl)).isoformat()
	access_code_hash = _hash_code(code)

	payload = {
		'machine_id': machine_id,
		'locked_by': client_id,
		'access_code_hash': access_code_hash,
		'locked_at': _now().isoformat(),
		'expires_at': expires_at,
		'status': 'locked'
	}

	def _upsert_lock():
		return supabase.table('locks').upsert(payload).execute()

	await asyncio.to_thread(_upsert_lock)
	return {'machine_id': machine_id, 'status': 'locked', 'expires_at': expires_at}


async def trigger_dispense_db(machine_id: str, client_id: str, access_code: str, quantity: int, transaction_id: str, amount: int):
	"""Validate lock and record a transaction. Returns dict with error or success."""
	# fetch lock
	def _get_lock():
		return supabase.table('locks').select('*').eq('machine_id', machine_id).single().execute()

	res = await asyncio.to_thread(_get_lock)
	lock = _res_data(res)
	if not lock or lock.get('status') != 'locked':
		return {'error': 'no_lock'}
	if lock.get('locked_by') != client_id:
		return {'error': 'not_owner'}
	if lock.get('expires_at') and _now().isoformat() > lock.get('expires_at'):
		return {'error': 'expired'}

	if lock.get('access_code_hash') != _hash_code(access_code):
		return {'error': 'access_mismatch'}

	# create transaction row
	tx_payload = {
		'id': transaction_id,
		'machine_id': machine_id,
		'client_id': client_id,
		'access_code': access_code,
		'amount': amount,
		'quantity': quantity,
		'payment_status': 'paid',
		'created_at': _now().isoformat()
	}

	def _insert_tx():
		return supabase.table('transactions').insert(tx_payload).execute()

	await asyncio.to_thread(_insert_tx)

	# mark lock as consumed (keep row for history)
	def _update_lock():
		return supabase.table('locks').update({'status': 'consumed'}).eq('machine_id', machine_id).execute()

	await asyncio.to_thread(_update_lock)

	# update machine status
	def _update_machine():
		return supabase.table('machines').update({'status': 'dispatch_sent'}).eq('id', machine_id).execute()

	await asyncio.to_thread(_update_machine)

	return {'status': 'ok'}

